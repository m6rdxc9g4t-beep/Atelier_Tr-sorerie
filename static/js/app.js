// Atelier Trésorerie — comportements communs et utilitaires partagés (window.AT).
(function () {
  "use strict";

  // ======================================================================= utilitaires

  const eurFormatter = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" });
  const dateFormatter = new Intl.DateTimeFormat("fr-FR", { day: "2-digit", month: "short", year: "numeric" });
  const monthFormatter = new Intl.DateTimeFormat("fr-FR", { month: "long", year: "numeric" });

  const AT = {
    PASTELS: ["#a5b4fc", "#6ee7b7", "#fcd34d", "#7dd3fc", "#c4b5fd", "#fda4af", "#f9a8d4", "#fdba74", "#86efac", "#cbd5e1"],

    /** Échappe une valeur avant de l'insérer dans du HTML. */
    esc(value) {
      return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
    },

    eur(cents, { signed = false } = {}) {
      const text = eurFormatter.format((cents || 0) / 100);
      return signed && cents > 0 ? `+${text}` : text;
    },

    /** Centimes -> valeur pour un champ de saisie (« 12,50 »). */
    toInput(cents) {
      return ((cents || 0) / 100).toFixed(2).replace(".", ",");
    },

    date(iso) {
      return iso ? dateFormatter.format(new Date(`${iso}T00:00:00`)) : "";
    },

    monthLabel(month) {
      const label = monthFormatter.format(new Date(`${month}-01T00:00:00`));
      return label.charAt(0).toUpperCase() + label.slice(1);
    },

    today() {
      const d = new Date();
      return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
    },

    shiftMonth(month, delta) {
      const [y, m] = month.split("-").map(Number);
      const d = new Date(y, m - 1 + delta, 1);
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    },

    amountClass(cents) {
      return cents > 0 ? "text-gain" : cents < 0 ? "text-loss" : "text-muted";
    },

    // ---------------------------------------------------------------- appels API

    /**
     * Appel JSON à l'API. Lève une erreur { message, fields, status } si la réponse n'est pas 2xx.
     * L'en-tête X-Requested-With est exigé par le serveur pour toute modification.
     */
    async api(method, url, body) {
      const options = { method, headers: { Accept: "application/json", "X-Requested-With": "fetch" } };
      if (body instanceof FormData) {
        options.body = body;
      } else if (body !== undefined) {
        options.headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(body);
      }
      let res;
      try {
        res = await fetch(url, options);
      } catch (e) {
        throw Object.assign(new Error("Serveur injoignable : l'application est-elle lancée ?"), { status: 0 });
      }
      if (res.status === 204) return null;
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw Object.assign(new Error(data.error || `Erreur ${res.status}`), { status: res.status, fields: data.fields || {} });
      }
      return data;
    },

    // ---------------------------------------------------------------- notifications

    toast(message, tone = "info") {
      let box = document.getElementById("toasts");
      if (!box) {
        box = document.createElement("div");
        box.id = "toasts";
        box.setAttribute("aria-live", "polite");
        document.body.appendChild(box);
      }
      const el = document.createElement("div");
      el.className = `toast ${tone === "error" ? "toast-error" : ""}`;
      el.textContent = message;
      box.appendChild(el);
      setTimeout(() => el.remove(), tone === "error" ? 6000 : 3500);
    },

    // ---------------------------------------------------------------- formulaires

    /** Affiche les erreurs de validation renvoyées par l'API sous chaque champ. */
    showErrors(form, err) {
      AT.clearErrors(form);
      const fields = (err && err.fields) || {};
      let shown = false;
      for (const [name, message] of Object.entries(fields)) {
        const input = form.querySelector(`[name="${name}"]`);
        if (!input) continue;
        input.setAttribute("aria-invalid", "true");
        const p = document.createElement("p");
        p.className = "field-error";
        p.textContent = message;
        (input.closest("[data-field]") || input.parentElement).appendChild(p);
        shown = true;
      }
      if (!shown || !Object.keys(fields).length) AT.toast(err.message, "error");
    },

    clearErrors(form) {
      form.querySelectorAll(".field-error").forEach((el) => el.remove());
      form.querySelectorAll("[aria-invalid]").forEach((el) => el.removeAttribute("aria-invalid"));
    },

    /** Boîte de confirmation accessible (remplace window.confirm). */
    confirm(message, { confirmLabel = "Confirmer", danger = true } = {}) {
      return new Promise((resolve) => {
        const dlg = document.createElement("dialog");
        dlg.className = "modal";
        dlg.innerHTML = `
          <div class="modal-body pt-6"><p class="font-semibold leading-relaxed">${AT.esc(message)}</p></div>
          <div class="modal-foot">
            <button type="button" class="btn btn-ghost" data-v="0">Annuler</button>
            <button type="button" class="btn ${danger ? "btn-danger" : "btn-primary"}" data-v="1">${AT.esc(confirmLabel)}</button>
          </div>`;
        document.body.appendChild(dlg);
        let result = false;
        dlg.addEventListener("click", (e) => {
          const btn = e.target.closest("[data-v]");
          if (btn) { result = btn.dataset.v === "1"; dlg.close(); }
        });
        dlg.addEventListener("close", () => { dlg.remove(); resolve(result); });
        dlg.showModal();
      });
    },

    /** Ferme un <dialog> en cliquant sur le fond. */
    closeOnBackdrop(dialog) {
      dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.close(); });
    },

    /** Remplit un <select> à partir d'une liste d'objets. */
    fillSelect(select, items, { value = "id", label = "name", placeholder = null, groupBy = null } = {}) {
      const current = select.value;
      const opts = [];
      if (placeholder !== null) opts.push(`<option value="">${AT.esc(placeholder)}</option>`);
      if (groupBy) {
        const groups = new Map();
        items.forEach((it) => {
          const key = groupBy(it);
          if (!groups.has(key)) groups.set(key, []);
          groups.get(key).push(it);
        });
        for (const [group, list] of groups) {
          opts.push(`<optgroup label="${AT.esc(group)}">`);
          list.forEach((it) => opts.push(`<option value="${AT.esc(it[value])}">${AT.esc(it[label])}</option>`));
          opts.push("</optgroup>");
        }
      } else {
        items.forEach((it) => opts.push(`<option value="${AT.esc(it[value])}">${AT.esc(it[label])}</option>`));
      }
      select.innerHTML = opts.join("");
      if ([...select.options].some((o) => o.value === current)) select.value = current;
    },

    KIND_LABELS: { revenu: "Revenus", depense: "Dépenses", transfert: "Virements" },

    /**
     * Markdown minimal et sûr pour les réponses de l'IA : le texte est échappé AVANT
     * toute mise en forme, aucune balise venant du modèle n'est donc interprétée.
     */
    markdown(text) {
      const inline = (s) => AT.esc(s)
        .replace(/`([^`]+)`/g, '<code class="rounded bg-raised px-1">$1</code>')
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
        .replace(/(^|[\s(])\*([^*\s][^*]*)\*(?=[\s.,;:!?)]|$)/g, "$1<em>$2</em>")
        .replace(/(\d) ([%€])/g, "$1&nbsp;$2"); // « 46,6 % » ne se coupe pas en fin de ligne
      const out = [];
      let list = null;
      const close = () => { if (list) { out.push(`</${list}>`); list = null; } };
      for (const raw of String(text || "").split(/\r?\n/)) {
        const line = raw.trimEnd();
        let m;
        if (!line.trim()) { close(); continue; }
        if ((m = line.match(/^\s*#{1,6}\s+(.*)$/))) { close(); out.push(`<p class="mt-3 font-bold">${inline(m[1])}</p>`); continue; }
        if ((m = line.match(/^\s*[-*•]\s+(.*)$/))) {
          if (list !== "ul") { close(); out.push('<ul class="my-1.5 list-disc space-y-1 pl-5">'); list = "ul"; }
          out.push(`<li>${inline(m[1])}</li>`); continue;
        }
        if ((m = line.match(/^\s*\d+[.)]\s+(.*)$/))) {
          if (list !== "ol") { close(); out.push('<ol class="my-1.5 list-decimal space-y-1 pl-5">'); list = "ol"; }
          out.push(`<li>${inline(m[1])}</li>`); continue;
        }
        close();
        out.push(`<p class="my-1.5">${inline(line)}</p>`);
      }
      close();
      return out.join("");
    },
  };
  window.AT = AT;

  // ======================================================================= mise en page

  // ---------- Thème clair / sombre ----------
  const root = document.documentElement;
  document.getElementById("theme-toggle")?.addEventListener("click", () => {
    const dark = root.classList.toggle("dark");
    try { localStorage.setItem("theme", dark ? "dark" : "light"); } catch (e) { /* stockage indisponible */ }
    document.dispatchEvent(new CustomEvent("themechange", { detail: { dark } })); // pour Chart.js (étape 3)
  });

  // ---------- Sidebar mobile ----------
  const sidebar = document.getElementById("sidebar");
  const backdrop = document.getElementById("backdrop");
  const setMenu = (open) => {
    sidebar?.classList.toggle("-translate-x-full", !open);
    backdrop?.classList.toggle("hidden", !open);
  };
  document.getElementById("menu-toggle")?.addEventListener("click", () => setMenu(true));
  backdrop?.addEventListener("click", () => setMenu(false));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") setMenu(false); });

  // ---------- État de l'assistant IA (barre latérale) ----------
  AT.aiState = (ai) => {
    if (!ai) return { tone: "muted", text: "État indisponible" };
    if (ai.ready) return { tone: "gain", text: `${ai.provider === "ollama" ? ai.model : ai.label} prêt` };
    if (ai.provider === "ollama" && ai.models && ai.models.length) return { tone: "warn", text: `Modèle ${ai.model} absent` };
    return { tone: ai.provider === "ollama" ? "loss" : "warn", text: ai.provider === "ollama" ? "Ollama hors ligne" : `${ai.label} à configurer` };
  };

  async function refreshHealth() {
    const dot = document.getElementById("ai-dot");
    const label = document.getElementById("ai-label");
    const privacy = document.getElementById("ai-privacy");
    try {
      const { ai } = await AT.api("GET", "/api/health");
      const { tone, text } = AT.aiState(ai);
      if (dot) dot.className = `h-2.5 w-2.5 rounded-full bg-${tone}`;
      if (label) { label.textContent = text; label.title = ai.error || ""; }
      if (privacy) privacy.textContent = ai.local ? "100 % local, aucune donnée envoyée" : "Claude : résumé chiffré envoyé";
      document.dispatchEvent(new CustomEvent("aistatus", { detail: ai }));
    } catch (err) {
      if (label) label.textContent = "État indisponible";
    }
  }
  AT.refreshHealth = refreshHealth;
  refreshHealth();
})();

// ---------- Quitter (application Mac lancée par double-clic) ----------
document.getElementById("quit-app")?.addEventListener("click", async () => {
  if (!(await AT.confirm("Quitter Atelier Trésorerie ? Le serveur local sera arrêté.", { confirmLabel: "Quitter", danger: false }))) return;
  try {
    await AT.api("POST", "/api/system/shutdown");
  } catch (e) { /* le serveur s'arrête : une erreur réseau est attendue */ }
  document.body.innerHTML = `
    <main style="min-height:100vh;display:grid;place-items:center;text-align:center;padding:2rem">
      <div>
        <p style="font-size:1.25rem;font-weight:800">Atelier Trésorerie est fermé.</p>
        <p style="margin-top:.5rem;opacity:.7">Vous pouvez fermer cet onglet. Double-cliquez sur l'application pour la relancer.</p>
      </div>
    </main>`;
});
