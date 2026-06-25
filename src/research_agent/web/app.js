const form = document.querySelector("#researchForm");
const questionInput = document.querySelector("#questionInput");
const saveTrace = document.querySelector("#saveTrace");
const enableRag = document.querySelector("#enableRag");
const runButton = document.querySelector("#runButton");
const resetButton = document.querySelector("#resetButton");
const copyButton = document.querySelector("#copyButton");
const connectionStatus = document.querySelector("#connectionStatus");
const activeMode = document.querySelector("#activeMode");
const stepItems = Array.from(document.querySelectorAll("#stepList li"));
const reportTitle = document.querySelector("#reportTitle");
const runSummary = document.querySelector("#runSummary");
const emptyState = document.querySelector("#emptyState");
const reportOutput = document.querySelector("#reportOutput");
const sourceList = document.querySelector("#sourceList");
const evidenceList = document.querySelector("#evidenceList");
const claimList = document.querySelector("#claimList");
const traceBox = document.querySelector("#traceBox");
const ragList = document.querySelector("#ragList");
const tabButtons = Array.from(document.querySelectorAll(".tab-button"));
const tabViews = Array.from(document.querySelectorAll(".tab-view"));

let currentMarkdown = "";
let progressTimer = null;
const DEFAULT_SEARCH_MODE = "web";
const DEFAULT_QUESTION = "compare youtube and bilibili";

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = questionInput.value.trim();
  const formData = new FormData(form);
  const mode = formData.get("mode") || DEFAULT_SEARCH_MODE;
  const llmMode = formData.get("llmMode") || "gemini";
  const embeddingMode = formData.get("embeddingMode") || "gemini";
  if (!question) {
    setStatus("Question needed", "error");
    questionInput.focus();
    return;
  }

  setRunning(true);
  setStatus("Running", "active");
  activeMode.textContent = mode;
  startProgress();

  try {
    const response = await fetch("/api/research", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        mode,
        llm_mode: llmMode,
        embedding_mode: embeddingMode,
        rag: enableRag.checked,
        save: saveTrace.checked,
      }),
    });

    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || payload.detail || "Research failed.");
    }

    finishProgress();
    renderResult(payload);
    if (isMockFallback(payload)) {
      setStatus("Mock fallback", "error");
    } else {
      setStatus("Complete", "ok");
    }
    activateTab("report");
  } catch (error) {
    stopProgress();
    setStatus("Failed", "error");
    renderError(error.message, {
      mode,
      llmMode,
      embeddingMode,
      rag: enableRag.checked,
    });
  } finally {
    setRunning(false);
  }
});

resetButton.addEventListener("click", () => {
  questionInput.value = DEFAULT_QUESTION;
  setRadioValue("mode", DEFAULT_SEARCH_MODE);
  setRadioValue("llmMode", "gemini");
  setRadioValue("embeddingMode", "gemini");
  enableRag.checked = true;
  saveTrace.checked = true;
  currentMarkdown = "";
  reportTitle.textContent = "No run yet";
  runSummary.textContent = "Search mode: web";
  reportOutput.innerHTML = "";
  hideReportOutput();
  sourceList.innerHTML = "";
  evidenceList.innerHTML = "";
  claimList.innerHTML = "";
  traceBox.textContent = "No saved run yet.";
  ragList.innerHTML = "";
  copyButton.disabled = true;
  setStatus("Ready", "ok");
  activeMode.textContent = DEFAULT_SEARCH_MODE;
  resetProgress();
});

copyButton.addEventListener("click", async () => {
  if (!currentMarkdown) {
    return;
  }
  await navigator.clipboard.writeText(currentMarkdown);
  copyButton.textContent = "Copied";
  window.setTimeout(() => {
    copyButton.textContent = "Copy Markdown";
  }, 1200);
});

tabButtons.forEach((button) => {
  button.addEventListener("click", () => activateTab(button.dataset.tab));
});

function setRunning(isRunning) {
  runButton.disabled = isRunning;
  resetButton.disabled = isRunning;
  runButton.textContent = isRunning ? "Running..." : "Run research";
}

function setStatus(label, state) {
  connectionStatus.textContent = label;
  connectionStatus.dataset.state = state;
}

