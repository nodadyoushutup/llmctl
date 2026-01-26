const chat = document.getElementById("chat");
const form = document.getElementById("composer-form");
const input = document.getElementById("message-input");
const statusEl = document.getElementById("status");
const clearBtn = document.getElementById("clear-btn");
const contextMeter = document.getElementById("context-meter");
const sourceKind = document.getElementById("source-kind");
const sourceIndexButtons = document.querySelectorAll(".source-index-btn");
const githubRepoSelect = document.getElementById("github-repo-select");
const githubRepoStatus = document.getElementById("github-repo-status");
const chromaTestBtn = document.getElementById("chroma-test-btn");
const chromaTestStatus = document.getElementById("chroma-test-status");
const chromaHostInput = document.querySelector('input[name="chroma_host"]');
const chromaPortInput = document.querySelector('input[name="chroma_port"]');

const MAX_INPUT_LINES = 3;
const CHARS_PER_TOKEN = 4;
const DEFAULT_CONTEXT_BUDGET_TOKENS = 8000;

let history = [];

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

function formatSourceStatus(state) {
  if (!state) {
    return "Not indexed";
  }
  if (state.running) {
    return "Indexing...";
  }
  if (state.last_error) {
    return "Error";
  }
  if (state.last_indexed_at) {
    return `Indexed ${state.last_indexed_at}`;
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

async function startSourceIndex(sourceId, buttonEl) {
  if (!sourceId) {
    return;
  }
  if (buttonEl) {
    buttonEl.disabled = true;
  }
  updateSourceStatus(sourceId, "Indexing...");
  try {
    const response = await fetch(`/api/sources/${sourceId}/index`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reset: false }),
    });
    const data = await response.json();
    updateSourceStatus(sourceId, formatSourceStatus(data));
    if (!response.ok && !data.running) {
      if (buttonEl) {
        buttonEl.disabled = false;
      }
      return;
    }
    const poll = async () => {
      const status = await fetchSourceStatus(sourceId);
      if (status) {
        updateSourceStatus(sourceId, formatSourceStatus(status));
        if (!status.running) {
          clearInterval(interval);
          if (buttonEl) {
            buttonEl.disabled = false;
          }
        }
      }
    };
    const interval = setInterval(poll, 2000);
    await poll();
  } catch (err) {
    console.error(err);
    updateSourceStatus(sourceId, "Index failed");
    if (buttonEl) {
      buttonEl.disabled = false;
    }
  }
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

function addMessage(role, content, sources, isPending) {
  if (!chat) {
    return null;
  }
  const wrapper = document.createElement("div");
  wrapper.className = `message ${role}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = content;
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
    bubble.textContent = content;
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

async function sendMessage(text, historySnapshot) {
  const payload = {
    message: text,
    history: historySnapshot || [],
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
    updateMessage(pendingEl, reply || "(no response)", data.sources || []);
    history.push({ role: "assistant", content: reply });
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
    const historySnapshot = history.slice();
    history.push({ role: "user", content: text });
    updateContextMeter();
    await sendMessage(text, historySnapshot);
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

if (clearBtn && chat && input) {
  clearBtn.addEventListener("click", () => {
    history = [];
    chat.innerHTML = "";
    setStatus("Cleared.");
    input.focus();
    resizeComposerInput();
    updateContextMeter();
  });
}

sourceIndexButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const sourceId = button.dataset.sourceId;
    startSourceIndex(sourceId, button);
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
      setChromaTestStatus(
        `Connected to ${data.host}:${data.port}${detail}.`,
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
    succeeded: "status-success",
    failed: "status-failed",
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
    return status === "queued" || status === "running";
  });
  if (hasActive) {
    poll();
  }
}

function updateSourceFields() {
  if (!sourceKind) {
    return;
  }
  const isGithub = sourceKind.value === "github";
  document.querySelectorAll(".source-field-local").forEach((field) => {
    field.style.display = isGithub ? "none" : "flex";
  });
  document.querySelectorAll(".source-field-github").forEach((field) => {
    field.style.display = isGithub ? "flex" : "none";
  });
  const localInput = document.querySelector('input[name="source_local_path"]');
  const repoInput = document.querySelector('input[name="source_git_repo"]');
  if (localInput) {
    localInput.required = !isGithub;
  }
  if (repoInput) {
    repoInput.required = isGithub;
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
    githubRepoSelect.appendChild(placeholder);
    data.repos.forEach((repo) => {
      const option = document.createElement("option");
      option.value = repo;
      option.textContent = repo;
      githubRepoSelect.appendChild(option);
    });
    githubReposLoaded = true;
    githubRepoStatus.textContent = data.repos.length
      ? `${data.repos.length} repos loaded.`
      : "No repositories found.";
  } catch (err) {
    console.error(err);
    githubRepoStatus.textContent = err.message;
  }
}
