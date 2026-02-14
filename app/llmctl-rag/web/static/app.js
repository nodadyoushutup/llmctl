const chat = document.getElementById("chat");
const form = document.getElementById("composer-form");
const input = document.getElementById("message-input");
const statusEl = document.getElementById("status");
const clearBtn = document.getElementById("clear-btn");
const contextMeter = document.getElementById("context-meter");
const verbositySelect = document.getElementById("verbosity-select");
const sourceKind = document.getElementById("source-kind");
const sourceFreshButtons = document.querySelectorAll(".source-index-btn");
const sourceDeltaButtons = document.querySelectorAll(".source-delta-btn");
const sourceResumeButtons = document.querySelectorAll(".source-resume-btn");
const sourcePauseButtons = document.querySelectorAll(".source-pause-btn");
const githubRepoSelect = document.getElementById("github-repo-select");
const githubRepoStatus = document.getElementById("github-repo-status");
const driveFolderInput = document.getElementById("drive-folder-id");
const driveFolderVerifyBtn = document.getElementById("drive-folder-verify-btn");
const driveFolderStatus = document.getElementById("drive-folder-status");
const googleDriveServiceAccountInput = document.querySelector(
  'textarea[name="google_drive_service_account_json"]'
);
const chromaTestBtn = document.getElementById("chroma-test-btn");
const chromaTestStatus = document.getElementById("chroma-test-status");
const chromaHostInput = document.querySelector('input[name="chroma_host"]');
const chromaPortInput = document.querySelector('input[name="chroma_port"]');

const MAX_INPUT_LINES = 3;
const CHARS_PER_TOKEN = 4;
const DEFAULT_CONTEXT_BUDGET_TOKENS = 8000;
const CHAT_HISTORY_STORAGE_KEY = "llmctl-rag:chat-history:v1";
const CHAT_VERBOSITY_STORAGE_KEY = "llmctl-rag:chat-verbosity:v1";
const SUPPORTED_VERBOSITY = new Set(["low", "medium", "high"]);
const ALLOWED_MARKDOWN_TAGS = new Set([
  "p",
  "br",
  "strong",
  "em",
  "b",
  "i",
  "code",
  "pre",
  "ul",
  "ol",
  "li",
  "blockquote",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "hr",
  "table",
  "thead",
  "tbody",
  "tr",
  "th",
  "td",
  "a",
]);
const ALLOWED_LINK_PROTOCOLS = new Set(["http:", "https:", "mailto:", "tel:"]);

let history = [];

if (window.marked && typeof window.marked.setOptions === "function") {
  window.marked.setOptions({
    gfm: true,
    breaks: true,
  });
}

function sanitizeHistoryItem(item) {
  if (!item || typeof item !== "object") {
    return null;
  }
  const role = item.role;
  const content = typeof item.content === "string" ? item.content.trim() : "";
  if ((role !== "user" && role !== "assistant") || !content) {
    return null;
  }
  const cleaned = { role, content };
  if (Array.isArray(item.sources) && item.sources.length) {
    cleaned.sources = item.sources
      .map((source) => {
        if (!source || typeof source !== "object") {
          return null;
        }
        return {
          label: typeof source.label === "string" ? source.label : "",
          snippet: typeof source.snippet === "string" ? source.snippet : "",
        };
      })
      .filter(Boolean);
  }
  return cleaned;
}

function sanitizeHistoryItems(items) {
  if (!Array.isArray(items)) {
    return [];
  }
  return items.map(sanitizeHistoryItem).filter(Boolean);
}

function loadPersistedHistory() {
  try {
    const raw = window.localStorage.getItem(CHAT_HISTORY_STORAGE_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw);
    return sanitizeHistoryItems(parsed);
  } catch (err) {
    console.error(err);
    return [];
  }
}

function persistHistory() {
  try {
    if (!history.length) {
      window.localStorage.removeItem(CHAT_HISTORY_STORAGE_KEY);
      return;
    }
    window.localStorage.setItem(CHAT_HISTORY_STORAGE_KEY, JSON.stringify(history));
  } catch (err) {
    console.error(err);
  }
}

