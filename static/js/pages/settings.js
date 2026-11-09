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
        <button type="button" id="api-key-delete" class="font-medium text-danger hover:underline">Supprimer</button>`;
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
        `<div class="card kpi-card px-3 py-2.5"><dt class="text-xs text-muted">${k}</dt><dd class="num mt-0.5 text-lg font-semibold">${v ?? "—"}</dd></div>`).join("");
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

  // ------------------------------------------------------------ exemples de la suite
  const APPS = { convert: "Convert", tab: "Tab", viz: "Viz", tresorerie: "Trésorerie", nexus: "Nexus", projets: "Projets", wiki: "Wiki" };
  const STORAGE_KEY = "atelier:exemple"; // histoire choisie, commune aux apps de la même origine
  let histoires = [];

  function remembered() {
    try { return localStorage.getItem(STORAGE_KEY); } catch { return null; }
  }
  function remember(id) {
    try { localStorage.setItem(STORAGE_KEY, id); } catch { /* stockage indisponible : le choix n'est pas gardé */ }
  }

  function renderExemple() {
    const h = histoires.find((x) => x.id === $("exemple-select").value) || histoires[0];
    if (!h) return;
    const i = h.parcours.findIndex((e) => e.app === "tresorerie");
    const current = h.parcours[i];
    const next = h.parcours[i + 1];
    $("exemple-titre").textContent = h.titre;
    $("exemple-sous-titre").textContent = `— ${h.sous_titre}`;
    $("exemple-resume").textContent = h.resume;
    $("exemple-parcours").innerHTML = h.parcours.map((e, n) => `
      <li class="chip${e.app === "tresorerie" ? " bg-selected text-brand" : ""}" title="${esc(e.texte)}"${e.app === "tresorerie" ? ' aria-current="step"' : ""}>
        <span class="num text-faint">${n + 1}</span> ${esc(APPS[e.app] || e.app)}
      </li>`).join("");
    $("exemple-etape").textContent = current ? current.texte : "";
    $("exemple-contenu").textContent = `Compte « ${h.compte} », ${h.operations} opérations d'août à octobre 2026, ${h.budgets} budgets pour ${AT.monthLabel(h.budgets_mois).toLowerCase()}.`;
    $("exemple-suite").innerHTML = next
      ? `<span class="font-medium text-ink">Ensuite, ${esc(APPS[next.app] || next.app)}</span> — ${esc(next.texte)}`
      : "";
    $("exemple-charger").hidden = h.charge;
    $("exemple-retirer").hidden = !h.charge;
    $("exemple-ouvrir").hidden = !h.charge;
    $("exemple-budgets").hidden = !h.charge;
    if (h.charge) {
      $("exemple-ouvrir").href = `/transactions?account_id=${encodeURIComponent(h.account_id)}`;
      $("exemple-budgets").href = `/budgets?month=${encodeURIComponent(h.budgets_mois)}`;
    }
  }

  async function loadExemples() {
    try {
      histoires = (await api("GET", "/api/exemples-suite")).items;
    } catch {
      histoires = [];
    }
    $("exemples").hidden = !histoires.length;
    if (!histoires.length) return;
    const keep = $("exemple-select").value || remembered();
    $("exemple-select").innerHTML = histoires
      .map((h) => `<option value="${esc(h.id)}">${esc(h.secteur)} · ${esc(h.titre)}</option>`).join("");
    $("exemple-select").value = histoires.some((h) => h.id === keep) ? keep : histoires[0].id;
    renderExemple();
  }

  $("exemple-select").addEventListener("change", () => { remember($("exemple-select").value); renderExemple(); });
  $("exemple-charger").addEventListener("click", async () => {
    const id = $("exemple-select").value;
    $("exemple-charger").disabled = true;
    try {
      const res = await api("POST", `/api/exemples-suite/${encodeURIComponent(id)}`);
      toast(res.budgets_gardes && res.budgets_gardes.length
        ? `Exemple chargé. Budgets déjà présents, laissés tels quels : ${res.budgets_gardes.join(", ")}.`
        : "Exemple chargé.");
      await loadExemples();
      loadStats();
    } catch (err) {
      toast(err.message, "error");
    } finally {
      $("exemple-charger").disabled = false;
    }
  });
  $("exemple-retirer").addEventListener("click", async () => {
    const h = histoires.find((x) => x.id === $("exemple-select").value);
    if (!h || !(await AT.confirm(`Retirer l'exemple « ${h.titre} » : son compte, ses opérations et ses budgets ?`, { confirmLabel: "Retirer", danger: true }))) return;
    try {
      const res = await api("DELETE", `/api/exemples-suite/${encodeURIComponent(h.id)}`);
      toast(res.categories_gardees && res.categories_gardees.length
        ? `Exemple retiré. Catégories gardées car utilisées ailleurs : ${res.categories_gardees.join(", ")}.`
        : "Exemple retiré.");
      await loadExemples();
      loadStats();
    } catch (err) {
      toast(err.message, "error");
    }
  });

  (async () => {
    loadExemples();
    try {
      fill(await api("GET", "/api/settings"));
    } catch (err) {
      toast(err.message, "error");
    }
    loadOllamaModels();
    loadStats();
  })();
})();
