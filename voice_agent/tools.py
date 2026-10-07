"""The two PDF tools available to the voice LLM."""

import asyncio

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.direct_function import tool_options
from pipecat.services.llm_service import FunctionCallParams
import regex

from database import SessionLocal
from page_tools import get_page, search_pages


def build_tools(document_id: str, graph_enricher, activity) -> list[FunctionSchema]:
    @tool_options(cancel_on_interruption=True)
    async def search_document(params: FunctionCallParams) -> None:
        arguments = params.arguments or {}
        question = graph_enricher.capture_question()

        def run() -> dict:
            with SessionLocal() as session:
                return search_pages(
                    session,
                    document_id,
                    arguments.get("pattern", ""),
                    arguments.get("lines_before", 2),
                    arguments.get("lines_after", 2),
                    arguments.get("use_regex", False),
                )

        async def execute():
            try:
                return await asyncio.to_thread(run)
            except (LookupError, ValueError, regex.error) as error:
                return {"status": "error", "message": str(error)}

        result = await activity.track(
            "voice", params.function_name, dict(arguments), execute,
            call_id=params.tool_call_id,
        )
        graph_enricher.observe_tool_result(result, question)
        await params.result_callback(result)

    @tool_options(cancel_on_interruption=True)
    async def read_page(params: FunctionCallParams) -> None:
        arguments = params.arguments or {}
        question = graph_enricher.capture_question()

        def run() -> dict:
            with SessionLocal() as session:
                return get_page(session, document_id, arguments.get("page_number"))

        async def execute():
            try:
                return await asyncio.to_thread(run)
            except (LookupError, ValueError) as error:
                return {"status": "error", "message": str(error)}

        result = await activity.track(
            "voice", params.function_name, dict(arguments), execute,
            call_id=params.tool_call_id,
        )
        graph_enricher.observe_tool_result(result, question)
        await params.result_callback(result)

    return [
        FunctionSchema(
            name="search_document",
            description=(
                "Search the selected PDF by word, phrase, or regular expression. "
                "Returns the total occurrence count and up to 50 matches with page numbers and nearby lines. "
                "Search before answering factual questions."
            ),
            properties={
                "pattern": {"type": "string", "description": "Text or regex pattern to find."},
                "use_regex": {"type": "boolean", "description": "Whether pattern is a regular expression."},
                "lines_before": {"type": "integer", "description": "Context lines before each match, 0 to 10."},
                "lines_after": {"type": "integer", "description": "Context lines after each match, 0 to 10."},
            },
            required=["pattern", "use_regex", "lines_before", "lines_after"],
            handler=search_document,
        ),
        FunctionSchema(
            name="get_page",
            description="Get the entire extracted Markdown content of one page from the selected PDF.",
            properties={
                "page_number": {"type": "integer", "description": "One-based page number from search results."},
            },
            required=["page_number"],
            handler=read_page,
        ),
    ]
