"""Realtime PDF voice agent. Run with `python -m voice_agent.bot`."""

import os
import asyncio
from contextlib import suppress

from fastapi import HTTPException
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import EndFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair, LLMUserAggregatorParams
from pipecat.processors.aggregators.llm_response_universal import AssistantTurnStoppedMessage
from pipecat.processors.aggregators.llm_response_universal import UserTurnMessageAddedMessage
from pipecat.runner.run import app
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.google.gemini_live.stt import GeminiSTTService
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.google.tts import GeminiTTSService
from pipecat.transports.base_transport import TransportParams
from pipecat.workers.runner import WorkerRunner
from sqlalchemy import select

from database import Document, DocumentPage, SessionLocal
from voice_agent.graph import GraphEnricher
from voice_agent.activity import ActivityStream
from voice_agent.graph_store import graph_driver, read_knowledge
from voice_agent.tools import build_tools


SYSTEM_INSTRUCTION = """You answer spoken questions about the selected PDF.
Before stating a document fact, call search_document. Use get_page when a result needs more context.
You may call either tool several times. Cite page numbers in your spoken answer.
If the document does not support an answer, say so. Never invent a document fact.
Keep answers brief and natural for speech. The background knowledge graph is not an answer source."""


@app.get("/documents")
async def list_documents():
    with SessionLocal() as session:
        rows = session.execute(
            select(Document.id, Document.filename, Document.title, Document.page_count)
            .join(DocumentPage, DocumentPage.document_id == Document.id)
            .distinct()
            .order_by(Document.created_at.desc())
        ).all()
    return [dict(row._mapping) for row in rows]


@app.get("/documents/{document_id}/graph")
async def document_graph(document_id: str):
    with SessionLocal() as session:
        if session.get(Document, document_id) is None:
            raise HTTPException(404, "Document not found")
    try:
        async with asyncio.timeout(15):
            async with graph_driver() as driver:
                async with driver.session() as session:
                    return await session.execute_read(read_knowledge, document_id)
    except Exception as error:
        raise HTTPException(503, "Knowledge graph unavailable. Check Neo4j and restart the voice service.") from error


async def bot(runner_args: RunnerArguments):
    body = runner_args.body if isinstance(runner_args.body, dict) else {}
    document_id = body.get("document_id")
    with SessionLocal() as session:
        if not document_id or session.get(DocumentPage, (document_id, 1)) is None:
            raise HTTPException(400, "Select a PDF with extracted page data")

    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("Set GEMINI_API_KEY before starting the voice agent")

    activity = ActivityStream()
    activity_task = None
    graph = GraphEnricher(document_id, key, activity)
    try:
        await graph.start()
        transport = await create_transport(
            runner_args,
            {"webrtc": lambda: TransportParams(audio_in_enabled=True, audio_out_enabled=True)},
        )
        stt = GeminiSTTService(
            api_key=key,
            settings=GeminiSTTService.Settings(model=os.getenv("GEMINI_STT_MODEL", "gemini-3.5-transcribe-live")),
        )
        llm = GoogleLLMService(
            api_key=key,
            settings=GoogleLLMService.Settings(
                model=os.getenv("GEMINI_LLM_MODEL", "gemini-3.1-flash-lite"),
                system_instruction=SYSTEM_INSTRUCTION,
                max_tokens=512,
            ),
        )
        tts = GeminiTTSService(
            api_key=key,
            use_genai=True,
            settings=GeminiTTSService.Settings(
                model=os.getenv("GEMINI_TTS_MODEL", "gemini-3.1-flash-tts-preview"),
                voice=os.getenv("GEMINI_TTS_VOICE", "Kore"),
                language="en-US",
            ),
        )
        context = LLMContext(tools=build_tools(document_id, graph, activity))
        user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
        )
        @user_aggregator.event_handler("on_user_turn_message_added")
        async def on_user_turn_message_added(_aggregator, message: UserTurnMessageAddedMessage):
            if message.content and message.content.strip():
                graph.observe_query(message.content.strip())

        pipeline = Pipeline([
            transport.input(), stt, user_aggregator, llm, tts,
            transport.output(), assistant_aggregator,
        ])
        worker = PipelineWorker(
            pipeline,
            params=PipelineParams(enable_metrics=True),
            idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
        )

        activity_task = asyncio.create_task(activity.send(worker.rtvi.send_server_message))

        @assistant_aggregator.event_handler("on_assistant_turn_stopped")
        async def on_assistant_turn_stopped(_aggregator, message: AssistantTurnStoppedMessage):
            graph.observe_answer(message.content or "")
            await worker.rtvi.send_server_message({
                "type": "assistant-turn",
                "text": message.content or "",
                "interrupted": message.interrupted,
            })

        @transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(_transport, _client):
            await worker.queue_frame(EndFrame())

        runner = WorkerRunner(handle_sigint=False)
        await runner.add_workers(worker)
        await runner.run()
    finally:
        try:
            await graph.close()
        finally:
            if activity_task:
                activity_task.cancel()
                with suppress(asyncio.CancelledError):
                    await activity_task


def main():
    from pipecat.runner.run import main as run_pipecat
    run_pipecat()


if __name__ == "__main__":
    main()