function snapshotConversation(items) {
  return items.map((item) => ({ role: item.role, content: item.content }));
}

function normalizeVerbosity(value, fallback = "high") {
  const candidate = String(value || "")
    .trim()
    .toLowerCase();
  if (SUPPORTED_VERBOSITY.has(candidate)) {
    return candidate;
  }
  return SUPPORTED_VERBOSITY.has(fallback) ? fallback : "high";
}

function loadPersistedVerbosity() {
  try {
    return window.localStorage.getItem(CHAT_VERBOSITY_STORAGE_KEY);
  } catch (err) {
    console.error(err);
    return null;
  }
}

function persistVerbosity(value) {
  try {
    const normalized = normalizeVerbosity(value);
    window.localStorage.setItem(CHAT_VERBOSITY_STORAGE_KEY, normalized);
  } catch (err) {
    console.error(err);
  }
}

function hydrateChatFromHistory() {
  if (!chat) {
    return;
  }
  history.forEach((item) => {
    addMessage(item.role, item.content, item.sources || []);
  });
}

function estimateTokens(text) {
  if (!text) {
    return 0;
  }
  const cleaned = text.trim();
  if (!cleaned) {
    return 0;
  }
  return Math.max(1, Math.ceil(cleaned.length / CHARS_PER_TOKEN));
}

function estimateHistoryTokens(historyItems, maxItems) {
  if (!historyItems || !historyItems.length) {
    return 0;
  }
  const slice = maxItems
    ? historyItems.slice(Math.max(historyItems.length - maxItems, 0))
    : historyItems;
  return slice.reduce((sum, item) => sum + estimateTokens(item.content), 0);
}

function updateContextMeter(pendingInput) {
  if (!contextMeter) {
    return;
  }
  const budgetTokens =
    Number.parseInt(contextMeter.dataset.budgetTokens, 10) ||
    DEFAULT_CONTEXT_BUDGET_TOKENS;
  const maxHistory = Number.parseInt(contextMeter.dataset.maxHistory, 10) || 0;
  const historyTokens = estimateHistoryTokens(history, maxHistory);
  const pendingTokens = estimateTokens(pendingInput);
  const totalTokens = historyTokens + pendingTokens;
  const percent = budgetTokens
    ? Math.min(100, Math.round((totalTokens / budgetTokens) * 100))
    : 0;
  const valueEl = contextMeter.querySelector(".context-meter-value");
  const fillEl = contextMeter.querySelector(".context-meter-fill");
  if (valueEl) {
    valueEl.textContent = `${percent}%`;
  }
  if (fillEl) {
    fillEl.style.width = `${percent}%`;
  }
  contextMeter.classList.remove("is-warning", "is-critical");
  if (percent >= 90) {
    contextMeter.classList.add("is-critical");
  } else if (percent >= 70) {
    contextMeter.classList.add("is-warning");
  }
  const label =
    budgetTokens > 0
      ? `${totalTokens} / ${budgetTokens} tokens (approx.)`
      : `${totalTokens} tokens (approx.)`;
  contextMeter.setAttribute("title", label);
}

function resizeComposerInput() {
  if (!input) {
    return;
  }
  const styles = window.getComputedStyle(input);
  const lineHeight = Number.parseFloat(styles.lineHeight) || 20;
  const padding =
    Number.parseFloat(styles.paddingTop) +
    Number.parseFloat(styles.paddingBottom);
  const maxHeight = Math.ceil(lineHeight * MAX_INPUT_LINES + padding);
  input.style.height = "auto";
  const nextHeight = Math.min(input.scrollHeight, maxHeight);
  input.style.height = `${nextHeight}px`;
  input.style.overflowY = input.scrollHeight > maxHeight ? "auto" : "hidden";
}

function setStatus(text) {
  if (!statusEl) {
    return;
  }
  statusEl.textContent = text;
}

function setChromaTestStatus(text, variant) {
  if (!chromaTestStatus) {
    return;
  }
  chromaTestStatus.textContent = text;
  chromaTestStatus.classList.remove("success", "error");
  if (variant) {
    chromaTestStatus.classList.add(variant);
  }
  chromaTestStatus.hidden = false;
}

