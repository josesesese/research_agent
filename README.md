# Research Agent MVP

A citation-grounded Research Agent project suitable for a resume or GitHub portfolio.

The current version implements project steps 1-6:

1. Project skeleton
2. Core data models
3. CLI MVP
4. Mock research pipeline
5. Reproducible run storage
6. Live web search and page reading with mock fallback

## What It Does

Given a research question such as:

```bash
python -m research_agent.cli "compare Cursor and Windsurf"
```

The agent runs this pipeline:

1. `Planner` decomposes the question into research sub-questions.
2. `Searcher` retrieves sources from mock data or live DuckDuckGo HTML search.
3. `Reader` fetches and cleans page text, or reads mock documents.
4. `Extractor` extracts evidence and claim candidates.
5. `Synthesizer` generates a Markdown report.
6. `CitationChecker` verifies every claim has evidence references.
7. `ResearchRunStore` saves `report.md` and `trace.json` for reproducibility.

## Quick Start

Install as an editable local package:

```bash
python -m pip install -e .
research-agent "compare Cursor and Windsurf"
```

Or run directly from the source tree:

```powershell
cd "D:\codex research project"
$env:PYTHONPATH='src'
& 'C:\Users\asus\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m research_agent.cli "compare Cursor and Windsurf"
```

## Search Modes

The CLI supports three modes:

```bash
python -m research_agent.cli "compare Cursor and Windsurf" --mode mock
python -m research_agent.cli "compare Cursor and Windsurf" --mode web
python -m research_agent.cli "compare Cursor and Windsurf" --mode auto
```

- `mock`: deterministic offline demo mode.
- `web`: live DuckDuckGo search plus web page reading.
- `auto`: try live web search first, then fall back to mock data if search fails.

You can also set:

```bash
RESEARCH_AGENT_SEARCH_MODE=auto
RESEARCH_AGENT_OUTPUT_DIR=runs
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
  mock_data.py
tests/
  test_pipeline.py
examples/
```

## Resume Bullet

Built a citation-grounded Research Agent that decomposes open-ended research questions, retrieves web sources, extracts structured evidence, and generates comparative reports with reproducible traces and verifiable citations.

## Current Limitations

- Live search uses DuckDuckGo HTML results, so availability can vary by network and rate limits.
- The MVP does not call an LLM yet; extraction and synthesis are deterministic.
- Fast-changing facts such as pricing should be verified from official sources before external use.
