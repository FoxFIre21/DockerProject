const state = {
  token: localStorage.getItem("docker-panel-token") || "",
  user: null,
  bootstrap: null,
  dashboard: null,
  selectedContainerId: "",
  tempToken: "",
};

const el = {
  loginPanel: document.getElementById("loginPanel"),
  app: document.getElementById("app"),
  loginForm: document.getElementById("loginForm"),
  username: document.getElementById("username"),
  password: document.getElementById("password"),
  loginFeedback: document.getElementById("loginFeedback"),
  modeChip: document.getElementById("modeChip"),
  headerMode: document.getElementById("headerMode"),
  headerUser: document.getElementById("headerUser"),
  headerStats: document.getElementById("headerStats"),
  statusUser: document.getElementById("statusUser"),
  sidebarTree: document.getElementById("sidebarTree"),
  statTotal: document.getElementById("statTotal"),
  statRunning: document.getElementById("statRunning"),
  statStopped: document.getElementById("statStopped"),
  statDegraded: document.getElementById("statDegraded"),
  quickContainers: document.getElementById("quickContainers"),
  selectedContainerCard: document.getElementById("selectedContainerCard"),
  containersTableBody: document.getElementById("containersTableBody"),
  containerCount: document.getElementById("containerCount"),
  activityList: document.getElementById("activityList"),
  actionFeedback: document.getElementById("actionFeedback"),
  composeBadge: document.getElementById("composeBadge"),
  logoutBtn: document.getElementById("logoutBtn"),
  twoFaStep: document.getElementById("twoFaStep"),
  twoFaCode: document.getElementById("twoFaCode"),
  twoFaSubmit: document.getElementById("twoFaSubmit"),
  twoFaFeedback: document.getElementById("twoFaFeedback"),
};

// ===== API =====

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(path, { ...options, headers });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || "Erreur reseau.");
  return payload;
}

// Expose api globally so admin.js can reuse it
window.api = api;

// ===== HELPERS =====

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => {
    const entities = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };
    return entities[char];
  });
}

function pillClass(value) {
  return String(value || "").toLowerCase();
}

function containerActionButtons(containerId) {
  const escapedId = escapeHtml(containerId);
  return `
    <button class="btn-inline-action start" data-container-action="start" data-container-id="${escapedId}">Demarrer</button>
    <button class="btn-inline-action restart" data-container-action="restart" data-container-id="${escapedId}">Redemarrer</button>
    <button class="btn-inline-action stop" data-container-action="stop" data-container-id="${escapedId}">Arreter</button>
  `;
}

function syncSelectedContainer(containers) {
  if (!containers.length) {
    state.selectedContainerId = "";
    return null;
  }

  const selected = containers.find((container) => container.id === state.selectedContainerId);
  if (selected) return selected;

  state.selectedContainerId = containers[0].id;
  return containers[0];
}

function selectContainer(containerId) {
  state.selectedContainerId = containerId;
  if (state.dashboard) renderDashboard(state.dashboard);
}

// ===== RENDER =====

function renderStats(summary) {
  el.statTotal.textContent = summary.total;
  el.statRunning.textContent = summary.running;
  el.statStopped.textContent = summary.stopped;
  el.statDegraded.textContent = summary.degraded;

  el.headerStats.innerHTML = `
    <span class="header-stat-chip">Total <span class="chip-val">${summary.total}</span></span>
    <span class="header-stat-chip chip-green">Running <span class="chip-val">${summary.running}</span></span>
    <span class="header-stat-chip">Stopped <span class="chip-val">${summary.stopped}</span></span>
    ${summary.degraded > 0
      ? `<span class="header-stat-chip chip-orange">Degraded <span class="chip-val">${summary.degraded}</span></span>`
      : ""}
  `;
}

function renderSidebar(containers, selectedId) {
  if (!containers.length) {
    el.sidebarTree.innerHTML = '<div class="sidebar-item empty">Aucune machine</div>';
    return;
  }

  el.sidebarTree.innerHTML = containers.map((container) => `
    <button class="sidebar-item${container.id === selectedId ? " active" : ""}" data-container-id="${escapeHtml(container.id)}">
      <span class="sidebar-status-dot ${pillClass(container.status)}"></span>
      <span>${escapeHtml(container.name)}</span>
    </button>
  `).join("");
}

function renderQuickContainers(containers, selectedId) {
  if (!containers.length) {
    el.quickContainers.innerHTML = '<div class="quick-item empty">Aucune machine disponible.</div>';
    return;
  }

  el.quickContainers.innerHTML = containers.map((container) => `
    <button class="quick-item${container.id === selectedId ? " active" : ""}" data-container-id="${escapeHtml(container.id)}">
      <span class="sidebar-status-dot ${pillClass(container.status)}"></span>
      <span class="quick-item-name">${escapeHtml(container.name)}</span>
      <span class="status-pill ${pillClass(container.status)}">${escapeHtml(container.status)}</span>
      <span class="quick-item-image">${escapeHtml(container.image)}</span>
    </button>
  `).join("");
}