function formatSourceTimestamp(value) {
  if (!value) {
    return "-";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return String(value);
  }
  return parsed.toLocaleString();
}

function formatSourceStatus(state) {
  if (!state) {
    return "Not indexed";
  }
  const progressSummary =
    state.progress && typeof state.progress.summary === "string"
      ? state.progress.summary.trim()
      : "";
  const compactSummary =
    progressSummary.length > 120
      ? `${progressSummary.slice(0, 117).trimEnd()}...`
      : progressSummary;
  if (state.status === "paused") {
    return compactSummary ? `Paused (${compactSummary})` : "Paused";
  }
  if (state.status === "pausing") {
    return "Pausing...";
  }
  if (state.running) {
    return compactSummary ? `Indexing (${compactSummary})` : "Indexing...";
  }
  if (state.last_error) {
    return "Error";
  }
  if (state.last_indexed_at) {
    return `Indexed ${formatSourceTimestamp(state.last_indexed_at)}`;
  }
  return "Not indexed";
}

async function fetchSourceStatus(sourceId) {
  try {
    const response = await fetch(`/api/sources/${sourceId}/index`);
    if (!response.ok) {
      return null;
    }
    return await response.json();
  } catch (err) {
    console.error(err);
    return null;
  }
}

function updateSourceStatus(sourceId, text) {
  const statusEl = document.querySelector(
    `.source-status[data-source-id="${sourceId}"]`
  );
  if (statusEl) {
    statusEl.textContent = text;
  }
}

function updateSourceTiming(sourceId, state) {
  const lastIndexedEl = document.querySelector(
    `.source-last-indexed[data-source-id="${sourceId}"]`
  );
  if (lastIndexedEl) {
    lastIndexedEl.textContent = formatSourceTimestamp(
      state && state.last_indexed_at
    );
  }
  const nextIndexEl = document.querySelector(
    `.source-next-index[data-source-id="${sourceId}"]`
  );
  if (nextIndexEl) {
    const hasSchedule = Boolean(
      state &&
        state.schedule_value &&
        typeof state.schedule_unit === "string" &&
        state.schedule_unit
    );
    if (!hasSchedule) {
      nextIndexEl.textContent = "Not scheduled";
    } else {
      nextIndexEl.textContent = formatSourceTimestamp(state.next_index_at);
    }
  }
}

function setSourceActionDisabled(sourceId, disabled) {
  if (!sourceId) {
    return;
  }
  const selector = `.source-action-btn[data-source-id="${sourceId}"]`;
  document.querySelectorAll(selector).forEach((button) => {
    button.disabled = disabled;
  });
}

function applySourceActionState(sourceId, state) {
  updateSourceStatus(sourceId, formatSourceStatus(state));
  updateSourceTiming(sourceId, state);
  const running = Boolean(state && state.running);
  const status = state && typeof state.status === "string" ? state.status : "";
  const canResume = Boolean(state && state.can_resume);
  const canPause = running && status !== "pausing";
  const freshBtn = document.querySelector(
    `.source-index-btn[data-source-id="${sourceId}"]`
  );
  const deltaBtn = document.querySelector(
    `.source-delta-btn[data-source-id="${sourceId}"]`
  );
  const resumeBtn = document.querySelector(
    `.source-resume-btn[data-source-id="${sourceId}"]`
  );
  const pauseBtn = document.querySelector(
    `.source-pause-btn[data-source-id="${sourceId}"]`
  );
  if (freshBtn) {
    freshBtn.disabled = running || canResume;
  }
  if (deltaBtn) {
    deltaBtn.disabled = running || canResume;
  }
  if (resumeBtn) {
    resumeBtn.disabled = running || !canResume;
  }
  if (pauseBtn) {
    pauseBtn.disabled = !canPause;
  }
}