function startProgress() {
  resetProgress();
  let index = 0;
  setStep(index);
  progressTimer = window.setInterval(() => {
    index = Math.min(index + 1, stepItems.length - 1);
    setStep(index);
  }, 700);
}

function finishProgress() {
  stopProgress();
  stepItems.forEach((item) => {
    item.classList.remove("active");
    item.classList.add("done");
  });
}

function stopProgress() {
  if (progressTimer) {
    window.clearInterval(progressTimer);
    progressTimer = null;
  }
}

function resetProgress() {
  stopProgress();
  stepItems.forEach((item) => {
    item.classList.remove("active", "done");
  });
}

function setStep(activeIndex) {
  stepItems.forEach((item, index) => {
    item.classList.toggle("done", index < activeIndex);
    item.classList.toggle("active", index === activeIndex);
  });
}

function activateTab(name) {
  tabButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === name);
  });
  tabViews.forEach((view) => {
    view.classList.toggle("active", view.id === `${name}View`);
  });
}

function setRadioValue(name, value) {
  const input = document.querySelector(`input[name="${name}"][value="${value}"]`);
  if (input) {
    input.checked = true;
  }
}

function renderResult(payload) {
  const report = payload?.report || {};
  const metadata = report.metadata || {};
  currentMarkdown = typeof report.markdown === "string" ? report.markdown : "";
  if (!currentMarkdown.trim()) {
    throw new Error("Backend response did not include report.markdown.");
  }
  reportTitle.textContent = report.question?.text || "Research report";
  renderRunSummary(metadata, report.sources || []);
  reportOutput.innerHTML = renderMarkdown(currentMarkdown);
  showReportOutput();
  copyButton.disabled = !currentMarkdown;

  renderSources(report.sources || []);
  renderEvidence(report.evidence || [], report.sources || []);
  renderClaims(report.claims || []);
  renderRag(report.retrieved_chunks || [], report.sources || []);
  renderTrace(payload.saved_run, metadata, report.sources || []);
  updateModeStatus(metadata);
}

function showReportOutput() {
  emptyState.hidden = true;
  reportOutput.hidden = false;
}

function hideReportOutput() {
  reportOutput.hidden = true;
  emptyState.hidden = false;
}

function renderError(message, request) {
  currentMarkdown = "";
  const safeMessage = message || "Research failed.";
  reportTitle.textContent = "Run failed";
  runSummary.innerHTML = `
    <span class="badge warning">requested search: ${escapeHtml(request.mode || DEFAULT_SEARCH_MODE)}</span>
    <span class="badge">llm: ${escapeHtml(request.llmMode || "unknown")}</span>
    <span class="badge">embedding: ${escapeHtml(request.embeddingMode || "unknown")}</span>
    <span class="badge">rag: ${escapeHtml(String(Boolean(request.rag)))}</span>
  `;
  reportOutput.innerHTML = `
    <section class="error-panel">
      <h2>Search failed</h2>
      <p>${escapeHtml(safeMessage)}</p>
    </section>
  `;
  showReportOutput();
  sourceList.innerHTML = `<div class="source-item muted">No sources returned because the run failed.</div>`;
  evidenceList.innerHTML = `<div class="evidence-item muted">No evidence extracted.</div>`;
  claimList.innerHTML = `<div class="claim-item muted">No claims extracted.</div>`;
  ragList.innerHTML = `<div class="evidence-item muted">No RAG chunks retrieved.</div>`;
  traceBox.textContent = [
    `requested_search_mode: ${request.mode || DEFAULT_SEARCH_MODE}`,
    `requested_llm_mode: ${request.llmMode || "unknown"}`,
    `requested_embedding_mode: ${request.embeddingMode || "unknown"}`,
    `rag_enabled: ${String(Boolean(request.rag))}`,
    `failure_reason: ${safeMessage}`,
  ].join("\n");
  copyButton.disabled = true;
  activeMode.textContent = `${request.mode || DEFAULT_SEARCH_MODE} failed`;
  activateTab("report");
}