function renderSelectedContainer(container) {
  if (!container) {
    el.selectedContainerCard.innerHTML = `
      <div class="selected-container-empty">
        Aucune machine selectionnable.
      </div>
    `;
    return;
  }

  el.selectedContainerCard.innerHTML = `
    <div class="selected-container">
      <div class="selected-container-name">${escapeHtml(container.name)}</div>
      <div class="selected-container-image">${escapeHtml(container.image)}</div>
      <div class="selected-container-badges">
        <span class="status-pill ${pillClass(container.status)}">${escapeHtml(container.status)}</span>
        <span class="status-pill ${pillClass(container.health)}">${escapeHtml(container.health)}</span>
      </div>
      <div class="selected-container-meta">
        <div class="selected-container-row">
          <span class="selected-container-label">ID</span>
          <span class="selected-container-value td-mono">${escapeHtml(container.id)}</span>
        </div>
        <div class="selected-container-row">
          <span class="selected-container-label">Ports</span>
          <span class="selected-container-value td-mono">${escapeHtml(container.ports || "-")}</span>
        </div>
      </div>
      <div class="selected-container-actions">
        ${containerActionButtons(container.id)}
      </div>
    </div>
  `;
}

function renderTable(containers, selectedId) {
  el.containerCount.textContent = containers.length;

  if (!containers.length) {
    el.containersTableBody.innerHTML = `
      <tr>
        <td colspan="7" class="table-empty">Aucune machine disponible.</td>
      </tr>
    `;
    return;
  }

  el.containersTableBody.innerHTML = containers.map((container) => `
    <tr class="container-row${container.id === selectedId ? " selected" : ""}" data-container-id="${escapeHtml(container.id)}">
      <td><span class="status-pill ${pillClass(container.status)}">${escapeHtml(container.status)}</span></td>
      <td><strong>${escapeHtml(container.name)}</strong></td>
      <td class="td-mono">${escapeHtml(container.image)}</td>
      <td class="td-mono">${escapeHtml(container.id)}</td>
      <td><span class="status-pill ${pillClass(container.health)}">${escapeHtml(container.health)}</span></td>
      <td class="td-mono">${escapeHtml(container.ports || "-")}</td>
      <td>
        <div class="table-action-group">
          ${containerActionButtons(container.id)}
        </div>
      </td>
    </tr>
  `).join("");
}

function renderActivity(entries) {
  el.activityList.innerHTML = entries.map((item) =>
    `<div class="log-entry">${escapeHtml(item)}</div>`
  ).join("");
}

function setMode(mode) {
  const label = mode === "docker" ? "Mode Docker reel" : "Mode demo";
  el.modeChip.textContent = label;
  el.headerMode.textContent = label;
}

function setFeedback(message, isError = false) {
  el.actionFeedback.textContent = message || "";
  el.actionFeedback.className = "action-feedback" + (isError ? " error" : message ? " success" : "");
}

function showApp(show) {
  el.loginPanel.classList.toggle("hidden", show);
  el.app.classList.toggle("hidden", !show);
}

function renderDashboard(payload) {
  state.dashboard = payload;
  state.user = payload.user || state.user;
  window.appUser = state.user;

  const selectedContainer = syncSelectedContainer(payload.containers);

  renderStats(payload.summary);
  renderSidebar(payload.containers, selectedContainer?.id || "");
  renderQuickContainers(payload.containers, selectedContainer?.id || "");
  renderSelectedContainer(selectedContainer);
  renderTable(payload.containers, selectedContainer?.id || "");
  renderActivity(payload.activity);
  setMode(payload.mode);

  const username = state.user?.username || "admin";
  el.headerUser.textContent = username;
  el.statusUser.textContent = `${username} — ${payload.mode === "docker" ? "Docker reel" : "Demo"}`;
  el.composeBadge.textContent = payload.composeAvailable ? "✓ Compose detecte" : "✗ Compose absent";
}

// ===== TABS =====

document.querySelectorAll(".app-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".app-tab").forEach((item) => item.classList.remove("active"));
    document.querySelectorAll(".tab-pane").forEach((content) => content.classList.add("hidden"));
    tab.classList.add("active");
    const target = document.getElementById("tab-" + tab.dataset.tab);
    if (target) target.classList.remove("hidden");
  });
});

// ===== ACTIONS =====

async function doAction(action) {
  setFeedback("Execution en cours...");
  try {
    const payload = await api(`/api/actions/${action}`, { method: "POST" });
    renderDashboard(payload);
    setFeedback(payload.message || "Action terminee.");
  } catch (error) {
    setFeedback(error.message, true);
  }
}

async function doContainerAction(containerId, action) {
  setFeedback(`Execution sur ${containerId}...`);
  try {
    const payload = await api(
      `/api/containers/${encodeURIComponent(containerId)}/actions/${action}`,
      { method: "POST" }
    );
    state.selectedContainerId = containerId;
    renderDashboard(payload);
    setFeedback(payload.message || "Action terminee.");
  } catch (error) {
    setFeedback(error.message, true);
  }
}