async function runSourceAction(sourceId, endpoint, pendingText, payload) {
  if (!sourceId) {
    return;
  }
  setSourceActionDisabled(sourceId, true);
  if (pendingText) {
    updateSourceStatus(sourceId, pendingText);
  }
  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    });
    const data = await response.json();
    applySourceActionState(sourceId, data);
    if (!response.ok && !data.running && data.status !== "pausing") {
      return;
    }
    const poll = async () => {
      const status = await fetchSourceStatus(sourceId);
      if (status) {
        applySourceActionState(sourceId, status);
        if (!status.running && status.status !== "pausing") {
          clearInterval(interval);
        }
      }
    };
    const interval = setInterval(poll, 2000);
    await poll();
  } catch (err) {
    console.error(err);
    updateSourceStatus(sourceId, "Action failed");
  } finally {
    const status = await fetchSourceStatus(sourceId);
    if (status) {
      applySourceActionState(sourceId, status);
    } else {
      setSourceActionDisabled(sourceId, false);
    }
  }
}

async function startSourceIndex(sourceId) {
  return runSourceAction(sourceId, `/api/sources/${sourceId}/index`, "Indexing...", {
    reset: false,
    mode: "fresh",
  });
}

async function startSourceDelta(sourceId) {
  return runSourceAction(
    sourceId,
    `/api/sources/${sourceId}/index`,
    "Delta indexing...",
    {
      reset: false,
      mode: "delta",
    }
  );
}

async function startSourceResume(sourceId) {
  return runSourceAction(
    sourceId,
    `/api/sources/${sourceId}/resume`,
    "Resuming...",
    {}
  );
}

async function startSourcePause(sourceId) {
  return runSourceAction(sourceId, `/api/sources/${sourceId}/pause`, "Pausing...", {});
}

function buildSourcesSection(sources) {
  if (!sources || !sources.length) {
    return null;
  }
  const wrapper = document.createElement("div");
  wrapper.className = "sources-wrapper";

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "sources-toggle";
  const label = document.createElement("span");
  label.className = "sources-label";
  label.textContent = `Sources (${sources.length})`;
  const caret = document.createElement("span");
  caret.className = "sources-caret";
  caret.textContent = "▾";
  toggle.append(label, caret);

  const sourcesEl = document.createElement("div");
  sourcesEl.className = "sources";
  const listId = `sources-${Math.random().toString(36).slice(2, 10)}`;
  sourcesEl.id = listId;
  toggle.setAttribute("aria-controls", listId);
  toggle.setAttribute("aria-expanded", "false");

  sources.forEach((source) => {
    const item = document.createElement("div");
    item.className = "source";
    const title = document.createElement("strong");
    title.textContent = source.label || "source";
    const snippet = document.createElement("div");
    snippet.textContent = source.snippet || "";
    item.appendChild(title);
    item.appendChild(snippet);
    sourcesEl.appendChild(item);
  });

  toggle.addEventListener("click", () => {
    const isOpen = wrapper.classList.toggle("is-open");
    toggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
    caret.textContent = isOpen ? "▴" : "▾";
  });

  wrapper.appendChild(toggle);
  wrapper.appendChild(sourcesEl);
  return wrapper;
}

function normalizeSafeHref(rawHref) {
  if (!rawHref || typeof rawHref !== "string") {
    return null;
  }
  const trimmed = rawHref.trim();
  if (!trimmed) {
    return null;
  }
  try {
    const url = new URL(trimmed, window.location.origin);
    if (ALLOWED_LINK_PROTOCOLS.has(url.protocol)) {
      return url.href;
    }
  } catch (err) {
    console.warn("Skipping invalid markdown link href", err);
  }
  return null;
}

