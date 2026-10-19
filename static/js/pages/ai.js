// Page Assistant IA : conversation, données transmises, catégorisation assistée
(function () {
  "use strict";
  const { esc, eur, api, toast } = AT;
  const $ = (id) => document.getElementById(id);

  const thread = $("thread");
  const form = $("composer");
  const input = $("question");
  const state = { items: [], suggestions: [], engine: null, busy: false, categories: [] };
  const timeFormat = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" });

  // ======================================================================= moteur

  function renderEngine(ai) {
    state.engine = ai;
    const { tone, text } = AT.aiState(ai);
    $("engine-dot").className = `h-2.5 w-2.5 shrink-0 rounded-full bg-${tone}`;
    $("engine-label").textContent = ai.provider === "ollama" ? `Ollama · ${ai.model}` : `${ai.label} · ${ai.model}`;
    $("engine-privacy").textContent = ai.ready ? (ai.local ? "Local : rien ne quitte votre Mac" : "Résumé chiffré envoyé à Anthropic")
      : (ai.error || text);
    $("engine-privacy").className = `truncate text-xs ${ai.ready ? "text-muted" : "text-warn"}`;
    $("privacy-detail").innerHTML = ai.local
      ? `<p><strong class="text-ink">Ollama tourne sur votre Mac.</strong> Vos questions et vos données ne quittent pas l'ordinateur.</p>
         <p>L'IA reçoit un résumé détaillé : comptes, positions, plus grosses dépenses du mois.</p>`
      : `<p><strong class="text-ink">Claude est un service en ligne d'Anthropic.</strong> Vos questions et un résumé chiffré y sont envoyés.</p>
         <p>Ce résumé ne contient que des totaux par mois, catégorie, type de compte et type d'actif : aucun libellé d'opération, nom de compte ou de position.</p>
         <p>La catégorisation automatique, elle, envoie les libellés concernés après confirmation.</p>`;
  }

  // ======================================================================= conversation

  function bubble(m) {
    if (m.role === "user") {
      return `<div class="flex justify-end"><div class="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-brand/15 px-4 py-2.5">${esc(m.content)}</div></div>`;
    }
    if (m.role === "error") {
      return `<div class="flex"><div class="max-w-[85%] rounded-2xl rounded-bl-md border border-loss/40 px-4 py-3 text-sm">
        <p class="font-semibold text-loss">Pas de réponse</p><p class="mt-1 text-muted">${esc(m.content)}</p>
        <button type="button" class="mt-2 text-sm font-semibold text-brand hover:underline" data-retry="${esc(m.question)}">Réessayer</button>
      </div></div>`;
    }
    const engine = m.provider === "claude" ? "Claude" : "Ollama";
    const when = m.created_at ? timeFormat.format(new Date(`${m.created_at.replace(" ", "T")}Z`)) : "";
    return `<div class="flex"><div class="max-w-[90%]">
      <div class="rounded-2xl rounded-bl-md bg-raised/70 px-4 py-2.5 leading-relaxed">${AT.markdown(m.content)}</div>
      <p class="mt-1 pl-1 text-xs text-muted">${esc(engine)}${m.model ? ` · ${esc(m.model)}` : ""}${when ? ` · ${when}` : ""}</p>
    </div></div>`;
  }

  function renderThread({ pending = null } = {}) {
    if (!state.items.length && !pending) {
      thread.innerHTML = `
        <div class="mx-auto flex h-full max-w-lg flex-col items-center justify-center text-center">
          <div class="grid h-12 w-12 place-items-center rounded-2xl bg-lilac/15 text-lilac">
            <svg class="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9zM19 15l.8 2.2 2.2.8-2.2.8L19 21l-.8-2.2-2.2-.8 2.2-.8z"/></svg>
          </div>
          <p class="mt-4 text-lg font-bold">Posez une question sur vos finances</p>
          <p class="mt-1 text-sm text-muted">L'assistant s'appuie sur vos comptes, budgets et placements.</p>
          <div class="mt-5 flex flex-wrap justify-center gap-2">
            ${state.suggestions.map((s) => `<button type="button" class="btn btn-ghost btn-sm h-auto whitespace-normal py-1.5 text-left font-semibold" data-suggest="${esc(s)}">${esc(s)}</button>`).join("")}
          </div>
        </div>`;
      return;
    }
    // Séparateur quand le moteur change : chaque moteur ne voit que ses propres échanges
    let html = state.items.map((m, i) => {
      const prev = state.items[i - 1];
      const switched = m.role === "user" && m.provider && prev?.provider && prev.provider !== m.provider;
      const sep = switched ? `<p class="py-1 text-center text-xs text-muted">— Passage à ${m.provider === "claude" ? "Claude" : "Ollama"} :
        les échanges précédents ne lui sont pas transmis —</p>` : "";
      return sep + bubble(m);
    }).join("");
    if (pending) {
      html += bubble({ role: "user", content: pending });
      html += `<div class="flex" id="typing"><div class="rounded-2xl rounded-bl-md bg-raised/70 px-4 py-3 text-sm text-muted">
        <span class="inline-flex gap-1 align-middle"><span class="h-1.5 w-1.5 animate-bounce rounded-full bg-muted"></span>
        <span class="h-1.5 w-1.5 animate-bounce rounded-full bg-muted [animation-delay:.15s]"></span>
        <span class="h-1.5 w-1.5 animate-bounce rounded-full bg-muted [animation-delay:.3s]"></span></span>
        <span class="ml-2" id="typing-text">L'IA réfléchit…</span></div></div>`;
    }
    thread.innerHTML = html;
    thread.scrollTop = thread.scrollHeight;
  }

  async function send(question) {
    question = question.trim();
    if (!question || state.busy) return;
    state.busy = true;
    $("send").disabled = true;
    input.value = "";
    autosize();
    renderThread({ pending: question });
    const started = Date.now();
    const timer = setInterval(() => {
      const s = Math.round((Date.now() - started) / 1000);
      const el = $("typing-text");
      if (el && s >= 5) el.textContent = `L'IA réfléchit… ${s} s${state.engine?.local && s >= 15 ? " (un modèle local peut prendre une minute)" : ""}`;
    }, 1000);
    try {
      const res = await api("POST", "/api/ai/ask", { question });
      state.items.push({ role: "user", content: res.question, provider: res.answer.provider }, res.answer);
      renderThread();
    } catch (err) {
      state.items.push({ role: "user", content: question }, { role: "error", content: err.message, question });
      renderThread();
      state.items.splice(-2, 2); // l'échec n'est pas conservé côté serveur
    } finally {
      clearInterval(timer);
      state.busy = false;
      $("send").disabled = false;
      input.focus();
    }
  }

  function autosize() {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
  }

  // ======================================================================= données transmises

  async function showContext() {
    try {
      const ctx = await api("GET", "/api/ai/context");
      $("context-intro").textContent = ctx.local
        ? `Avec ${ctx.label}, ce texte reste sur votre Mac. Il accompagne chaque question.`
        : `Avec ${ctx.label}, ce texte est envoyé à Anthropic avec chaque question. Il ne contient que des montants agrégés.`;
      $("context-text").textContent = ctx.text;
      $("context-dialog").showModal();
    } catch (err) {
      toast(err.message, "error");
    }
  }

  // ======================================================================= catégorisation

  function renderUncategorized(n) {
    $("uncat-text").innerHTML = n
      ? `<strong class="num text-ink">${n}</strong> opération${n > 1 ? "s" : ""} sans catégorie.`
      : "Toutes vos opérations sont catégorisées.";
    $("btn-categorize").disabled = !n;
  }

  async function categorize() {
    if (!state.engine?.local) {
      const ok = await AT.confirm("Avec Claude, les libellés, dates et montants des opérations non catégorisées (40 au maximum) seront envoyés à Anthropic. Continuer ?",
        { confirmLabel: "Envoyer à Claude", danger: false });
      if (!ok) return;
    }
    const btn = $("btn-categorize");
    const label = btn.innerHTML;
    btn.disabled = true;
    btn.textContent = "Analyse en cours…";
    try {
      if (!state.categories.length) state.categories = (await api("GET", "/api/categories")).items.filter((c) => c.kind !== "transfert");
      const res = await api("POST", "/api/ai/categorize", {});
      if (!res.items.length) {
        toast(res.unmatched ? "L'IA n'a pas trouvé de catégorie sûre pour ces opérations." : "Rien à catégoriser.");
        return;
      }
      $("cat-summary").textContent = `${res.items.length} proposition(s)` +
        (res.unmatched ? `, ${res.unmatched} opération(s) laissée(s) sans catégorie faute de certitude` : "") +
        ". Corrigez si besoin, puis appliquez.";
      const byKind = (c) => AT.KIND_LABELS[c.kind];
      $("cat-rows").innerHTML = res.items.map((t) => `
        <tr data-id="${t.id}">
          <td><input type="checkbox" class="checkbox" checked aria-label="Appliquer pour ${esc(t.label)}"></td>
          <td class="max-w-[18rem]"><p class="truncate font-semibold">${esc(t.label)}</p><p class="text-xs text-muted">${AT.date(t.date)} · ${esc(t.account_name)}</p></td>
          <td class="num whitespace-nowrap text-right font-semibold ${AT.amountClass(t.amount_cents)}">${eur(t.amount_cents, { signed: true })}</td>
          <td><select class="input h-9 text-sm" aria-label="Catégorie">${""}</select></td>
        </tr>`).join("");
      $("cat-rows").querySelectorAll("tr").forEach((tr, i) => {
        const select = tr.querySelector("select");
        AT.fillSelect(select, state.categories, { groupBy: byKind });
        select.value = String(res.items[i].category_id);
      });
      $("cat-all").checked = true;
      $("cat-dialog").showModal();
    } catch (err) {
      toast(err.message, "error");
    } finally {
      btn.innerHTML = label;
      btn.disabled = false;
    }
  }

  $("cat-all").addEventListener("change", (e) => {
    $("cat-rows").querySelectorAll('input[type="checkbox"]').forEach((c) => { c.checked = e.target.checked; });
  });

  $("cat-apply").addEventListener("click", async () => {
    const items = [...$("cat-rows").querySelectorAll("tr")]
      .filter((tr) => tr.querySelector('input[type="checkbox"]').checked)
      .map((tr) => ({ id: Number(tr.dataset.id), category_id: Number(tr.querySelector("select").value) }));
    if (!items.length) { $("cat-dialog").close(); return; }
    try {
      const res = await api("POST", "/api/ai/categorize/apply", { items });
      $("cat-dialog").close();
      toast(`${res.applied} opération(s) catégorisée(s).`);
      renderUncategorized(res.remaining);
    } catch (err) {
      toast(err.message, "error");
    }
  });

  // ======================================================================= événements

  form.addEventListener("submit", (e) => { e.preventDefault(); send(input.value); });
  input.addEventListener("input", autosize);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(input.value); }
  });
  thread.addEventListener("click", (e) => {
    const s = e.target.closest("[data-suggest]");
    if (s) send(s.dataset.suggest);
    const r = e.target.closest("[data-retry]");
    if (r) send(r.dataset.retry);
  });
  $("btn-context").addEventListener("click", showContext);
  $("btn-clear").addEventListener("click", async () => {
    if (!state.items.length) return;
    if (!(await AT.confirm("Effacer toute la conversation ?", { confirmLabel: "Effacer" }))) return;
    try {
      await api("DELETE", "/api/ai/messages");
      state.items = [];
      renderThread();
    } catch (err) {
      toast(err.message, "error");
    }
  });
  $("btn-categorize").addEventListener("click", categorize);
  ["context-dialog", "cat-dialog"].forEach((id) => {
    const d = $(id);
    AT.closeOnBackdrop(d);
    d.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => d.close()));
  });
  // L'état du moteur arrive avec la vérification de la barre latérale (une seule requête)
  document.addEventListener("aistatus", (e) => renderEngine(e.detail));

  (async () => {
    try {
      const data = await api("GET", "/api/ai/messages");
      state.items = data.items;
      state.suggestions = data.suggestions;
      renderUncategorized(data.uncategorized);
      renderThread();
      input.focus();
    } catch (err) {
      toast(err.message, "error");
    }
  })();
})();
