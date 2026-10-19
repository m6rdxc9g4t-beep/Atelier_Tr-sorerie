// Page Paramètres : moteur d'IA et données
(function () {
  "use strict";
  const { esc, api, toast } = AT;
  const $ = (id) => document.getElementById(id);
  const form = $("ai-form");
  const F = form.elements;
  let saved = null;

  function syncVisibility() {
    const claude = F.ai_provider.value === "claude";
    $("ollama-fields").hidden = claude;
    $("claude-fields").hidden = !claude;
    $("cli-fields").hidden = F.claude_mode.value !== "cli";
    $("api-fields").hidden = F.claude_mode.value !== "api";
  }

  function renderKeyState() {
    const el = $("api-key-state");
    if (saved.anthropic_api_key_set) {
      el.innerHTML = `Clé enregistrée : <span class="num">${esc(saved.anthropic_api_key_hint)}</span> ·
        <button type="button" id="api-key-delete" class="font-semibold text-loss hover:underline">Supprimer</button>`;
      F.anthropic_api_key.placeholder = "Laisser vide pour conserver la clé";
    } else {
      el.textContent = "Aucune clé enregistrée.";
      F.anthropic_api_key.placeholder = "sk-ant-…";
    }
  }

  function fill(s) {
    saved = s;
    F.ai_provider.value = s.ai_provider;
    F.claude_mode.value = s.claude_mode;
    F.ollama_model.value = s.ollama_model;
    F.claude_cli_model.value = s.claude_cli_model;
    F.claude_cli_path.value = s.claude_cli_path;
    F.claude_api_model.value = s.claude_api_model;
    F.anthropic_api_key.value = "";
    $("ollama-url").textContent = s.ollama_url;
    $("db-path").textContent = s.database_path;
    renderKeyState();
    syncVisibility();
  }

  async function loadOllamaModels() {
    try {
      const st = await api("GET", "/api/ai/ollama");
      $("ollama-models").innerHTML = st.models.map((m) => `<option value="${esc(m)}">`).join("");
      $("ollama-models-hint").textContent = st.available
        ? (st.models.length ? `Installés : ${st.models.join(", ")}` : "Aucun modèle installé dans Ollama.")
        : "Ollama ne répond pas : lancez l'application Ollama.";
    } catch (err) {
      $("ollama-models-hint").textContent = "";
    }
  }

  async function loadStats() {
    try {
      const { database: db } = await api("GET", "/api/health");
      const stats = [["Comptes", db.accounts], ["Opérations", db.transactions], ["Catégories", db.categories], ["Budgets", db.budgets]];
      $("db-stats").innerHTML = stats.map(([k, v]) =>
        `<div class="rounded-xl bg-raised/60 p-3"><dt class="text-xs text-muted">${k}</dt><dd class="num mt-1 text-lg font-bold">${v ?? "—"}</dd></div>`).join("");
    } catch (err) { /* facultatif */ }
  }

  async function save({ silent = false } = {}) {
    if (F.ai_provider.value === "claude" && saved.ai_provider !== "claude") {
      const ok = await AT.confirm(
        "Avec Claude, vos questions et un résumé chiffré de vos finances seront envoyés à Anthropic à chaque échange. Activer Claude ?",
        { confirmLabel: "Activer Claude", danger: false });
      if (!ok) { F.ai_provider.value = saved.ai_provider; syncVisibility(); return null; }
    }
    const body = {
      ai_provider: F.ai_provider.value,
      claude_mode: F.claude_mode.value,
      ollama_model: F.ollama_model.value,
      claude_cli_model: F.claude_cli_model.value,
      claude_cli_path: F.claude_cli_path.value,
      claude_api_model: F.claude_api_model.value,
    };
    if (F.anthropic_api_key.value.trim()) body.anthropic_api_key = F.anthropic_api_key.value.trim();
    try {
      fill(await api("PATCH", "/api/settings", body));
      AT.clearErrors(form);
      if (!silent) toast("Paramètres enregistrés.");
      AT.refreshHealth?.();
      return saved;
    } catch (err) {
      AT.showErrors(form, err);
      return null;
    }
  }

  async function test() {
    if (!(await save({ silent: true }))) return;
    const out = $("test-result");
    out.innerHTML = '<span class="h-2.5 w-2.5 animate-pulse rounded-full bg-muted"></span><span class="text-muted">Test en cours…</span>';
    try {
      const st = await api("GET", "/api/ai/status?deep=1");
      const detail = st.ready
        ? `${esc(st.provider === "ollama" ? `Ollama · ${st.model}` : `${st.label} · ${st.model}`)} fonctionne${st.cli_path ? ` (${esc(st.cli_path)})` : ""}.`
        : esc(st.error || "Moteur indisponible.");
      out.innerHTML = `<span class="h-2.5 w-2.5 shrink-0 rounded-full bg-${st.ready ? "gain" : "loss"}"></span><span>${detail}</span>`;
    } catch (err) {
      out.innerHTML = `<span class="h-2.5 w-2.5 shrink-0 rounded-full bg-loss"></span><span>${esc(err.message)}</span>`;
    }
  }

  form.addEventListener("change", (e) => {
    if (["ai_provider", "claude_mode"].includes(e.target.name)) syncVisibility();
    $("test-result").innerHTML = "";
  });
  form.addEventListener("submit", (e) => { e.preventDefault(); save(); });
  $("btn-test").addEventListener("click", test);
  $("api-key-state").addEventListener("click", async (e) => {
    if (!e.target.closest("#api-key-delete")) return;
    if (!(await AT.confirm("Supprimer la clé API Claude enregistrée sur ce Mac ?", { confirmLabel: "Supprimer" }))) return;
    try {
      fill(await api("PATCH", "/api/settings", { anthropic_api_key: null }));
      toast("Clé supprimée.");
    } catch (err) {
      toast(err.message, "error");
    }
  });

  (async () => {
    try {
      fill(await api("GET", "/api/settings"));
    } catch (err) {
      toast(err.message, "error");
    }
    loadOllamaModels();
    loadStats();
  })();
})();
