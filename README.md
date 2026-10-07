# Margin: talk to a PDF

The PDF API extracts a document with PyMuPDF4LLM and stores both its full Markdown and numbered pages in SQLite. A separate Pipecat voice service uses Gemini speech, the page search and get-page tools, and a background LangGraph worker that writes evidence-grounded relationships to Neo4j. The voice answer uses the page tools; the graph is stored for future use.

## Setup

Python 3.13 and Node.js are required. Docker is used for Neo4j.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m nltk.downloader -d .venv/nltk_data punkt_tab
cp .env.example .env
```

If the NLTK downloader fails with a certificate error on macOS, install the same data from NLTK's official repository:

```sh
mkdir -p .venv/nltk_data/tokenizers
curl -fL https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/tokenizers/punkt_tab.zip -o /tmp/punkt_tab.zip
unzip -q /tmp/punkt_tab.zip -d .venv/nltk_data/tokenizers
```

Set `GEMINI_API_KEY` and a new `NEO4J_PASSWORD` in `.env`. The optional `PDF_DATABASE_PATH` selects a different SQLite file. Both Python services and Alembic read this file. Start Docker Desktop before the next command.

```sh
docker compose up -d
.venv/bin/alembic upgrade head
```

Start the three services in separate terminals:

```sh
.venv/bin/uvicorn app:app --port 8000
.venv/bin/python -m voice_agent.bot -t webrtc
cd frontend && npm install && npm run dev
```

Open the URL printed by Vite. Upload a PDF, select it, and start a conversation. The browser needs microphone permission. The voice runner listens on port 7860 by default; the Vite development proxy connects the two Python services.

## PDF API

- `POST /documents` accepts multipart `file` and returns the document ID.
- `GET /documents/{id}` returns full Markdown and PDF metadata.
- `GET /documents/{id}/search?pattern=...&lines_before=2&lines_after=2&use_regex=false` returns the total occurrence count and up to 50 matches with page context.
- `GET /documents/{id}/pages/{page_number}` returns the entire extracted page.
- `GET /docs` has interactive API documentation.

Example:

```sh
curl -F "file=@document.pdf" http://127.0.0.1:8000/documents
```

The search tool accepts literal text or a regex. Context line counts are limited to 0–10, and regex execution has a timeout. PDFs uploaded before the `document_pages` migration have page data only if they had one page. Upload older multi-page PDFs again to enable page tools.

## Context-aware knowledge graph

The background LangGraph worker now runs five observable stages:

1. **Context:** accumulate tool evidence for the original question; load actual retrieved pages and adjacent context from SQLite; read existing entities, claims and predicates from Neo4j.
2. **Interpret:** use recent conversation turns to resolve the inquiry into a concise topic and focus. Conversation guides discovery but is not factual evidence.
3. **Extract:** propose only durable entities and relationships directly useful to the inquiry. Prefer an evidence-backed detail on an existing entity for a small standalone fact. Propose a revision when source evidence corrects a saved relationship, or a retraction when it directly contradicts one. Extraction is limited to six claims, two entity updates and two retractions.
4. **Validate:** check exact citations and entity endpoints, then independently review each proposed addition, update or retraction. Missing, duplicate or unsupported verdicts fail closed. Absence from the current pages is not grounds to remove a saved claim.
5. **Persist:** atomically apply reviewed changes. Identical claims deduplicate across retries and sessions. Reviewed entity details accumulate unless one is explicitly corrected. A corrected relation retains its claim ID and replaces stale citations; a retracted relation and any empty orphan entity are removed.

The graph uses `KnowledgeEntity`, `KnowledgeClaim` and `KnowledgeEvidence`. A claim connects its subject, object and source quotes. Inquiry topics no longer create graph nodes; older topic records remain stored but are not shown in the atlas. Exact canonical names/types and known aliases can be reused; similar names alone do not authorize a merge. Model review is fallible, so the UI exposes source evidence for inspection.

Context is bounded to 12 retrieved pages plus neighbors, up to 70,000 characters. Long pages are windowed near retrieved text. Activity reports windowed/omitted pages and omitted registry entries. Up to 300 existing entities and 200 existing claims are supplied for reuse or correction. The graph does not influence spoken answers yet.

Legacy `Question`, `Concept` and `Page` records remain untouched. The atlas also displays earlier `Concept` relationships and their saved source quotes in amber, labeled **not independently reviewed**. New evidence-reviewed entities and claims appear alongside them. Historical records are not silently labeled as reviewed, and no legacy backfill is performed.

Neo4j must be reachable when a voice session starts. Image-only pages require OCR; source quality affects results. Enrichment runs independently of voice output. Its in-memory queue is bounded; overflow is reported, and shutdown allows up to 120 seconds for pending work. Pending jobs do not survive a server crash.

## Knowledge atlas

Select a document in **Conversation**, then open **Knowledge atlas**. The screen loads the entire saved graph for that document across sessions through `GET /documents/{id}/graph` on the voice service. It checks every five seconds while visible and reloads when you return to the atlas. Document changes clear previous data and discard stale responses. The voice room stays active while this second screen is open.

- Search entities and explore incoming/outgoing relationships.
- Select a relationship to inspect qualifiers, exact quotes and page references. **Read source page** loads the original extracted page.
- Pan, zoom or fit the graph; the entity explorer also supports keyboard navigation.
- Inspect source-backed details attached to an entity without adding another node.
- Export the saved graph, including citations, as JSON.
- Continue speaking, mute or end the session without leaving the atlas.

Large graphs use a deterministic spiral layout instead of an expensive force-layout pass; graph data and the searchable list are not capped. A failed refresh preserves the last loaded graph and reports an error.

## Live activity

The conversation workspace contains document controls, a live transcript and a filterable timeline. Expand any step for original arguments and output side by side. Reviewed claims also appear as relationship cards. The graph is persistent; transcripts and execution history are session-local.

Voice tools report `search_document` and `get_page`; the graph reports all five stages, with timestamps, duration, status and question IDs. The finalized user turn from Pipecat's context aggregator supplies the question before the LLM's document tools run. Tools capture that question at invocation so a later utterance cannot reattribute an in-flight result. Persistence reports an actual save summary. A bounded best-effort telemetry queue keeps reporting independent of agent execution. Large events are chunked over the data channel and reassembled without changing their content. Unfinished steps are marked disconnected when the session ends. No model-internal reasoning is displayed.

Use **Export session** before starting another conversation to retain its transcript and activity. Restart the Python voice service after these changes, then refresh the frontend. No new package installation or SQLite migration is needed; Neo4j constraints are created at worker startup.

## Validation

```sh
npm --prefix frontend run build
node --test frontend/src/activity-stream.test.js
.venv/bin/python -m unittest discover -s tests -v
```

Optional local Neo4j integration check; synthetic fixture writes are always rolled back:

```sh
.venv/bin/python -m tests.check_graph_store
```

References: [LangGraph state/node API](https://docs.langchain.com/oss/python/langgraph/choosing-apis), [Neo4j async transactions](https://neo4j.com/docs/api/python-driver/current/async_api.html). Context7 supplied current documentation rather than an exact LangGraph 1.2.13 snapshot; pipeline tests also run against installed dependencies.