function sanitizeMarkdownHtml(html) {
  const template = document.createElement("template");
  template.innerHTML = html;
  const container = document.createElement("div");

  const appendNode = (node, target) => {
    if (node.nodeType === Node.TEXT_NODE) {
      target.appendChild(document.createTextNode(node.textContent || ""));
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) {
      return;
    }
    const tagName = String(node.nodeName || "").toLowerCase();
    if (!ALLOWED_MARKDOWN_TAGS.has(tagName)) {
      node.childNodes.forEach((child) => appendNode(child, target));
      return;
    }

    const clean = document.createElement(tagName);
    if (tagName === "a") {
      const safeHref = normalizeSafeHref(node.getAttribute("href"));
      if (safeHref) {
        clean.setAttribute("href", safeHref);
        clean.setAttribute("target", "_blank");
        clean.setAttribute("rel", "noopener noreferrer nofollow");
      }
      const title = node.getAttribute("title");
      if (title) {
        clean.setAttribute("title", title);
      }
    }
    if (tagName === "th" || tagName === "td") {
      const colspan = node.getAttribute("colspan");
      const rowspan = node.getAttribute("rowspan");
      if (colspan && /^\d+$/.test(colspan)) {
        clean.setAttribute("colspan", colspan);
      }
      if (rowspan && /^\d+$/.test(rowspan)) {
        clean.setAttribute("rowspan", rowspan);
      }
    }

    node.childNodes.forEach((child) => appendNode(child, clean));
    target.appendChild(clean);
  };

  template.content.childNodes.forEach((node) => appendNode(node, container));
  return container.innerHTML;
}

function setBubbleContent(bubble, role, content) {
  const text = typeof content === "string" ? content : "";
  if (
    role !== "assistant" ||
    !window.marked ||
    typeof window.marked.parse !== "function"
  ) {
    bubble.textContent = text;
    bubble.classList.remove("markdown-body");
    return;
  }

  const rendered = window.marked.parse(text || "");
  const safeHtml = sanitizeMarkdownHtml(String(rendered || ""));
  if (!safeHtml.trim()) {
    bubble.textContent = text;
    bubble.classList.remove("markdown-body");
    return;
  }
  bubble.innerHTML = safeHtml;
  bubble.classList.add("markdown-body");
}

