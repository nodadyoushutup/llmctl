(function () {
  const INTERACTIVE_SELECTOR =
    "a, button, input, select, textarea, label, summary, details";
  const ACTIVE_JOB_STATUSES = new Set(["queued", "running", "pausing"]);

  function wireRowLinks() {
    const rowLinks = document.querySelectorAll(".table-row-link[data-href]");
    rowLinks.forEach((row) => {
      row.addEventListener("click", (event) => {
        if (event.target.closest(INTERACTIVE_SELECTOR)) {
          return;
        }
        const href = row.dataset.href;
        if (href) {
          window.location.href = href;
        }
      });
    });
  }

  function textOrFallback(value, fallback) {
    if (value === null || value === undefined || String(value).trim() === "") {
      return fallback;
    }
    return String(value);
  }

  function formatTimestamp(value) {
    if (!value) {
      return "-";
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return String(value);
    }
    return date.toLocaleString();
  }

  function statusClass(status) {
    const normalized = String(status || "").trim().toLowerCase();
    if (normalized === "running") {
      return "status-running";
    }
    if (normalized === "queued") {
      return "status-idle";
    }
    if (normalized === "pausing" || normalized === "paused") {
      return "status-warning";
    }
    if (normalized === "succeeded") {
      return "status-success";
    }
    if (normalized === "failed") {
      return "status-failed";
    }
    if (normalized === "cancelled") {
      return "status-warning";
    }
    return "status-idle";
  }

  function wireSourceForm() {
    const kindSelect = document.getElementById("source-kind");
    if (!kindSelect) {
      return;
    }

    const githubRepoSelect = document.getElementById("github-repo-select");
    const githubRepoStatus = document.getElementById("github-repo-status");
    const driveFolderInput = document.getElementById("drive-folder-id");
    const driveVerifyButton = document.getElementById("drive-folder-verify-btn");
    const driveStatus = document.getElementById("drive-folder-status");

    let githubLoaded = false;

    function toggleSourceFields() {
      const kind = String(kindSelect.value || "").trim().toLowerCase();
      const isLocal = kind === "local";
      const isGithub = kind === "github";
      const isDrive = kind === "google_drive";

      document.querySelectorAll(".rag-source-field-local").forEach((el) => {
        el.style.display = isLocal ? "" : "none";
      });
      document.querySelectorAll(".rag-source-field-github").forEach((el) => {
        el.style.display = isGithub ? "" : "none";
      });
      document.querySelectorAll(".rag-source-field-google-drive").forEach((el) => {
        el.style.display = isDrive ? "" : "none";
      });

      const localInput = document.querySelector('input[name="source_local_path"]');
      const githubInput = document.querySelector('select[name="source_git_repo"]');
      const driveInput = document.querySelector('input[name="source_drive_folder_id"]');
      if (localInput) {
        localInput.required = isLocal;
      }
      if (githubInput) {
        githubInput.required = isGithub;
      }
      if (driveInput) {
        driveInput.required = isDrive;
      }

      if (isGithub) {
        loadGithubRepos();
      }
    }

    async function loadGithubRepos() {
      if (!githubRepoSelect || githubLoaded) {
        return;
      }
      const selectedRepo = (
        githubRepoSelect.dataset.selectedValue || githubRepoSelect.value || ""
      ).trim();
      if (githubRepoStatus) {
        githubRepoStatus.textContent = "Loading repositories...";
      }

      try {
        const response = await fetch("/api/rag/github/repos", {
          headers: { Accept: "application/json" },
        });
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.error || "Unable to load repositories.");
        }

        githubRepoSelect.innerHTML = "";
        const placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.textContent = "Select repository";
        placeholder.selected = !selectedRepo;
        githubRepoSelect.appendChild(placeholder);

        let selectedFound = false;
        const repos = Array.isArray(data.repos) ? data.repos : [];
        repos.forEach((repo) => {
          const option = document.createElement("option");
          option.value = repo;
          option.textContent = repo;
          if (selectedRepo && repo === selectedRepo) {
            selectedFound = true;
            option.selected = true;
          }
          githubRepoSelect.appendChild(option);
        });

        if (selectedRepo && !selectedFound) {
          const option = document.createElement("option");
          option.value = selectedRepo;
          option.textContent = `${selectedRepo} (current)`;
          option.selected = true;
          githubRepoSelect.appendChild(option);
        }

        githubLoaded = true;
        if (githubRepoStatus) {
          githubRepoStatus.textContent = repos.length
            ? `${repos.length} repositories loaded.`
            : "No repositories returned for this token.";
        }
      } catch (error) {
        if (githubRepoStatus) {
          githubRepoStatus.textContent = String(error.message || error);
        }
      }
    }

    async function verifyDriveFolder() {
      if (!driveFolderInput || !driveVerifyButton || !driveStatus) {
        return;
      }
      const folderId = String(driveFolderInput.value || "").trim();
      if (!folderId) {
        driveStatus.textContent = "Enter a Google Drive folder ID first.";
        return;
      }

      driveVerifyButton.disabled = true;
      driveStatus.textContent = "Verifying folder access...";
      try {
        const response = await fetch("/api/rag/google-drive/verify", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Accept: "application/json",
          },
          body: JSON.stringify({ folder_id: folderId }),
        });
        const data = await response.json();
        if (!response.ok || !data.ok) {
          throw new Error(data.error || "Google Drive verification failed.");
        }
        const name = data.folder_name ? ` (${data.folder_name})` : "";
        driveStatus.textContent = `Verified${name}.`;
      } catch (error) {
        driveStatus.textContent = String(error.message || error);
      } finally {
        driveVerifyButton.disabled = false;
      }
    }

    kindSelect.addEventListener("change", toggleSourceFields);
    toggleSourceFields();
    if (driveVerifyButton) {
      driveVerifyButton.addEventListener("click", verifyDriveFolder);
    }
  }

  function renderChatMessage(log, role, text, sources) {
    const wrapper = document.createElement("div");
    wrapper.style.marginBottom = "10px";

    const label = document.createElement("div");
    label.className = "muted";
    label.style.fontSize = "12px";
    label.style.marginBottom = "4px";
    label.textContent = role === "user" ? "You" : "Assistant";

    const bubble = document.createElement("pre");
    bubble.style.margin = "0";
    bubble.style.whiteSpace = "pre-wrap";
    bubble.style.wordBreak = "break-word";
    bubble.style.padding = "10px";
    bubble.style.borderRadius = "10px";
    bubble.style.border = "1px solid var(--color-border, #ddd)";
    bubble.style.background = role === "user" ? "var(--panel-bg, #f7f7f7)" : "transparent";
    bubble.textContent = text;

    wrapper.appendChild(label);
    wrapper.appendChild(bubble);

    if (Array.isArray(sources) && sources.length) {
      const sourceTitle = document.createElement("p");
      sourceTitle.className = "muted";
      sourceTitle.style.fontSize = "12px";
      sourceTitle.style.margin = "6px 0 4px";
      sourceTitle.textContent = `Sources (${sources.length})`;
      wrapper.appendChild(sourceTitle);

      const sourceList = document.createElement("ul");
      sourceList.style.margin = "0 0 0 18px";
      sourceList.style.padding = "0";
      sources.forEach((source) => {
        const item = document.createElement("li");
        const labelText = textOrFallback(source.label, "source");
        const snippet = textOrFallback(source.snippet, "");
        item.textContent = snippet ? `${labelText}: ${snippet}` : labelText;
        sourceList.appendChild(item);
      });
      wrapper.appendChild(sourceList);
    }

    log.appendChild(wrapper);
    log.scrollTop = log.scrollHeight;
  }

  function wireChat() {
    const root = document.getElementById("rag-chat-root");
    if (!root) {
      return;
    }

    const form = document.getElementById("rag-chat-form");
    const log = document.getElementById("rag-chat-log");
    const input = document.getElementById("rag-chat-input");
    const status = document.getElementById("rag-chat-status");
    const sendButton = document.getElementById("rag-chat-send-btn");
    const clearButton = document.getElementById("rag-chat-clear-btn");
    const verbosityInput = document.getElementById("rag-chat-verbosity");
    const topKInput = document.getElementById("rag-chat-top-k");
    const historyLimitInput = document.getElementById("rag-chat-history-limit");
    const contextBudgetInput = document.getElementById("rag-chat-context-budget");
    const collectionInputs = document.querySelectorAll(
      ".rag-chat-collection-checkbox, .rag-chat-source-checkbox"
    );

    if (!form || !log || !input || !status || !sendButton) {
      return;
    }

    const historyStorageKey = "llmctl-studio-rag-chat-history-v1";
    let history = [];

    function updateStatus(text) {
      status.textContent = text;
    }

    function selectedCollections() {
      const values = [];
      collectionInputs.forEach((checkbox) => {
        if (checkbox.checked) {
          const value = String(checkbox.value || "").trim();
          if (value && !values.includes(value)) {
            values.push(value);
          }
        }
      });
      return values;
    }

    function historySnapshot() {
      return history.map((item) => ({ role: item.role, content: item.content }));
    }

    function persistHistory() {
      try {
        window.localStorage.setItem(historyStorageKey, JSON.stringify(history));
      } catch (error) {
        console.error(error);
      }
    }

    function hydrateHistory() {
      try {
        const raw = window.localStorage.getItem(historyStorageKey);
        if (!raw) {
          return;
        }
        const parsed = JSON.parse(raw);
        if (!Array.isArray(parsed)) {
          return;
        }
        parsed.forEach((item) => {
          if (!item || typeof item !== "object") {
            return;
          }
          const role = String(item.role || "").trim();
          const content = String(item.content || "").trim();
          if (!role || !content) {
            return;
          }
          const sources = Array.isArray(item.sources) ? item.sources : [];
          history.push({ role, content, sources });
          renderChatMessage(log, role, content, sources);
        });
      } catch (error) {
        console.error(error);
      }
    }

    async function sendMessage(text) {
      const payload = {
        message: text,
        history: historySnapshot(),
        collections: selectedCollections(),
        verbosity: verbosityInput ? verbosityInput.value : root.dataset.verbosity,
        top_k: topKInput ? topKInput.value : root.dataset.topK,
        history_limit: historyLimitInput
          ? historyLimitInput.value
          : root.dataset.maxHistory,
        context_budget_tokens: contextBudgetInput
          ? contextBudgetInput.value
          : root.dataset.contextBudgetTokens,
      };

      sendButton.disabled = true;
      updateStatus("Thinking...");

      try {
        const response = await fetch("/api/rag/chat", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Accept: "application/json",
          },
          body: JSON.stringify(payload),
        });
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.error || "Chat request failed.");
        }

        const reply = String(data.reply || "").trim() || "(no response)";
        const sources = Array.isArray(data.sources) ? data.sources : [];
        history.push({ role: "assistant", content: reply, sources: sources });
        renderChatMessage(log, "assistant", reply, sources);
        persistHistory();
        if (typeof data.elapsed_ms === "number") {
          updateStatus(`Answered in ${data.elapsed_ms} ms`);
        } else {
          updateStatus("Answered");
        }
      } catch (error) {
        renderChatMessage(log, "assistant", `Error: ${String(error.message || error)}`, []);
        updateStatus("Error");
      } finally {
        sendButton.disabled = false;
        input.focus();
      }
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const text = String(input.value || "").trim();
      if (!text) {
        return;
      }
      if (!selectedCollections().length) {
        updateStatus("Select at least one collection.");
        return;
      }

      input.value = "";
      history.push({ role: "user", content: text, sources: [] });
      renderChatMessage(log, "user", text, []);
      persistHistory();
      await sendMessage(text);
    });

    if (clearButton) {
      clearButton.addEventListener("click", () => {
        history = [];
        try {
          window.localStorage.removeItem(historyStorageKey);
        } catch (error) {
          console.error(error);
        }
        log.innerHTML = "";
        updateStatus("Cleared");
      });
    }

    hydrateHistory();
  }

  function wireIndexJobsPolling() {
    const jobsTable = document.querySelector("[data-rag-jobs-table]");
    if (!jobsTable) {
      return;
    }

    const rows = Array.from(document.querySelectorAll("tr[data-rag-job-id]"));
    if (!rows.length) {
      return;
    }

    const rowById = new Map();
    rows.forEach((row) => {
      const parsed = Number.parseInt(String(row.dataset.ragJobId || ""), 10);
      if (!Number.isNaN(parsed) && parsed > 0) {
        rowById.set(parsed, row);
      }
    });

    if (!rowById.size) {
      return;
    }

    function rowIsActive(row) {
      const status = String(row.dataset.ragJobStatus || "").trim().toLowerCase();
      return ACTIVE_JOB_STATUSES.has(status);
    }

    function updateRow(task) {
      const row = rowById.get(Number(task.id));
      if (!row) {
        return;
      }

      const status = String(task.status || "").trim().toLowerCase();
      row.dataset.ragJobStatus = status;

      const statusLabel = row.querySelector("[data-rag-job-status-label]");
      if (statusLabel) {
        statusLabel.className = `status ${statusClass(status)}`;
        statusLabel.textContent = status || "-";
      }

      const started = row.querySelector("[data-rag-job-started]");
      if (started) {
        started.textContent = formatTimestamp(task.started_at);
      }

      const finished = row.querySelector("[data-rag-job-finished]");
      if (finished) {
        finished.textContent = formatTimestamp(task.finished_at);
      }

      const progress = row.querySelector("[data-rag-job-progress]");
      if (progress) {
        const summary =
          task.progress && typeof task.progress.summary === "string"
            ? task.progress.summary.trim()
            : "";
        progress.textContent = summary || "-";
      }
    }

    async function poll() {
      const ids = Array.from(rowById.keys());
      const params = new URLSearchParams({ ids: ids.join(",") });

      try {
        const response = await fetch(`/api/rag/tasks/status?${params.toString()}`, {
          cache: "no-store",
          headers: { Accept: "application/json" },
        });
        if (!response.ok) {
          return;
        }
        const data = await response.json();
        const tasks = Array.isArray(data.tasks) ? data.tasks : [];
        tasks.forEach(updateRow);
      } catch (error) {
        console.error(error);
      }

      const stillActive = Array.from(rowById.values()).some(rowIsActive);
      if (stillActive) {
        window.setTimeout(poll, 2000);
      }
    }

    if (Array.from(rowById.values()).some(rowIsActive)) {
      poll();
    }
  }

  function wireIndexJobDetailPolling() {
    const detail = document.querySelector("[data-rag-job-detail]");
    if (!detail) {
      return;
    }

    const parsedId = Number.parseInt(String(detail.dataset.ragJobDetailId || ""), 10);
    if (Number.isNaN(parsedId) || parsedId <= 0) {
      return;
    }

    const statusEl = document.getElementById("rag-job-detail-status");
    const startedEl = document.getElementById("rag-job-detail-started");
    const finishedEl = document.getElementById("rag-job-detail-finished");
    const progressEl = document.getElementById("rag-job-detail-progress");
    const outputEl = document.getElementById("rag-job-detail-output");
    const outputEmptyEl = document.getElementById("rag-job-detail-output-empty");
    const errorEl = document.getElementById("rag-job-detail-error");

    function isActiveStatus(status) {
      return ACTIVE_JOB_STATUSES.has(String(status || "").trim().toLowerCase());
    }

    function updateDetail(task) {
      const status = String(task.status || "").trim().toLowerCase();
      detail.dataset.ragJobDetailStatus = status;

      if (statusEl) {
        statusEl.className = `status ${statusClass(status)}`;
        statusEl.textContent = status || "-";
      }
      if (startedEl) {
        startedEl.textContent = formatTimestamp(task.started_at);
      }
      if (finishedEl) {
        finishedEl.textContent = formatTimestamp(task.finished_at);
      }
      if (progressEl) {
        const summary =
          task.progress && typeof task.progress.summary === "string"
            ? task.progress.summary.trim()
            : "";
        progressEl.textContent = summary || "No progress details yet.";
      }
      if (outputEl) {
        const output = textOrFallback(task.output, "");
        if (output.trim()) {
          outputEl.style.display = "";
          outputEl.textContent = output;
          if (outputEmptyEl) {
            outputEmptyEl.style.display = "none";
          }
        } else {
          outputEl.style.display = "none";
          outputEl.textContent = "";
          if (outputEmptyEl) {
            outputEmptyEl.style.display = "";
          }
        }
      }
      if (errorEl) {
        const error = textOrFallback(task.error, "none");
        errorEl.textContent = error;
      }
    }

    async function poll() {
      try {
        const response = await fetch(`/api/rag/tasks/status?ids=${parsedId}`, {
          cache: "no-store",
          headers: { Accept: "application/json" },
        });
        if (!response.ok) {
          return;
        }
        const data = await response.json();
        const tasks = Array.isArray(data.tasks) ? data.tasks : [];
        if (!tasks.length) {
          return;
        }
        const task = tasks[0];
        updateDetail(task);
        if (isActiveStatus(task.status)) {
          window.setTimeout(poll, 2000);
        }
      } catch (error) {
        console.error(error);
      }
    }

    if (isActiveStatus(detail.dataset.ragJobDetailStatus)) {
      poll();
    }
  }

  wireRowLinks();
  wireSourceForm();
  wireChat();
  wireIndexJobsPolling();
  wireIndexJobDetailPolling();
})();