function renderRunSummary(metadata, sources) {
  const requestedSearch = metadata.requested_search_mode || "unknown";
  const actualSearch = metadata.actual_search_mode || "unknown";
  const sourceCount = sources.length;
  const mockSources = sources.filter((source) => String(source.url || "").startsWith("mock://")).length;
  const warning = requestedSearch !== "mock" && actualSearch === "mock";
  const sourceLabel = mockSources ? `${sourceCount} sources, ${mockSources} mock` : `${sourceCount} sources`;
  runSummary.innerHTML = `
    <span class="badge ${warning ? "warning" : ""}">requested search: ${escapeHtml(requestedSearch)}</span>
    <span class="badge ${warning ? "warning" : ""}">actual search: ${escapeHtml(actualSearch)}</span>
    <span class="badge">llm: ${escapeHtml(metadata.actual_llm_mode || "unknown")}</span>
    <span class="badge">embedding: ${escapeHtml(metadata.actual_embedding_provider || "unknown")}</span>
    <span class="badge">${escapeHtml(sourceLabel)}</span>
  `;
}

function updateModeStatus(metadata) {
  const requestedSearch = metadata.requested_search_mode || "unknown";
  const actualSearch = metadata.actual_search_mode || "unknown";
  activeMode.textContent = requestedSearch === actualSearch ? actualSearch : `${requestedSearch} -> ${actualSearch}`;
}

function isMockFallback(payload) {
  const metadata = payload?.report?.metadata || {};
  return metadata.requested_search_mode !== "mock" && metadata.actual_search_mode === "mock";
}

function renderSources(sources) {
  if (!sources.length) {
    sourceList.innerHTML = `<div class="source-item muted">No sources returned.</div>`;
    return;
  }

  sourceList.innerHTML = sources
    .map((source, index) => {
      const title = escapeHtml(source.title || `Source ${index + 1}`);
      const url = escapeHtml(source.url || "");
      const snippet = escapeHtml(source.snippet || "No snippet.");
      const type = escapeHtml(source.source_type || "unknown");
      return `
        <article class="source-item">
          <h3>S${index + 1}. ${title}</h3>
          <div class="meta-row">
            <span class="badge">${type}</span>
            ${source.published_at ? `<span class="badge">${escapeHtml(source.published_at)}</span>` : ""}
          </div>
          <p>${snippet}</p>
          <a href="${url}" target="_blank" rel="noreferrer">${url}</a>
        </article>
      `;
    })
    .join("");
}

function renderEvidence(evidence, sources) {
  const sourceIndex = new Map(sources.map((source, index) => [source.id, index + 1]));
  if (!evidence.length) {
    evidenceList.innerHTML = `<div class="evidence-item muted">No evidence extracted.</div>`;
    return;
  }

  evidenceList.innerHTML = evidence
    .map((item) => {
      const sourceNumber = sourceIndex.get(item.source_id) || "?";
      return `
        <article class="evidence-item">
          <strong>[S${sourceNumber}]</strong>
          ${escapeHtml(item.quote || "")}
        </article>
      `;
    })
    .join("");
}