document.getElementById("startAllBtn").addEventListener("click", () => doAction("start-all"));
document.getElementById("restartAllBtn").addEventListener("click", () => doAction("restart-all"));
document.getElementById("stopAllBtn").addEventListener("click", () => doAction("stop-all"));
document.getElementById("deployBtn").addEventListener("click", () => doAction("deploy-stack"));

document.querySelectorAll("[data-action]").forEach((btn) => {
  btn.addEventListener("click", () => doAction(btn.dataset.action));
});

el.sidebarTree.addEventListener("click", (event) => {
  const item = event.target.closest("[data-container-id]");
  if (!item) return;
  selectContainer(item.dataset.containerId);
});

el.quickContainers.addEventListener("click", (event) => {
  const item = event.target.closest("[data-container-id]");
  if (!item) return;
  selectContainer(item.dataset.containerId);
});

el.containersTableBody.addEventListener("click", (event) => {
  const actionButton = event.target.closest("[data-container-action]");
  if (actionButton) {
    doContainerAction(actionButton.dataset.containerId, actionButton.dataset.containerAction);
    return;
  }

  const row = event.target.closest("tr[data-container-id]");
  if (!row) return;
  selectContainer(row.dataset.containerId);
});

el.selectedContainerCard.addEventListener("click", (event) => {
  const actionButton = event.target.closest("[data-container-action]");
  if (!actionButton) return;
  doContainerAction(actionButton.dataset.containerId, actionButton.dataset.containerAction);
});

// ===== LOGIN =====

function showTwoFaStep() {
  el.loginForm.classList.add("hidden");
  el.twoFaStep.classList.remove("hidden");
  el.twoFaCode.value = "";
  el.twoFaFeedback.textContent = "";
  el.twoFaCode.focus();
}

function resetLoginStep() {
  el.loginForm.classList.remove("hidden");
  el.twoFaStep.classList.add("hidden");
  state.tempToken = "";
  el.twoFaCode.value = "";
  el.twoFaFeedback.textContent = "";
}

el.twoFaSubmit.addEventListener("click", async () => {
  const code = el.twoFaCode.value.trim();
  if (!code) {
    el.twoFaFeedback.textContent = "Saisissez le code.";
    return;
  }

  el.twoFaFeedback.textContent = "Verification...";
  el.twoFaFeedback.style.color = "";

  try {
    const payload = await api("/api/2fa/verify", {
      method: "POST",
      body: JSON.stringify({
        temp_token: state.tempToken,
        code,
      }),
    });

    state.token = payload.token;
    state.user = payload.user;
    window.appUser = state.user;
    localStorage.setItem("docker-panel-token", state.token);
    resetLoginStep();
    el.loginFeedback.textContent = "";
    showApp(true);
    await refreshDashboard();
    if (typeof window.initAdmin === "function") window.initAdmin();
  } catch (error) {
    el.twoFaFeedback.textContent = error.message;
    el.twoFaFeedback.style.color = "var(--red)";
  }
});

el.loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  el.loginFeedback.textContent = "Connexion en cours...";
  el.loginFeedback.style.color = "";

  try {
    const payload = await api("/api/login", {
      method: "POST",
      body: JSON.stringify({
        username: el.username.value.trim(),
        password: el.password.value,
      }),
    });

    if (payload["2fa_required"]) {
      state.tempToken = payload.temp_token || "";
      el.loginFeedback.textContent = "";
      showTwoFaStep();
      return;
    }

    state.token = payload.token;
    state.user = payload.user;
    window.appUser = state.user;
    localStorage.setItem("docker-panel-token", state.token);
    el.loginFeedback.textContent = "";
    showApp(true);
    await refreshDashboard();
    if (typeof window.initAdmin === "function") window.initAdmin();
  } catch (error) {
    el.loginFeedback.textContent = error.message;
    el.loginFeedback.style.color = "var(--red)";
  }
});

// ===== LOGOUT =====

el.logoutBtn.addEventListener("click", async () => {
  try {
    await api("/api/logout", { method: "POST" });
  } catch (_) {}

  state.token = "";
  state.user = null;
  window.appUser = null;
  state.dashboard = null;
  state.selectedContainerId = "";
  state.tempToken = "";
  localStorage.removeItem("docker-panel-token");
  resetLoginStep();
  showApp(false);
  setFeedback("");
});

// adminBtn click is handled by admin.js once initAdmin() is called

// ===== BOOTSTRAP / INIT =====

async function loadBootstrap() {
  const payload = await api("/api/bootstrap", { method: "GET" });
  state.bootstrap = payload;
  setMode(payload.mode);
}

async function refreshDashboard() {
  const payload = await api("/api/dashboard", { method: "GET" });
  renderDashboard(payload);
}

async function init() {
  await loadBootstrap();
  if (!state.token) return;
  try {
    await refreshDashboard();
    showApp(true);
    if (typeof window.initAdmin === "function") window.initAdmin();
  } catch (_) {
    localStorage.removeItem("docker-panel-token");
    state.token = "";
    showApp(false);
  }
}

init().catch((error) => {
  el.loginFeedback.textContent = error.message;
});