function addMessage(role, content, sources, isPending) {
  if (!chat) {
    return null;
  }
  const wrapper = document.createElement("div");
  wrapper.className = `message ${role}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  setBubbleContent(bubble, role, content);
  if (isPending) {
    bubble.dataset.pending = "true";
  }

  wrapper.appendChild(bubble);

  const sourcesSection = buildSourcesSection(sources);
  if (sourcesSection) {
    wrapper.appendChild(sourcesSection);
  }

  chat.appendChild(wrapper);
  chat.scrollTop = chat.scrollHeight;
  return wrapper;
}

function updateMessage(messageEl, content, sources) {
  if (!messageEl) {
    return;
  }
  const bubble = messageEl.querySelector(".bubble");
  if (bubble) {
    const role = messageEl.classList.contains("assistant") ? "assistant" : "user";
    setBubbleContent(bubble, role, content);
    delete bubble.dataset.pending;
  }

  const existingSources = messageEl.querySelector(".sources-wrapper");
  if (existingSources) {
    existingSources.remove();
  }

  const sourcesSection = buildSourcesSection(sources);
  if (sourcesSection) {
    messageEl.appendChild(sourcesSection);
  }

  chat.scrollTop = chat.scrollHeight;
}

async function sendMessage(text, historySnapshot, verbosity) {
  const payload = {
    message: text,
    history: historySnapshot || [],
    verbosity: normalizeVerbosity(verbosity),
  };

  const pendingEl = addMessage("assistant", "Thinking...", null, true);
  setStatus("Thinking...");

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Request failed");
    }

    const reply = data.reply || "";
    const sources = Array.isArray(data.sources) ? data.sources : [];
    updateMessage(pendingEl, reply || "(no response)", sources);
    history.push({ role: "assistant", content: reply, sources });
    persistHistory();
    updateContextMeter();
    if (data.elapsed_ms !== undefined) {
      setStatus(`Answered in ${data.elapsed_ms} ms`);
    } else {
      setStatus("Answered.");
    }
  } catch (err) {
    updateMessage(pendingEl, `Error: ${err.message}`, []);
    setStatus("Error. Check console for details.");
    console.error(err);
  }
}

if (form && input) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text) {
      return;
    }

    input.value = "";
    resizeComposerInput();
    addMessage("user", text, []);
    const historySnapshot = snapshotConversation(history);
    history.push({ role: "user", content: text });
    persistHistory();
    updateContextMeter();
    const verbosity = verbositySelect
      ? normalizeVerbosity(verbositySelect.value)
      : "high";
    await sendMessage(text, historySnapshot, verbosity);
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  input.addEventListener("input", () => {
    resizeComposerInput();
    updateContextMeter(input.value);
  });

  resizeComposerInput();
}

if (verbositySelect) {
  const initialVerbosity = normalizeVerbosity(
    loadPersistedVerbosity(),
    normalizeVerbosity(verbositySelect.value)
  );
  verbositySelect.value = initialVerbosity;
  persistVerbosity(initialVerbosity);
  verbositySelect.addEventListener("change", () => {
    const nextVerbosity = normalizeVerbosity(verbositySelect.value);
    verbositySelect.value = nextVerbosity;
    persistVerbosity(nextVerbosity);
  });
}

if (clearBtn && chat && input) {
  clearBtn.addEventListener("click", () => {
    history = [];
    persistHistory();
    chat.innerHTML = "";
    setStatus("Cleared.");
    input.focus();
    resizeComposerInput();
    updateContextMeter();
  });
}

sourceFreshButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const sourceId = button.dataset.sourceId;
    startSourceIndex(sourceId);
  });
});

sourceDeltaButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const sourceId = button.dataset.sourceId;
    startSourceDelta(sourceId);
  });
});

sourceResumeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const sourceId = button.dataset.sourceId;
    startSourceResume(sourceId);
  });
});

sourcePauseButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const sourceId = button.dataset.sourceId;
    startSourcePause(sourceId);
  });
});

if (chromaTestBtn) {
  chromaTestBtn.addEventListener("click", async () => {
    const host = chromaHostInput ? chromaHostInput.value.trim() : "";
    const port = chromaPortInput ? chromaPortInput.value.trim() : "";
    chromaTestBtn.disabled = true;
    setChromaTestStatus("Testing Chroma connection...");
    try {
      const response = await fetch("/api/chroma/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ host, port }),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) {
        throw new Error(data.error || "Connection failed");
      }
      const detail =
        typeof data.collections_count === "number"
          ? ` (${data.collections_count} collections)`
          : "";
      if (chromaHostInput && data.host) {
        chromaHostInput.value = data.host;
      }
      if (chromaPortInput && data.port) {
        chromaPortInput.value = String(data.port);
      }
      const hint = data.hint ? ` ${data.hint}` : "";
      setChromaTestStatus(
        `Connected to ${data.host}:${data.port}${detail}.${hint}`,
        "success"
      );
    } catch (err) {
      console.error(err);
      setChromaTestStatus(`Connection failed: ${err.message}`, "error");
    } finally {
      chromaTestBtn.disabled = false;
    }
  });
}

history = loadPersistedHistory();
hydrateChatFromHistory();

setStatus("Ready.");
updateContextMeter();

(() => {
  const main = document.querySelector(".main");
  const topbar = document.querySelector(".topbar");
  if (!main || !topbar) {
    return;
  }
  const setTopbarOffset = () => {
    main.style.setProperty("--topbar-height", `${topbar.offsetHeight}px`);
  };
  setTopbarOffset();
  window.addEventListener("resize", setTopbarOffset);
})();

const viewButtons = document.querySelectorAll(".nav-btn[data-view]");
const views = {
  chat: document.getElementById("chat-view"),
  settings: document.getElementById("settings-view"),
};

function setView(nextView) {
  Object.entries(views).forEach(([name, section]) => {
    if (!section) {
      return;
    }
    section.classList.toggle("is-active", name === nextView);
  });
  viewButtons.forEach((button) => {
    button.classList.toggle("is-active", button.dataset.view === nextView);
  });
  const url = new URL(window.location.href);
  url.searchParams.set("view", nextView);
  window.history.replaceState({}, "", url);
}

viewButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const nextView = button.dataset.view;
    if (nextView) {
      setView(nextView);
    }
  });
});

const rowLinks = document.querySelectorAll(".table-row-link[data-href]");
rowLinks.forEach((row) => {
  row.addEventListener("click", (event) => {
    if (
      event.target.closest(
        "a, button, input, select, textarea, label, summary, details"
      )
    ) {
      return;
    }
    const href = row.dataset.href;
    if (href) {
      window.location.href = href;
    }
  });
});

const confirmForms = document.querySelectorAll("form[data-confirm]");
confirmForms.forEach((formEl) => {
  formEl.addEventListener("submit", (event) => {
    const message = formEl.dataset.confirm || "Are you sure?";
    if (!window.confirm(message)) {
      event.preventDefault();
    }
  });
});

const taskRows = document.querySelectorAll("tr[data-task-id][data-task-status]");
if (taskRows.length) {
  const rowsById = new Map();
  taskRows.forEach((row) => {
    const id = Number.parseInt(row.dataset.taskId || "", 10);
    if (Number.isNaN(id)) {
      return;
    }
    rowsById.set(id, row);
  });

  const statusClasses = {
    running: "status-running",
    queued: "status-queued",
    pausing: "status-warning",
    paused: "status-warning",
    succeeded: "status-success",
    failed: "status-failed",
    cancelled: "status-warning",
  };

  const updateText = (el, value, fallback = "-") => {
    if (!el) {
      return;
    }
    if (value === null || value === undefined || value === "") {
      el.textContent = fallback;
    } else {
      el.textContent = value;
    }
  };

  const updateStatus = (row, status) => {
    if (!row) {
      return;
    }
    const statusEl = row.querySelector(".status-pill");
    if (!statusEl) {
      return;
    }
    const className = statusClasses[status] || "";
    statusEl.className = `status-pill ${className}`.trim();
    statusEl.textContent = status || "-";
    row.dataset.taskStatus = status || "";
  };

  const updateRow = (task) => {
    const row = rowsById.get(task.id);
    if (!row) {
      return;
    }
    updateStatus(row, task.status);
    updateText(row.querySelector("[data-task-started]"), task.started_at);
    updateText(row.querySelector("[data-task-finished]"), task.finished_at);
    const pauseForm = row.querySelector("[data-task-pause-form]");
    if (pauseForm) {
      pauseForm.style.display =
        task.status === "queued" || task.status === "running" ? "" : "none";
    }
    const resumeForm = row.querySelector("[data-task-resume-form]");
    if (resumeForm) {
      resumeForm.style.display = task.status === "paused" ? "" : "none";
    }
    const cancelForm = row.querySelector("[data-task-cancel-form]");
    if (cancelForm) {
      cancelForm.style.display =
        task.status === "queued" ||
        task.status === "running" ||
        task.status === "pausing"
          ? ""
          : "none";
    }
  };

  let pollTimer = null;

  const stopPolling = () => {
    if (pollTimer) {
      window.clearTimeout(pollTimer);
      pollTimer = null;
    }
  };

  const poll = async () => {
    try {
      const ids = Array.from(rowsById.keys());
      if (!ids.length) {
        stopPolling();
        return;
      }
      const params = new URLSearchParams({ ids: ids.join(",") });
      const response = await fetch(`/api/tasks/status?${params.toString()}`, {
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        throw new Error("Request failed");
      }
      const data = await response.json();
      const tasks = Array.isArray(data.tasks) ? data.tasks : [];
      let anyRunning = false;
      tasks.forEach((task) => {
        updateRow(task);
        if (task.running) {
          anyRunning = true;
        }
      });
      if (!anyRunning) {
        stopPolling();
        return;
      }
    } catch (err) {
      console.error(err);
    }
    pollTimer = window.setTimeout(poll, 2000);
  };

  const hasActive = Array.from(rowsById.values()).some((row) => {
    const status = (row.dataset.taskStatus || "").toLowerCase();
    return status === "queued" || status === "running" || status === "pausing";
  });
  if (hasActive) {
    poll();
  }
}

function updateSourceFields() {
  if (!sourceKind) {
    return;
  }
  const sourceType = sourceKind.value;
  const isGithub = sourceType === "github";
  const isGoogleDrive = sourceType === "google_drive";
  document.querySelectorAll(".source-field-local").forEach((field) => {
    field.style.display = sourceType === "local" ? "flex" : "none";
  });
  document.querySelectorAll(".source-field-github").forEach((field) => {
    field.style.display = isGithub ? "flex" : "none";
  });
  document.querySelectorAll(".source-field-google-drive").forEach((field) => {
    field.style.display = isGoogleDrive ? "flex" : "none";
  });
  const localInput = document.querySelector('input[name="source_local_path"]');
  const repoInput = document.querySelector('[name="source_git_repo"]');
  const driveInput = document.querySelector('input[name="source_drive_folder_id"]');
  if (localInput) {
    localInput.required = sourceType === "local";
  }
  if (repoInput) {
    repoInput.required = isGithub;
  }
  if (driveInput) {
    driveInput.required = isGoogleDrive;
  }
  if (isGithub) {
    loadGithubRepos();
  }
}

if (sourceKind) {
  sourceKind.addEventListener("change", updateSourceFields);
  updateSourceFields();
}

let githubReposLoaded = false;

async function loadGithubRepos() {
  if (!githubRepoSelect || !githubRepoStatus || githubReposLoaded) {
    return;
  }
  const selectedRepo = (
    githubRepoSelect.dataset.selectedValue || githubRepoSelect.value || ""
  ).trim();
  githubRepoStatus.textContent = "Loading repositories...";
  try {
    const response = await fetch("/api/github/repos");
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Failed to load repositories");
    }
    githubRepoSelect.innerHTML = "";
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "Select a repo";
    placeholder.selected = !selectedRepo;
    githubRepoSelect.appendChild(placeholder);
    let foundSelectedRepo = false;
    data.repos.forEach((repo) => {
      const option = document.createElement("option");
      option.value = repo;
      option.textContent = repo;
      if (selectedRepo && repo === selectedRepo) {
        option.selected = true;
        foundSelectedRepo = true;
      }
      githubRepoSelect.appendChild(option);
    });
    if (selectedRepo && !foundSelectedRepo) {
      const selectedOption = document.createElement("option");
      selectedOption.value = selectedRepo;
      selectedOption.textContent = `${selectedRepo} (current)`;
      selectedOption.selected = true;
      githubRepoSelect.appendChild(selectedOption);
    }
    githubReposLoaded = true;
    githubRepoStatus.textContent = data.repos.length
      ? `${data.repos.length} repos loaded.`
      : "No repositories found.";
  } catch (err) {
    console.error(err);
    githubRepoStatus.textContent = err.message;
  }
}

function setDriveFolderStatus(text, variant) {
  if (!driveFolderStatus) {
    return;
  }
  driveFolderStatus.textContent = text;
  driveFolderStatus.classList.remove("success", "error");
  if (variant) {
    driveFolderStatus.classList.add(variant);
  }
}

async function verifyDriveFolder() {
  if (!driveFolderInput || !driveFolderVerifyBtn) {
    return;
  }
  const folderId = driveFolderInput.value.trim();
  if (!folderId) {
    setDriveFolderStatus("Enter a Google Drive folder ID first.", "error");
    return;
  }
  const serviceAccountJson = googleDriveServiceAccountInput
    ? googleDriveServiceAccountInput.value.trim()
    : "";
  driveFolderVerifyBtn.disabled = true;
  setDriveFolderStatus("Verifying Google Drive folder...");
  try {
    const response = await fetch("/api/google-drive/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        folder_id: folderId,
        service_account_json: serviceAccountJson,
      }),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || "Verification failed.");
    }
    const folderName = data.folder_name ? ` (${data.folder_name})` : "";
    setDriveFolderStatus(
      `Verified folder ${data.folder_id}${folderName}.`,
      "success"
    );
  } catch (err) {
    console.error(err);
    setDriveFolderStatus(`Verification failed: ${err.message}`, "error");
  } finally {
    driveFolderVerifyBtn.disabled = false;
  }
}

if (driveFolderVerifyBtn) {
  driveFolderVerifyBtn.addEventListener("click", () => {
    verifyDriveFolder();
  });
}
