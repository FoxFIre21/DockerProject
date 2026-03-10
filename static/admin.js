(function () {
  "use strict";

  const adminState = {
    open: false,
    activeTab: "profil",
    initialized: false,
    canManageUsers: false,
    currentRole: "user",
  };

  function getEl(id) {
    return document.getElementById(id);
  }

  function adminApi(path, options) {
    return window.api(path, options);
  }

  function setFeedback(id, message, type) {
    const el = getEl(id);
    if (!el) return;
    el.textContent = message || "";
    el.className = "admin-feedback" + (type ? " " + type : "");
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[char]));
  }

  function formatDate(ts) {
    if (!ts) return "—";
    try {
      return new Date(ts * 1000).toLocaleString("fr-FR");
    } catch (_) {
      return String(ts);
    }
  }

  function roleLabel(role) {
    return {
      admin: "Administrateur",
      operator: "Operateur",
      user: "Utilisateur",
    }[role] || role;
  }

  function applyManagementAccess(role) {
    adminState.currentRole = role || "user";
    adminState.canManageUsers = role === "admin" || role === "operator";
    const usersTab = document.querySelector('[data-modal-tab="users"]');
    const usersPanel = getEl("modal-panel-users");
    const roleSelect = getEl("newUserRole");

    if (usersTab) usersTab.classList.toggle("hidden", !adminState.canManageUsers);
    if (roleSelect) {
      roleSelect.innerHTML = role === "admin"
        ? `
          <option value="user">Utilisateur</option>
          <option value="operator">Operateur</option>
          <option value="admin">Administrateur</option>
        `
        : '<option value="user">Utilisateur</option>';
    }
    if (usersPanel && !adminState.canManageUsers && adminState.activeTab === "users") {
      switchTab("profil");
    }
  }

  function initAdmin() {
    if (adminState.initialized) return;

    const adminBtn = getEl("adminBtn");
    const modal = getEl("adminModal");
    const closeBtn = getEl("adminModalClose");

    if (!adminBtn || !modal) return;

    adminBtn.addEventListener("click", () => openAdmin());

    modal.addEventListener("click", (event) => {
      if (event.target === modal) closeAdmin();
    });

    if (closeBtn) closeBtn.addEventListener("click", () => closeAdmin());

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && adminState.open) closeAdmin();
    });

    document.querySelectorAll("[data-modal-tab]").forEach((btn) => {
      btn.addEventListener("click", () => switchTab(btn.dataset.modalTab));
    });

    getEl("saveEmailBtn")?.addEventListener("click", saveEmail);
    getEl("changePasswordBtn")?.addEventListener("click", changePassword);
    getEl("createUserBtn")?.addEventListener("click", createUser);

    adminState.initialized = true;
  }

  function openAdmin() {
    const modal = getEl("adminModal");
    if (!modal) return;
    applyManagementAccess(window.appUser?.role || "user");
    modal.classList.remove("hidden");
    adminState.open = true;
    switchTab(adminState.activeTab);
  }

  function closeAdmin() {
    const modal = getEl("adminModal");
    if (!modal) return;
    modal.classList.add("hidden");
    adminState.open = false;
  }

  function switchTab(tabName) {
    if (tabName === "users" && !adminState.canManageUsers) {
      tabName = "profil";
    }

    adminState.activeTab = tabName;

    document.querySelectorAll("[data-modal-tab]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.modalTab === tabName);
    });

    document.querySelectorAll(".modal-panel").forEach((panel) => {
      panel.classList.remove("active");
      panel.classList.add("hidden");
    });

    const activePanel = getEl("modal-panel-" + tabName);
    if (activePanel) {
      activePanel.classList.add("active");
      activePanel.classList.remove("hidden");
    }

    if (tabName === "profil") loadProfile();
    if (tabName === "a2f") loadTwoFaStatus();
    if (tabName === "sessions") loadSessions();
    if (tabName === "users") loadUsers();
  }

  async function loadProfile() {
    try {
      const data = await adminApi("/api/account");
      getEl("profileUsername").value = data.username || "";
      getEl("profileEmail").value = data.email || "";
      applyManagementAccess(data.role || "user");
    } catch (error) {
      setFeedback("profileFeedback", error.message, "error");
    }
  }

  async function saveEmail() {
    const email = getEl("profileEmail")?.value.trim() || "";
    setFeedback("profileFeedback", "Sauvegarde en cours...", "");

    try {
      await adminApi("/api/account/email", {
        method: "POST",
        body: JSON.stringify({ email }),
      });
      setFeedback("profileFeedback", "Email mis a jour.", "success");
    } catch (error) {
      setFeedback("profileFeedback", error.message, "error");
    }
  }

  async function changePassword() {
    const current = getEl("currentPassword")?.value || "";
    const nextPassword = getEl("newPassword")?.value || "";
    const confirm = getEl("confirmPassword")?.value || "";

    if (!current) {
      setFeedback("securiteFeedback", "Veuillez saisir le mot de passe actuel.", "error");
      return;
    }
    if (!nextPassword) {
      setFeedback("securiteFeedback", "Veuillez saisir un nouveau mot de passe.", "error");
      return;
    }
    if (nextPassword !== confirm) {
      setFeedback("securiteFeedback", "Les mots de passe ne correspondent pas.", "error");
      return;
    }

    setFeedback("securiteFeedback", "Modification en cours...", "");

    try {
      await adminApi("/api/account/password", {
        method: "POST",
        body: JSON.stringify({ current, new_password: nextPassword }),
      });
      setFeedback("securiteFeedback", "Mot de passe modifie avec succes.", "success");
      getEl("currentPassword").value = "";
      getEl("newPassword").value = "";
      getEl("confirmPassword").value = "";
    } catch (error) {
      setFeedback("securiteFeedback", error.message, "error");
    }
  }

  async function loadTwoFaStatus() {
    const container = getEl("twoFaCards");
    if (!container) return;
    container.innerHTML = '<div class="twofa-card-loading">Chargement...</div>';

    try {
      const payload = await adminApi("/api/2fa/status");
      renderTwoFaCard(Boolean(payload.totp));
    } catch (error) {
      container.innerHTML = `<div class="twofa-card-loading" style="color:var(--red)">${escapeHtml(error.message)}</div>`;
    }
  }

  function renderTwoFaCard(enabled) {
    const container = getEl("twoFaCards");
    if (!container) return;

    container.innerHTML = `
      <div class="twofa-card${enabled ? " enabled" : ""}" id="twofa-card-totp">
        <div class="twofa-card-header">
          <div class="twofa-card-info">
            <div class="twofa-card-icon totp">
              <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M3 4a1 1 0 011-1h3a1 1 0 011 1v3a1 1 0 01-1 1H4a1 1 0 01-1-1V4zm2 2V5h1v1H5zM3 13a1 1 0 011-1h3a1 1 0 011 1v3a1 1 0 01-1 1H4a1 1 0 01-1-1v-3zm2 2v-1h1v1H5zM13 3a1 1 0 00-1 1v3a1 1 0 001 1h3a1 1 0 001-1V4a1 1 0 00-1-1h-3zm1 2v1h1V5h-1z" clip-rule="evenodd"/><path d="M11 4a1 1 0 10-2 0v1a1 1 0 002 0V4zM10 7a1 1 0 011 1v1h2a1 1 0 110 2h-3a1 1 0 01-1-1V8a1 1 0 011-1zM16 9a1 1 0 100 2 1 1 0 000-2zM9 13a1 1 0 011-1h1a1 1 0 110 2v2a1 1 0 11-2 0v-3zM7 11a1 1 0 110-2h1a1 1 0 110 2H7zM17 13a1 1 0 01-1 1h-2a1 1 0 110-2h2a1 1 0 011 1zM16 17a1 1 0 100-2h-3a1 1 0 100 2h3z"/></svg>
            </div>
            <div>
              <div class="twofa-card-title">TOTP via QR code</div>
              <div class="twofa-card-desc">Compatible Google Authenticator, 2FAS, Authy et autres applications TOTP</div>
            </div>
          </div>
          <div class="twofa-card-actions">
            <span class="status-badge ${enabled ? "active" : "inactive"}">${enabled ? "Actif" : "Inactif"}</span>
            ${enabled
              ? '<button class="btn-danger" id="twofa-disable-totp">Desactiver</button>'
              : '<button class="btn-primary" id="twofa-enable-totp">Activer</button>'
            }
          </div>
        </div>
        <div class="twofa-card-body hidden" id="twofa-setup-totp"></div>
      </div>
    `;

    getEl("twofa-enable-totp")?.addEventListener("click", () => renderTotpSetup());
    getEl("twofa-disable-totp")?.addEventListener("click", () => disableTotp());
  }

  async function renderTotpSetup() {
    const container = getEl("twofa-setup-totp");
    if (!container) return;
    container.classList.remove("hidden");
    container.innerHTML = '<p style="color:var(--text-3);font-size:13px">Chargement...</p>';

    try {
      const payload = await adminApi("/api/2fa/totp/setup");
      const secret = payload.secret || "";
      const qrSvg = payload.qr_svg || "";

      container.innerHTML = `
        <div class="twofa-qr-wrap">
          <div id="totp-qr-canvas">${qrSvg || '<div class="twofa-qr-fallback">QR indisponible</div>'}</div>
          <p class="twofa-qr-label">Scannez ce QR code avec votre application TOTP</p>
        </div>
        <p style="font-size:12px;color:var(--text-3);margin-bottom:8px">Ou entrez manuellement la cle secrete :</p>
        <div class="twofa-secret-row">
          <div class="twofa-secret" id="totp-secret-display">${escapeHtml(secret)}</div>
          <button class="twofa-copy-btn" id="totp-copy-btn">Copier</button>
        </div>
        <div class="field-group" style="margin-bottom:12px">
          <label class="field-label">Code de verification</label>
          <input type="text" class="field-input field-input-plain" id="totp-verify-code" inputmode="numeric" maxlength="6" placeholder="000000" />
        </div>
        <div class="twofa-step-actions">
          <button class="btn-primary" id="totp-confirm-btn">Confirmer et activer</button>
          <button class="btn-ghost" id="totp-cancel-btn">Annuler</button>
        </div>
        <p class="twofa-feedback" id="totp-setup-feedback"></p>
      `;

      getEl("totp-copy-btn")?.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(secret);
          getEl("totp-copy-btn").textContent = "Copie !";
          setTimeout(() => {
            const btn = getEl("totp-copy-btn");
            if (btn) btn.textContent = "Copier";
          }, 1500);
        } catch (_) {}
      });

      getEl("totp-confirm-btn")?.addEventListener("click", () => enableTotp());
      getEl("totp-cancel-btn")?.addEventListener("click", () => {
        container.classList.add("hidden");
      });
    } catch (error) {
      container.innerHTML = `<p style="color:var(--red);font-size:13px">${escapeHtml(error.message)}</p>`;
    }
  }

  async function enableTotp() {
    const code = getEl("totp-verify-code")?.value.trim() || "";
    if (!code || code.length !== 6) {
      setTwoFaFeedback("totp-setup-feedback", "Saisissez un code a 6 chiffres.", "error");
      return;
    }

    setTwoFaFeedback("totp-setup-feedback", "Verification...", "");

    try {
      await adminApi("/api/2fa/totp/enable", {
        method: "POST",
        body: JSON.stringify({ code }),
      });
      setTwoFaFeedback("totp-setup-feedback", "A2F activee avec succes.", "success");
      setTimeout(() => loadTwoFaStatus(), 1000);
    } catch (error) {
      setTwoFaFeedback("totp-setup-feedback", error.message, "error");
    }
  }

  async function disableTotp() {
    if (!confirm("Desactiver l'A2F TOTP pour ce compte ?")) return;

    try {
      await adminApi("/api/2fa/totp/disable", { method: "POST" });
      loadTwoFaStatus();
    } catch (error) {
      alert("Erreur : " + error.message);
    }
  }

  function setTwoFaFeedback(id, message, type) {
    const el = getEl(id);
    if (!el) return;
    el.textContent = message || "";
    el.className = "twofa-feedback" + (type ? " " + type : "");
  }

  async function loadUsers() {
    const container = getEl("usersList");
    if (!container) return;

    if (!adminState.canManageUsers) {
      container.innerHTML = '<div class="sessions-loading">Acces de gestion requis.</div>';
      return;
    }

    container.innerHTML = '<div class="sessions-loading">Chargement...</div>';

    try {
      const payload = await adminApi("/api/admin/users");
      renderUsers(payload.users || []);
    } catch (error) {
      container.innerHTML = `<div class="sessions-loading" style="color:var(--red)">${escapeHtml(error.message)}</div>`;
    }
  }

  function renderUsers(users) {
    const container = getEl("usersList");
    if (!container) return;

    if (!users.length) {
      container.innerHTML = '<div class="sessions-loading">Aucun utilisateur.</div>';
      return;
    }

    container.innerHTML = users.map((user) => `
      <div class="user-row">
        <div class="user-row-main">
          <div class="user-row-title">
            <span>${escapeHtml(user.username)}</span>
            <span class="status-badge ${user.role === "admin" ? "active" : user.role === "operator" ? "pending" : "inactive"}">${escapeHtml(roleLabel(user.role))}</span>
          </div>
          <div class="user-row-meta">${escapeHtml(user.email || "Aucun email")}</div>
        </div>
        <div class="user-row-actions">
          ${Array.isArray(user.assignable_roles) && user.assignable_roles.length
            ? `<select class="field-input field-input-plain user-role-select" data-role-user="${escapeHtml(user.username)}">
                ${user.assignable_roles.map((role) => `<option value="${escapeHtml(role)}"${role === user.role ? " selected" : ""}>${escapeHtml(roleLabel(role))}</option>`).join("")}
              </select>`
            : `<span class="btn-ghost user-row-static">${user.manageable ? escapeHtml(roleLabel(user.role)) : "Verrouille"}</span>`
          }
          ${user.manageable
            ? `<button class="btn-danger" data-delete-user="${escapeHtml(user.username)}">Supprimer</button>`
            : ""
          }
        </div>
      </div>
    `).join("");

    container.querySelectorAll("[data-role-user]").forEach((select) => {
      select.addEventListener("change", () => updateUserRole(select.dataset.roleUser, select.value));
    });

    container.querySelectorAll("[data-delete-user]").forEach((btn) => {
      btn.addEventListener("click", () => deleteUser(btn.dataset.deleteUser));
    });
  }

  async function createUser() {
    if (!adminState.canManageUsers) {
      setFeedback("usersFeedback", "Acces de gestion requis.", "error");
      return;
    }

    const username = getEl("newUserUsername")?.value.trim() || "";
    const email = getEl("newUserEmail")?.value.trim() || "";
    const password = getEl("newUserPassword")?.value || "";
    const role = getEl("newUserRole")?.value || "user";

    if (!username) {
      setFeedback("usersFeedback", "Nom d'utilisateur requis.", "error");
      return;
    }
    if (!password) {
      setFeedback("usersFeedback", "Mot de passe requis.", "error");
      return;
    }

    setFeedback("usersFeedback", "Creation en cours...", "");

    try {
      await adminApi("/api/admin/users", {
        method: "POST",
        body: JSON.stringify({ username, email, password, role }),
      });
      setFeedback("usersFeedback", "Utilisateur cree.", "success");
      getEl("newUserUsername").value = "";
      getEl("newUserEmail").value = "";
      getEl("newUserPassword").value = "";
      getEl("newUserRole").value = "user";
      loadUsers();
    } catch (error) {
      setFeedback("usersFeedback", error.message, "error");
    }
  }

  async function updateUserRole(username, role) {
    try {
      await adminApi("/api/admin/users/role", {
        method: "POST",
        body: JSON.stringify({ username, role }),
      });
      setFeedback("usersFeedback", `Role de ${username} mis a jour.`, "success");
      loadUsers();
    } catch (error) {
      setFeedback("usersFeedback", error.message, "error");
      loadUsers();
    }
  }

  async function deleteUser(username) {
    if (!confirm(`Supprimer ${username} ?`)) return;

    try {
      await adminApi("/api/admin/users/delete", {
        method: "POST",
        body: JSON.stringify({ username }),
      });
      setFeedback("usersFeedback", `Utilisateur ${username} supprime.`, "success");
      loadUsers();
    } catch (error) {
      setFeedback("usersFeedback", error.message, "error");
    }
  }

  async function loadSessions() {
    const container = getEl("sessionsList");
    if (!container) return;
    container.innerHTML = '<div class="sessions-loading">Chargement...</div>';

    try {
      const payload = await adminApi("/api/sessions");
      renderSessions(payload.sessions || []);
    } catch (error) {
      container.innerHTML = `<div class="sessions-loading" style="color:var(--red)">${escapeHtml(error.message)}</div>`;
    }
  }

  function renderSessions(sessions) {
    const container = getEl("sessionsList");
    if (!container) return;

    if (!sessions.length) {
      container.innerHTML = '<div class="sessions-loading">Aucune session active.</div>';
      return;
    }

    container.innerHTML = sessions.map((session) => `
      <div class="session-row${session.current ? " current" : ""}">
        <div class="session-info">
          <div class="session-meta">
            <span class="session-ip">${escapeHtml(session.ip || "IP inconnue")}</span>
            ${session.current ? '<span class="session-current-badge">Session active</span>' : ""}
          </div>
          <div class="session-time">Cree : ${formatDate(session.created_at)}</div>
          <div class="session-token-preview">${escapeHtml((session.token_preview || "").slice(0, 12))}...</div>
        </div>
        <div>
          ${session.current
            ? '<button class="btn-ghost" disabled>Actuelle</button>'
            : `<button class="btn-danger" data-revoke-token="${escapeHtml(session.token)}">Revoquer</button>`
          }
        </div>
      </div>
    `).join("");

    container.querySelectorAll("[data-revoke-token]").forEach((btn) => {
      btn.addEventListener("click", () => revokeSession(btn.dataset.revokeToken));
    });
  }

  async function revokeSession(token) {
    if (!confirm("Revoquer cette session ?")) return;

    try {
      await adminApi("/api/sessions/revoke", {
        method: "POST",
        body: JSON.stringify({ token }),
      });
      loadSessions();
    } catch (error) {
      alert("Erreur : " + error.message);
    }
  }

  window.initAdmin = initAdmin;
})();
