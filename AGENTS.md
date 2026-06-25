# AGENTS.md

Guidance for future agents and contributors working on this Research Agent project.

## Project Goal

This repo is a resume-ready Research Agent MVP. It accepts an open-ended research question, searches the web, reads pages, extracts evidence, retrieves RAG context, and generates a citation-grounded Markdown report.

The main demo query is:

```powershell
.\.venv\Scripts\python.exe -m research_agent.cli "compare youtube and bilibili" --mode web
```

The expected result in `web` mode is real source URLs, never `mock://` URLs.

## Core Pipeline

The pipeline is coordinated by `src/research_agent/pipeline.py`:

1. `Planner` creates sub-questions and search queries.
2. `Searcher` retrieves sources.
3. `Reader` fetches and cleans page text.
4. `VectorStore` chunks documents and retrieves RAG context.
5. `Extractor` creates evidence and claims.
6. `Synthesizer` creates a deterministic template report.
7. `GeminiReportSynthesizer` optionally replaces the template with Gemini output.
8. `CitationChecker` verifies every claim has evidence references.
9. `ResearchRunStore` saves reproducible traces.

## Runtime Defaults

Production/demo defaults:

- Search mode: `web`
- LLM mode: `gemini`
- Embedding mode: `gemini`
- RAG: enabled
- Gemini text model: `gemini-2.5-flash`
- Gemini fallback models: `gemini-2.5-flash`, `gemini-2.5-flash-lite`, `gemini-2.5-pro`

Offline test path:

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m research_agent.cli "compare Cursor and Windsurf" --mode mock --llm-mode mock --embedding-mode hash
```

## Search Mode Rules

Preserve these behaviors:

- `--mode web` must use only real web sources.
- `--mode web` must fail loudly if live search fails.
- `--mode web` must never return `mock://` sources.
- `--mode auto` may fall back to mock data.
- If `auto` falls back to mock, the report must include Runtime Notes with the web search failure reason.
- UI defaults must not use mock.
- Final reports must not expose retrieval internals such as `rank=` or `score=`.

Current live search flow is implemented in `src/research_agent/searcher.py`:

- `LiveWebSearcher`
- `DuckDuckGoSearcher`
- `WikipediaSearcher`
- `BingSearcher`
- `AutoSearcher`
- `MockSearcher`

For entity comparisons such as `compare youtube and bilibili`, the planner splits entity queries and the Wikipedia fallback can produce real entity URLs.

Search result ordering should prefer official sites, official docs, Wikipedia, news, and then other pages. Avoid regressions where all sources are Wikipedia unless no better live sources are available.

## Web UI Contract

Files:

- `src/research_agent/web/index.html`
- `src/research_agent/web/app.js`
- `src/research_agent/web/styles.css`
- `src/research_agent/web_server.py`
- `src/research_agent/api.py`

The browser app must send these fields to `/api/research`:

```json
{
  "question": "compare youtube and bilibili",
  "mode": "web",
  "llm_mode": "gemini",
  "embedding_mode": "gemini",
  "rag": true,
  "save": true
}
```

The page should display:

- requested search mode
- actual search mode
- LLM mode
- embedding provider
- source count
- source URLs
- search failure reason when search fails

If the UI shows `mock://research/general-method` for a web run, treat that as a bug.

## Gemini Notes

Gemini code lives in:

- `src/research_agent/gemini_client.py`
- `src/research_agent/llm_synthesizer.py`
- `src/research_agent/embeddings.py`

Text generation must use Gemini `generateContent`:

```text
POST /models/{model}:generateContent
```

Embedding calls use Gemini embedding APIs. Gemini retry logic should continue retrying transient HTTP 429 and 5xx failures.

If Gemini generation fails, the app may return the deterministic template report, but it must include Runtime Notes and metadata with the failure reason.

If Gemini embeddings fail, RAG may fall back to hash embeddings, but it must record the embedding failure reason.

For report generation, do not fall back to the template after a single 429 or 503. Gemini should use exponential backoff, then try the next configured Gemini model. Runtime Notes and metadata should show provider, model, retry count, attempted models, and fallback reason.

Model chain can be configured with:

```powershell
$env:GEMINI_MODELS='gemini-2.5-flash,gemini-2.5-flash-lite,gemini-2.5-pro'
```

Never paste real API keys into docs, examples, commits, or responses. If a secret appears in chat or local files, tell the user to rotate it.

## Reader Notes

`src/research_agent/reader.py` should keep page text clean for demo quality.

Preferred extraction order:

1. Wikipedia article body only, around `.mw-parser-output`.
2. `trafilatura`.
3. `readability-lxml`.
4. `beautifulsoup4`.
5. Standard-library HTML parser fallback.

Do not regress Wikipedia extraction back to full-page text with language lists, sidebars, edit links, or footer content.

## Report Notes

The final report should stay clean for portfolio demos:

- Use a valid Markdown table in `Comparison Snapshot`, usually `| Feature | A | B |`.
- Show evidence, conclusion, and sources.
- Keep retrieval ranks, vector scores, and low-level RAG diagnostics in metadata, trace JSON, or the UI trace tab.

## Run Commands

CLI with live web and Gemini:

```powershell
cd "D:\codex research project"
$env:GEMINI_API_KEY='your-api-key'
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m research_agent.cli "compare youtube and bilibili" --mode web
```

CLI web search without Gemini dependency:

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m research_agent.cli "compare youtube and bilibili" --mode web --llm-mode mock --embedding-mode hash
```

Dependency-free Web UI:

```powershell
cd "D:\codex research project"
$env:GEMINI_API_KEY='your-api-key'
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m research_agent.web_server --port 8010
```

FastAPI Web UI:

```powershell
cd "D:\codex research project"
$env:GEMINI_API_KEY='your-api-key'
$env:PYTHONPATH='src'
.\.venv\Scripts\uvicorn.exe research_agent.api:app --host 127.0.0.1 --port 8011
```

Important: environment variables must be set in the same PowerShell session that starts the server. Browser requests use the server process environment, not a separate terminal's environment.

## Verification

Run the full tests:

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Compile check:

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m compileall src tests
```

JavaScript syntax check when Node is available:

```powershell
node --check src\research_agent\web\app.js
```

Manual web-mode check:

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m research_agent.cli "compare youtube and bilibili" --mode web --llm-mode mock --embedding-mode hash --no-save
```

Confirm:

- `metadata.actual_search_mode` is `web`.
- Sources include real `https://...` URLs.
- Sources do not include `mock://`.

## Common Debugging Notes

- If the browser still shows old mock results, it is probably connected to an old server process or port. Start a fresh server on a new port.
- If CLI works but UI does not, check whether `app.js` sends `mode=web` and whether the server process has the right environment variables.
- If web search fails in `web` mode, show the failure reason. Do not silently fall back to mock.
- If Gemini fails in the app but works in CLI, restart the web server from the same shell where `GEMINI_API_KEY` is set.
- Windows console output may need UTF-8-safe handling; the CLI configures stdout/stderr for this.

## Editing Guidelines

- Keep changes scoped to the relevant module.
- Preserve reproducible traces and citation-grounded output.
- Prefer tests for behavior involving fallback, provider errors, modes, and UI request contracts.
- Do not remove mock mode; it is needed for offline tests.
- Do not make mock mode the default for the browser app.
