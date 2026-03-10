const state = {
  token: localStorage.getItem("docker-panel-token") || "",
  user: null,
  bootstrap: null,
};

const elements = {
  loginPanel: document.getElementById("loginPanel"),
  dashboard: document.getElementById("dashboard"),
  loginForm: document.getElementById("loginForm"),
  username: document.getElementById("username"),
  password: document.getElementById("password"),
  loginFeedback: document.getElementById("loginFeedback"),
  credentialsHint: document.getElementById("credentialsHint"),
  modeChip: document.getElementById("modeChip"),
  dashboardMode: document.getElementById("dashboardMode"),
  welcomeLine: document.getElementById("welcomeLine"),
  statsGrid: document.getElementById("statsGrid"),
  machinesGrid: document.getElementById("machinesGrid"),
  activityList: document.getElementById("activityList"),
  actionFeedback: document.getElementById("actionFeedback"),
  logoutButton: document.getElementById("logoutButton"),
  composeBadge: document.getElementById("composeBadge"),
};

async function api(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };

  if (state.token) {
    headers.Authorization = `Bearer ${state.token}`;
  }

  const response = await fetch(path, {
    ...options,
    headers,
  });

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || "Erreur reseau.");
  }
  return payload;
}

function renderStats(summary) {
  const stats = [
    { label: "Machines totales", value: summary.total },
    { label: "En execution", value: summary.running },
    { label: "Arretees", value: summary.stopped },
    { label: "A surveiller", value: summary.degraded },
  ];

  elements.statsGrid.innerHTML = stats
    .map(
      (item) => `
        <article class="card stat-card">
          <div class="stat-label">${item.label}</div>
          <div class="stat-value">${item.value}</div>
        </article>
      `
    )
    .join("");
}

function pillClass(value) {
  return String(value || "").toLowerCase();
}

function renderMachines(containers) {
  elements.machinesGrid.innerHTML = containers
    .map(
      (container) => `
        <article class="machine-card">
          <header>
            <div>
              <h4>${container.name}</h4>
              <div class="machine-meta">
                <div><strong>Image</strong> ${container.image}</div>
                <div><strong>ID</strong> ${container.id}</div>
              </div>
            </div>
            <div class="status-pill ${pillClass(container.status)}">${container.status}</div>
          </header>
          <div class="machine-meta">
            <div><strong>Sante</strong> <span class="status-pill ${pillClass(container.health)}">${container.health}</span></div>
            <div><strong>Ports</strong> ${container.ports || "-"}</div>
            ${container.statusLabel ? `<div><strong>Etat brut</strong> ${container.statusLabel}</div>` : ""}
          </div>
        </article>
      `
    )
    .join("");
}

function renderActivity(entries) {
  elements.activityList.innerHTML = entries.map((item) => `<li>${item}</li>`).join("");
}

function setMode(mode) {
  const label = mode === "docker" ? "Mode Docker reel" : "Mode demo";
  elements.modeChip.textContent = label;
  elements.dashboardMode.textContent = label;
}

function setFeedback(target, message, isError = false) {
  target.textContent = message || "";
  target.style.color = isError ? "var(--warning)" : "var(--muted)";
}

function showDashboard(show) {
  elements.loginPanel.classList.toggle("hidden", show);
  elements.dashboard.classList.toggle("hidden", !show);
}

function renderDashboard(payload) {
  state.user = payload.user || state.user;
  state.bootstrap = payload;
  renderStats(payload.summary);
  renderMachines(payload.containers);
  renderActivity(payload.activity);
  setMode(payload.mode);
  elements.composeBadge.textContent = payload.composeAvailable
    ? "Compose detecte"
    : "Compose non detecte";
  elements.welcomeLine.textContent = `Connecte en tant que ${state.user?.username || "admin"} • ${
    payload.mode === "docker" ? "actions reelles disponibles" : "actions de demonstration"
  }`;
}

async function loadBootstrap() {
  const payload = await api("/api/bootstrap", { method: "GET" });
  setMode(payload.mode);
  elements.username.value = payload.credentials.username;
  elements.credentialsHint.innerHTML = `Identifiants par defaut: <code>${payload.credentials.username}</code> / <code>${payload.credentials.password}</code>`;
  return payload;
}

async function refreshDashboard() {
  const payload = await api("/api/dashboard", { method: "GET" });
  renderDashboard(payload);
  return payload;
}

elements.loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setFeedback(elements.loginFeedback, "Connexion en cours...");

  try {
    const payload = await api("/api/login", {
      method: "POST",
      body: JSON.stringify({
        username: elements.username.value.trim(),
        password: elements.password.value,
      }),
    });

    state.token = payload.token;
    state.user = payload.user;
    localStorage.setItem("docker-panel-token", state.token);
    setFeedback(elements.loginFeedback, "");
    showDashboard(true);
    await refreshDashboard();
  } catch (error) {
    setFeedback(elements.loginFeedback, error.message, true);
  }
});

document.querySelectorAll("[data-action]").forEach((button) => {
  button.addEventListener("click", async () => {
    const action = button.dataset.action;
    setFeedback(elements.actionFeedback, "Execution en cours...");

    try {
      const payload = await api(`/api/actions/${action}`, { method: "POST" });
      renderDashboard(payload);
      setFeedback(elements.actionFeedback, payload.message || "Action terminee.");
    } catch (error) {
      setFeedback(elements.actionFeedback, error.message, true);
    }
  });
});

elements.logoutButton.addEventListener("click", async () => {
  try {
    await api("/api/logout", { method: "POST" });
  } catch (error) {
    // ignore logout race or expired session
  }

  state.token = "";
  state.user = null;
  localStorage.removeItem("docker-panel-token");
  showDashboard(false);
  setFeedback(elements.actionFeedback, "");
});

async function init() {
  await loadBootstrap();

  if (!state.token) {
    return;
  }

  try {
    await refreshDashboard();
    showDashboard(true);
  } catch (error) {
    localStorage.removeItem("docker-panel-token");
    state.token = "";
    showDashboard(false);
  }
}

init().catch((error) => {
  setFeedback(elements.loginFeedback, error.message, true);
});