function renderClaims(claims) {
  if (!claims.length) {
    claimList.innerHTML = `<div class="claim-item muted">No claims extracted.</div>`;
    return;
  }

  claimList.innerHTML = claims
    .map((claim) => {
      const evidenceIds = (claim.evidence_ids || []).map(escapeHtml).join(", ");
      return `
        <article class="claim-item">
          <h3>${escapeHtml(claim.topic || "Claim")}</h3>
          <p>${escapeHtml(claim.text || "")}</p>
          <div class="meta-row">
            <span class="badge">${escapeHtml(String(Math.round((claim.confidence || 0) * 100)))}%</span>
            <span class="badge">${evidenceIds || "no evidence"}</span>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderRag(chunks, sources) {
  const sourceIndex = new Map(sources.map((source, index) => [source.id, index + 1]));
  if (!chunks.length) {
    ragList.innerHTML = `<div class="evidence-item muted">No RAG chunks retrieved.</div>`;
    return;
  }

  ragList.innerHTML = chunks
    .map((chunk) => {
      const sourceNumber = sourceIndex.get(chunk.source_id) || "?";
      return `
        <article class="evidence-item">
          <strong>#${escapeHtml(chunk.rank)} [S${sourceNumber}] score=${escapeHtml(chunk.score)}</strong>
          ${escapeHtml(chunk.text || "")}
        </article>
      `;
    })
    .join("");
}

function renderTrace(savedRun, metadata, sources) {
  const sourceLines = (sources || []).map((source, index) => {
    const url = source.url || "";
    return `source_${index + 1}: ${url}`;
  });
  const lines = [
    `requested_search_mode: ${metadata.requested_search_mode || "unknown"}`,
    `actual_search_mode: ${metadata.actual_search_mode || "unknown"}`,
    `search_failure_reason: ${metadata.search_failure_reason || "none"}`,
    `requested_llm_mode: ${metadata.requested_llm_mode || "unknown"}`,
    `actual_llm_mode: ${metadata.actual_llm_mode || "unknown"}`,
    `llm_provider: ${metadata.llm_provider || "unknown"}`,
    `llm_model: ${metadata.llm_model || "unknown"}`,
    `llm_retry_count: ${metadata.llm_retry_count || "0"}`,
    `llm_attempted_models: ${metadata.llm_attempted_models || "none"}`,
    `llm_failure_reason: ${metadata.llm_failure_reason || "none"}`,
    `requested_embedding_mode: ${metadata.requested_embedding_mode || "unknown"}`,
    `actual_embedding_provider: ${metadata.actual_embedding_provider || "unknown"}`,
    `embedding_failure_reason: ${metadata.embedding_failure_reason || "none"}`,
    `rag_enabled: ${metadata.rag_enabled || "unknown"}`,
    `retrieved_chunks: ${metadata.retrieved_chunks || "0"}`,
    `vector_store_path: ${metadata.vector_store_path || "unknown"}`,
    `source_count: ${(sources || []).length}`,
  ];
  lines.push(...sourceLines);

  if (savedRun) {
    lines.push(`run_id: ${savedRun.run_id}`);
    lines.push(`report_path: ${savedRun.report_path}`);
    lines.push(`trace_path: ${savedRun.trace_path}`);
  } else {
    lines.push("saved_run: disabled");
  }

  traceBox.textContent = lines.join("\n");
}

function renderMarkdown(markdown) {
  const lines = markdown.split(/\r?\n/);
  const html = [];
  let listOpen = false;
  let tableRows = [];

  const closeList = () => {
    if (listOpen) {
      html.push("</ul>");
      listOpen = false;
    }
  };

  const flushTable = () => {
    if (!tableRows.length) {
      return;
    }
    html.push(renderTable(tableRows));
    tableRows = [];
  };

  for (const line of lines) {
    if (line.trim().startsWith("|")) {
      closeList();
      tableRows.push(line);
      continue;
    }

    flushTable();
    const trimmed = line.trim();
    if (!trimmed) {
      closeList();
      continue;
    }

    if (trimmed.startsWith("# ")) {
      closeList();
      html.push(`<h1>${inlineMarkdown(trimmed.slice(2))}</h1>`);
    } else if (trimmed.startsWith("## ")) {
      closeList();
      html.push(`<h2>${inlineMarkdown(trimmed.slice(3))}</h2>`);
    } else if (trimmed.startsWith("### ")) {
      closeList();
      html.push(`<h3>${inlineMarkdown(trimmed.slice(4))}</h3>`);
    } else if (trimmed.startsWith("> ")) {
      closeList();
      html.push(`<blockquote>${inlineMarkdown(trimmed.slice(2))}</blockquote>`);
    } else if (trimmed.startsWith("- ")) {
      if (!listOpen) {
        html.push("<ul>");
        listOpen = true;
      }
      html.push(`<li>${inlineMarkdown(trimmed.slice(2))}</li>`);
    } else {
      closeList();
      html.push(`<p>${inlineMarkdown(trimmed)}</p>`);
    }
  }

  closeList();
  flushTable();
  return html.join("");
}

function renderTable(rows) {
  const cleanRows = rows
    .filter((row) => !/^\|\s*-+/.test(row))
    .map((row) => row.split("|").slice(1, -1).map((cell) => inlineMarkdown(cell.trim())));

  if (!cleanRows.length) {
    return "";
  }

  const [head, ...body] = cleanRows;
  const headHtml = `<thead><tr>${head.map((cell) => `<th>${cell}</th>`).join("")}</tr></thead>`;
  const bodyHtml = `<tbody>${body
    .map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`)
    .join("")}</tbody>`;
  return `<table>${headHtml}${bodyHtml}</table>`;
}

function inlineMarkdown(value) {
  return escapeHtml(value)
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/\[(S\d+)\]/g, '<strong>[$1]</strong>');
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
