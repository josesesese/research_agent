# Research Agent MVP

A citation-grounded Research Agent project suitable for a resume or GitHub portfolio.

The current version implements project steps 1-8:

1. Project skeleton
2. Core data models
3. CLI MVP
4. Mock research pipeline
5. Reproducible run storage
6. Live web search and page reading
7. FastAPI backend
8. Local Web UI
9. Gemini-backed synthesis, RAG, and local vector database

## What It Does

Given a research question such as:

```bash
python -m research_agent.cli "compare Cursor and Windsurf"
```

The agent runs this pipeline:

1. `Planner` decomposes the question into research sub-questions.
2. `Searcher` retrieves sources from mock data or live web search providers.
3. `Reader` fetches and cleans page text, or reads mock documents.
4. `Extractor` extracts evidence and claim candidates.
5. `Synthesizer` generates a Markdown report.
6. `CitationChecker` verifies every claim has evidence references.
7. `ResearchRunStore` saves `report.md` and `trace.json` for reproducibility.
8. `LocalVectorStore` persists document chunks and retrieves RAG context.
9. Optional Gemini synthesis rewrites the final report using retrieved context.

The final report intentionally stays presentation-friendly: it shows a summary, comparison table, evidence, conclusion, and sources. Retrieval ranks and vector scores stay in the structured trace/UI diagnostics, not in the report body.

## Web UI

Start the dependency-free local browser app:

```bash
python -m research_agent.web_server
```

Or run it from this Codex workspace:

```powershell
cd "D:\codex research project"
$env:PYTHONPATH='src'
& 'C:\Users\asus\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m research_agent.web_server --port 8000
```

Then open:

```text
http://127.0.0.1:8000
```

The UI includes:

- Research question input
- Mock, auto, and web search modes
- Template, auto, and Gemini LLM modes
- Hash, auto, and Gemini embedding modes
- RAG retrieval toggle
- Save trace toggle
- Generated report view
- Sources, evidence, claims, RAG chunks, and saved artifact paths

By default, the UI uses:

- Search mode: `web`
- LLM mode: `gemini`
- Embedding mode: `gemini`
- RAG: enabled

That default path performs live web search and requires `GEMINI_API_KEY` for Gemini synthesis. Use Mock + Template + Hash in the UI only for offline tests.

In `web` mode, the UI does not fall back to mock data. If live search fails, the page shows the search failure reason instead of displaying `mock://` sources. The result toolbar and Trace tab show requested search mode, actual search mode, LLM mode, embedding provider, and source URLs.

## Gemini API And RAG

The production default uses live search, Gemini report synthesis, Gemini embeddings, and the local JSON vector database.

Set your key first:

```powershell
$env:GEMINI_API_KEY='your-api-key'
$env:GEMINI_MODEL='gemini-2.5-flash'
$env:GEMINI_EMBEDDING_MODEL='gemini-embedding-2'
$env:GEMINI_MAX_RETRIES='3'
$env:GEMINI_RETRY_BACKOFF_SECONDS='1.0'
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m research_agent.cli "compare Cursor and Windsurf"
```

Gemini requests automatically retry transient failures such as HTTP 429 and 5xx responses. If Gemini report generation still fails, the app returns the deterministic template report with a `Runtime Notes` section and stores the failure reason in `metadata.llm_failure_reason`. If Gemini embeddings fail, RAG falls back to local hash embeddings and records `metadata.embedding_failure_reason`.

For report generation, Gemini now tries a model fallback chain before using the template fallback:

```text
gemini-2.5-flash -> gemini-2.5-flash-lite -> gemini-2.5-pro
```

HTTP 429 and 5xx errors use exponential backoff. Runtime Notes and metadata include the LLM provider, model used, retry count, attempted models, and fallback reason.

Override the model chain if needed:

```powershell
$env:GEMINI_MODELS='gemini-2.5-flash,gemini-2.5-flash-lite,gemini-2.5-pro'
$env:GEMINI_RETRY_MAX_BACKOFF_SECONDS='8.0'
```

For offline testing without an API key, explicitly use the mock path:

```powershell
.\.venv\Scripts\python.exe -m research_agent.cli "compare Cursor and Windsurf" --mode mock --llm-mode mock --embedding-mode hash
```

RAG writes vectors to:

```text
vector_store/research_agent_vectors.json
```

Disable RAG if needed:

```bash
python -m research_agent.cli "compare Cursor and Windsurf" --no-rag
```

## FastAPI Backend

Install the web dependencies:

