const state = {
  token: localStorage.getItem("docker-panel-token") || "",
  user: null,
  bootstrap: null,
};

const el = {
  loginPanel:        document.getElementById("loginPanel"),
  app:               document.getElementById("app"),
  loginForm:         document.getElementById("loginForm"),
  username:          document.getElementById("username"),
  password:          document.getElementById("password"),
  loginFeedback:     document.getElementById("loginFeedback"),
  credentialsHint:   document.getElementById("credentialsHint"),
  modeChip:          document.getElementById("modeChip"),
  headerMode:        document.getElementById("headerMode"),
  headerUser:        document.getElementById("headerUser"),
  headerStats:       document.getElementById("headerStats"),
  statusUser:        document.getElementById("statusUser"),
  sidebarTree:       document.getElementById("sidebarTree"),
  statTotal:         document.getElementById("statTotal"),
  statRunning:       document.getElementById("statRunning"),
  statStopped:       document.getElementById("statStopped"),
  statDegraded:      document.getElementById("statDegraded"),
  quickContainers:   document.getElementById("quickContainers"),
  containersTableBody: document.getElementById("containersTableBody"),
  containerCount:    document.getElementById("containerCount"),
  activityList:      document.getElementById("activityList"),
  actionFeedback:    document.getElementById("actionFeedback"),
  composeBadge:      document.getElementById("composeBadge"),
  logoutBtn:         document.getElementById("logoutBtn"),
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

// ===== RENDER =====

function pillClass(value) {
  return String(value || "").toLowerCase();
}

function renderStats(summary) {
  el.statTotal.textContent   = summary.total;
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

function renderSidebar(containers) {
  el.sidebarTree.innerHTML = containers.map(c => `
    <div class="sidebar-item">
      <span class="sidebar-status-dot ${pillClass(c.status)}"></span>
      <span>${c.name}</span>
    </div>
  `).join("");
}

function renderQuickContainers(containers) {
  el.quickContainers.innerHTML = containers.map(c => `
    <div class="quick-item">
      <span class="sidebar-status-dot ${pillClass(c.status)}"></span>
      <span class="quick-item-name">${c.name}</span>
      <span class="status-pill ${pillClass(c.status)}">${c.status}</span>
      <span class="quick-item-image">${c.image}</span>
    </div>
  `).join("");
}

function renderTable(containers) {
  el.containerCount.textContent = containers.length;
  el.containersTableBody.innerHTML = containers.map(c => `
    <tr>
      <td><span class="status-pill ${pillClass(c.status)}">${c.status}</span></td>
      <td><strong>${c.name}</strong></td>
      <td class="td-mono">${c.image}</td>
      <td class="td-mono">${c.id}</td>
      <td><span class="status-pill ${pillClass(c.health)}">${c.health}</span></td>
      <td class="td-mono">${c.ports || "—"}</td>
    </tr>
  `).join("");
}

function renderActivity(entries) {
  el.activityList.innerHTML = entries.map(item =>
    `<div class="log-entry">${item}</div>`
  ).join("");
}

function setMode(mode) {
  const label = mode === "docker" ? "Mode Docker reel" : "Mode demo";
  el.modeChip.textContent  = label;
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
  state.user = payload.user || state.user;
  renderStats(payload.summary);
  renderSidebar(payload.containers);
  renderQuickContainers(payload.containers);
  renderTable(payload.containers);
  renderActivity(payload.activity);
  setMode(payload.mode);

  const username = state.user?.username || "admin";
  el.headerUser.textContent = username;
  el.statusUser.textContent = `${username} — ${payload.mode === "docker" ? "Docker reel" : "Demo"}`;
  el.composeBadge.textContent = payload.composeAvailable ? "✓ Compose detecte" : "✗ Compose absent";
}

// ===== TABS =====

document.querySelectorAll(".pve-tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".pve-tab").forEach(t => t.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach(c => c.classList.add("hidden"));
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

// Sidebar action buttons
document.getElementById("startAllBtn").addEventListener("click",   () => doAction("start-all"));
document.getElementById("restartAllBtn").addEventListener("click", () => doAction("restart-all"));
document.getElementById("stopAllBtn").addEventListener("click",    () => doAction("stop-all"));
document.getElementById("deployBtn").addEventListener("click",     () => doAction("deploy-stack"));

// Summary action buttons (data-action attribute)
document.querySelectorAll("[data-action]").forEach(btn => {
  btn.addEventListener("click", () => doAction(btn.dataset.action));
});

// ===== LOGIN =====

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

    state.token = payload.token;
    state.user  = payload.user;
    localStorage.setItem("docker-panel-token", state.token);
    el.loginFeedback.textContent = "";
    showApp(true);
    await refreshDashboard();
  } catch (error) {
    el.loginFeedback.textContent = error.message;
    el.loginFeedback.style.color = "var(--red)";
  }
});

// ===== LOGOUT =====

el.logoutBtn.addEventListener("click", async () => {
  try { await api("/api/logout", { method: "POST" }); } catch (_) {}
  state.token = "";
  state.user  = null;
  localStorage.removeItem("docker-panel-token");
  showApp(false);
  setFeedback("");
});

// ===== BOOTSTRAP / INIT =====

async function loadBootstrap() {
  const payload = await api("/api/bootstrap", { method: "GET" });
  setMode(payload.mode);
  el.username.value = payload.credentials.username;
  el.credentialsHint.innerHTML =
    `Identifiants: <code>${payload.credentials.username}</code> / <code>${payload.credentials.password}</code>`;
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
  } catch (_) {
    localStorage.removeItem("docker-panel-token");
    state.token = "";
    showApp(false);
  }
}

init().catch(err => {
  el.loginFeedback.textContent = err.message;
});