```bash
python -m pip install -e .[web]
```

Or:

```bash
python -m pip install -r requirements.txt
```

Run the FastAPI backend:

```bash
uvicorn research_agent.api:app --reload --port 8001
```

From the source tree without installing the package:

```powershell
cd "D:\codex research project"
$env:PYTHONPATH='src'
uvicorn research_agent.api:app --reload --port 8001
```

API endpoints:

```text
GET  /api/health
POST /api/research
GET  /
```

Example request:

```bash
curl -X POST http://127.0.0.1:8001/api/research \
  -H "Content-Type: application/json" \
  -d '{"question":"compare Cursor and Windsurf","mode":"web","llm_mode":"gemini","embedding_mode":"gemini","rag":true,"save":true}'
```

## Quick Start

Install as an editable local package:

```bash
python -m pip install -e .
export GEMINI_API_KEY="your-api-key"
research-agent "compare Cursor and Windsurf"
```

Or run directly from the source tree:

```powershell
cd "D:\codex research project"
$env:GEMINI_API_KEY='your-api-key'
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m research_agent.cli "compare Cursor and Windsurf"
```

Offline smoke test:

```powershell
.\.venv\Scripts\python.exe -m research_agent.cli "compare Cursor and Windsurf" --mode mock --llm-mode mock --embedding-mode hash
```

## Search Modes

The CLI supports three modes:

```bash
python -m research_agent.cli "compare Cursor and Windsurf" --mode mock
python -m research_agent.cli "compare Cursor and Windsurf" --mode web
python -m research_agent.cli "compare Cursor and Windsurf" --mode auto
```

- `mock`: deterministic offline demo mode.
- `web`: live web search plus web page reading; it never falls back to mock data.
- `auto`: try live web search first, then fall back to mock data if search fails.

Live search ranks sources for demo quality:

1. Official sites
2. Official documentation
3. Wikipedia
4. High-quality news
5. Other pages

DuckDuckGo and Bing parsers use multiple result selectors and report concrete parse failure reasons when result pages cannot be parsed.

You can also set:

```bash
RESEARCH_AGENT_SEARCH_MODE=auto
RESEARCH_AGENT_LLM_MODE=gemini
RESEARCH_AGENT_EMBEDDING_MODE=gemini
RESEARCH_AGENT_OUTPUT_DIR=runs
```

## Reader Quality

`WebReader` tries to produce clean readable text:

1. Wikipedia pages: extract only the article body around `.mw-parser-output`.
2. Normal pages: try `trafilatura`.
3. If that fails: try `readability-lxml`.
4. If that fails: try `beautifulsoup4`.
5. Final fallback: a small standard-library HTML parser.

Install the recommended extraction dependencies with:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Reproducible Runs

Every CLI run saves a reproducible trace by default:

```text
runs/<run_id>/
  report.md
  trace.json
```

`trace.json` includes the question, plan, sources, fetched documents, evidence, claims, citation check result, and final Markdown report.

Use `--no-save` to skip trace storage:

```bash
python -m research_agent.cli "compare Cursor and Windsurf" --no-save
```

Write a separate report file:

```bash
python -m research_agent.cli "compare Cursor and Windsurf" --output examples/cursor_vs_windsurf_report.md
```

## Example Artifacts

- `examples/cursor_vs_windsurf_report.md`
- `examples/cursor_vs_windsurf_report.json`

## Project Structure

```text
src/research_agent/
  cli.py
  pipeline.py
  models.py
  planner.py
  searcher.py
  reader.py
  extractor.py
  synthesizer.py
  citation_checker.py
  storage.py
  service.py
  gemini_client.py
  embeddings.py
  vector_store.py
  llm_synthesizer.py
  api.py
  fastapi_server.py
  web_server.py
  mock_data.py
  web/
    index.html
    styles.css
    app.js
tests/
  test_pipeline.py
examples/
```

## Resume Bullet

Built a citation-grounded Research Agent that decomposes open-ended research questions, retrieves web sources, extracts structured evidence, and generates comparative reports with reproducible traces and verifiable citations.

## Current Limitations

- Live search tries multiple public web sources, so availability can still vary by network and rate limits.
- Extraction is still deterministic; Gemini is used for optional final report synthesis.
- Fast-changing facts such as pricing should be verified from official sources before external use.





根据这个项目，总结一份报告，说明你用了哪些框架，使用了哪些语言来设计这个项目，项目中遇到了什么问题，你是如何解决的，最终结果优秀在哪里
