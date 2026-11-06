// Page Transactions : filtres, tableau paginé, saisie, actions groupées, import CSV/Excel
(function () {
  "use strict";
  const { esc, eur, api, toast } = AT;

  const STATUS = {
    valide: ["Validée", ""],
    en_attente: ["En attente", "badge-warn"],
    rapproche: ["Rapprochée", "badge-gain"],
  };

  const $ = (id) => document.getElementById(id);
  const filtersForm = $("filters");
  const rowsEl = $("rows");
  const emptyEl = $("empty");

  const state = {
    filters: {},
    page: 1,
    sort: "date",
    order: "desc",
    data: null,
    selected: new Set(),
    accounts: [],
    categories: [],
  };

  // ======================================================================= données de référence

  async function loadReferences() {
    const [acc, cat] = await Promise.all([api("GET", "/api/accounts?archived=1"), api("GET", "/api/categories")]);
    state.accounts = acc.items;
    state.categories = cat.items;
    const byKind = (c) => AT.KIND_LABELS[c.kind] || c.kind;

    AT.fillSelect($("f-account"), state.accounts, { placeholder: "Tous les comptes" });
    AT.fillSelect($("f-category"), state.categories, { placeholder: "Toutes les catégories", groupBy: byKind });
    $("f-category").insertAdjacentHTML("beforeend", '<option value="none">— Non catégorisées</option>');
    AT.fillSelect($("tx-account"), state.accounts.filter((a) => !a.archived));
    AT.fillSelect($("tx-category"), state.categories, { placeholder: "Automatique / aucune", groupBy: byKind });
    AT.fillSelect($("bulk-category"), state.categories, { placeholder: "Retirer la catégorie", groupBy: byKind });
    AT.fillSelect($("imp-account"), state.accounts.filter((a) => !a.archived));
  }

  // ======================================================================= filtres <-> URL

  function readUrl() {
    const params = new URLSearchParams(location.search);
    for (const el of filtersForm.elements) {
      if (el.name && params.has(el.name)) el.value = params.get(el.name);
    }
    state.page = Math.max(1, Number(params.get("page")) || 1);
    state.sort = params.get("sort") || "date";
    state.order = params.get("order") || "desc";
  }

  function syncUrl() {
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(state.filters)) if (v) params.set(k, v);
    if (state.page > 1) params.set("page", state.page);
    if (state.sort !== "date") params.set("sort", state.sort);
    if (state.order !== "desc") params.set("order", state.order);
    const qs = params.toString();
    history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
  }

  function collectFilters() {
    state.filters = Object.fromEntries([...new FormData(filtersForm)].filter(([, v]) => v !== ""));
  }

  // ======================================================================= liste

  function categoryBadge(t) {
    if (!t.category_id) return '<span class="badge text-muted">Non catégorisée</span>';
    return `<span class="badge"><span class="dot" style="background:${esc(t.category_color)}"></span>${esc(t.category_name)}</span>`;
  }

  function rowHtml(t) {
    const [statusLabel, statusClass] = STATUS[t.status] || [t.status, ""];
    const transfer = t.transfer_group
      ? '<span class="badge ml-2 align-middle" title="Virement entre comptes">⇄</span>' : "";
    return `
      <tr class="cursor-pointer ${state.selected.has(t.id) ? "is-selected" : ""}" data-id="${t.id}">
        <td><input type="checkbox" class="checkbox" data-select="${t.id}" ${state.selected.has(t.id) ? "checked" : ""}
             aria-label="Sélectionner ${esc(t.label)}"></td>
        <td class="num hidden whitespace-nowrap text-muted sm:table-cell">${AT.date(t.date)}</td>
        <td class="max-w-[13rem] sm:max-w-[22rem]">
          <p class="truncate font-semibold">${esc(t.label)}${transfer}</p>
          <p class="num text-xs text-muted sm:hidden">${AT.date(t.date)}</p>
          ${t.notes ? `<p class="truncate text-xs text-muted">${esc(t.notes)}</p>` : ""}
        </td>
        <td class="hidden sm:table-cell">${categoryBadge(t)}</td>
        <td class="hidden whitespace-nowrap text-muted md:table-cell">
          <span class="mr-1.5 inline-block h-2 w-2 rounded-full" style="background:${esc(t.account_color || "#a5b4fc")}"></span>${esc(t.account_name)}
        </td>
        <td class="hidden lg:table-cell"><span class="badge ${statusClass}">${statusLabel}</span></td>
        <td class="num whitespace-nowrap text-right font-bold ${AT.amountClass(t.amount_cents)}">${eur(t.amount_cents, { signed: true })}</td>
      </tr>`;
  }

  function renderSummary(d) {
    $("summary").innerHTML = `
      <span><strong class="text-ink">${d.total}</strong> opération${d.total > 1 ? "s" : ""}</span>
      <span>Entrées <strong class="num text-gain">${eur(d.income_cents, { signed: true })}</strong></span>
      <span>Sorties <strong class="num text-loss">${eur(d.expense_cents)}</strong></span>
      <span>Solde net <strong class="num text-ink">${eur(d.net_cents, { signed: true })}</strong></span>
      ${state.filters.import_batch_id ? `<span class="chip">Opérations d'un import
        <a class="ml-1 font-semibold text-brand hover:underline" href="/imports?report=${encodeURIComponent(state.filters.import_batch_id)}">voir le rapport</a></span>` : ""}`;
  }

  function renderBulk() {
    const n = state.selected.size;
    $("bulk-bar").classList.toggle("hidden", n === 0);
    $("bulk-bar").classList.toggle("flex", n > 0);
    $("bulk-count").textContent = `${n} sélectionnée${n > 1 ? "s" : ""}`;
    const ids = (state.data?.items || []).map((t) => t.id);
    const all = $("select-all");
    all.checked = ids.length > 0 && ids.every((id) => state.selected.has(id));
    all.indeterminate = !all.checked && ids.some((id) => state.selected.has(id));
  }

  function render() {
    const d = state.data;
    renderSummary(d);
    rowsEl.innerHTML = d.items.map(rowHtml).join("");
    const hasFilters = Object.keys(state.filters).length > 0;
    emptyEl.classList.toggle("hidden", d.items.length > 0);
    emptyEl.innerHTML = hasFilters
      ? "Aucune opération ne correspond à ces filtres."
      : 'Aucune opération pour le moment. <button class="font-semibold text-brand hover:underline" data-new>Ajoutez-en une</button> ou importez un relevé.';
    $("page-info").textContent = d.total ? `Page ${d.page} sur ${d.pages}` : "";
    $("page-prev").disabled = d.page <= 1;
    $("page-next").disabled = d.page >= d.pages;
    document.querySelectorAll("[data-sort]").forEach((b) => {
      const active = b.dataset.sort === state.sort;
      b.textContent = b.textContent.replace(/ [↑↓]$/, "") + (active ? (state.order === "asc" ? " ↑" : " ↓") : "");
      b.classList.toggle("text-ink", active);
    });
    renderBulk();
  }

  async function load() {
    collectFilters();
    syncUrl();
    const params = new URLSearchParams({ ...state.filters, page: state.page, sort: state.sort, order: state.order });
    rowsEl.innerHTML = '<tr><td colspan="7"><div class="skeleton h-6"></div></td></tr>'.repeat(4);
    try {
      state.data = await api("GET", `/api/transactions?${params}`);
      if (state.page > state.data.pages) { state.page = state.data.pages; return load(); }
      render();
    } catch (err) {
      rowsEl.innerHTML = "";
      emptyEl.classList.remove("hidden");
      emptyEl.textContent = err.message;
    }
  }

  // ======================================================================= saisie / édition

  const txDialog = $("tx-dialog");
  const txForm = $("tx-form");
  const F = txForm.elements;
  let editing = null;
  let ruleSuggestion = null;

  function toggleRuleRow() {
    const show = !!(editing && ruleSuggestion && ruleSuggestion.pattern && !editing.transfer_group && F.category_id.value);
    $("tx-rule-row").classList.toggle("hidden", !show);
    $("tx-rule-row").classList.toggle("flex", show);
  }

  async function loadRuleSuggestion(t) {
    ruleSuggestion = null;
    $("tx-rule").checked = false;
    toggleRuleRow();
    if (!t || t.transfer_group) return;
    try {
      ruleSuggestion = await api("GET", `/api/transactions/${t.id}/rule-suggestion`);
      $("tx-rule-merchant").textContent = `« ${ruleSuggestion.merchant || ""} »`;
    } catch { ruleSuggestion = null; }
    if (editing === t) toggleRuleRow();
  }
  F.category_id.addEventListener("change", toggleRuleRow);

  function openTx(t = null) {
    editing = t;
    txForm.reset();
    AT.clearErrors(txForm);
    $("tx-dialog-title").textContent = t ? "Modifier l'opération" : "Nouvelle opération";
    $("tx-delete").hidden = !t;
    $("tx-transfer-note").classList.toggle("hidden", !(t && t.transfer_group));
    $("tx-category-hint").classList.toggle("hidden", !!t);
    F.account_id.disabled = !!(t && t.transfer_group);
    if (t) {
      // Le compte d'une opération archivée doit rester sélectionnable en édition
      AT.fillSelect(F.account_id, state.accounts.filter((a) => !a.archived || a.id === t.account_id));
      F.direction.value = t.amount_cents > 0 ? "in" : "out";
      F.amount.value = AT.toInput(Math.abs(t.amount_cents));
      F.date.value = t.date;
      F.label.value = t.label;
      F.account_id.value = t.account_id;
      F.category_id.value = t.category_id || "";
      F.status.value = t.status;
      F.notes.value = t.notes || "";
    } else {
      AT.fillSelect(F.account_id, state.accounts.filter((a) => !a.archived));
      F.date.value = AT.today();
      if (state.filters.account_id) F.account_id.value = state.filters.account_id;
    }
    if (!F.account_id.options.length) {
      toast("Créez d'abord un compte (page Comptes & Soldes).", "error");
      return;
    }
    txDialog.showModal();
    F.amount.focus();
    loadRuleSuggestion(t);
  }

  txForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const raw = F.amount.value.trim().replace(/^[-+]/, "");
    const body = {
      amount: raw ? (F.direction.value === "out" ? `-${raw}` : raw) : "",
      date: F.date.value,
      label: F.label.value,
      category_id: F.category_id.value || null,
      status: F.status.value,
      notes: F.notes.value,
    };
    if (!F.account_id.disabled) body.account_id = F.account_id.value;
    try {
      await api(editing ? "PATCH" : "POST", editing ? `/api/transactions/${editing.id}` : "/api/transactions", body);
      let message = editing ? "Opération mise à jour." : "Opération ajoutée.";
      if (editing && $("tx-rule").checked && ruleSuggestion?.pattern && body.category_id) {
        const rule = await api("POST", "/api/rules", { pattern: ruleSuggestion.pattern, match_type: "commercant", category_id: body.category_id });
        const applied = await api("POST", "/api/rules/apply", { rule_id: rule.id });
        message = `Règle créée pour ${ruleSuggestion.merchant}${applied.updated ? ` : ${applied.updated} autre(s) opération(s) reclassée(s)` : ""}.`;
      }
      txDialog.close();
      toast(message);
      load();
    } catch (err) {
      AT.showErrors(txForm, err);
    }
  });

  $("tx-delete").addEventListener("click", async () => {
    if (!editing) return;
    const msg = editing.transfer_group
      ? "Supprimer ce virement ? Les deux opérations liées seront supprimées."
      : `Supprimer l'opération « ${editing.label} » ?`;
    if (!(await AT.confirm(msg, { confirmLabel: "Supprimer" }))) return;
    try {
      await api("DELETE", `/api/transactions/${editing.id}`);
      txDialog.close();
      state.selected.delete(editing.id);
      toast("Opération supprimée.");
      load();
    } catch (err) {
      toast(err.message, "error");
    }
  });

  // ======================================================================= actions groupées

  async function bulk(body, success) {
    try {
      const res = await api("POST", "/api/transactions/bulk", { ...body, ids: [...state.selected] });
      toast(success(res.affected));
      if (body.action === "delete") state.selected.clear();
      load();
    } catch (err) {
      toast(err.message, "error");
    }
  }

  $("bulk-apply").addEventListener("click", () =>
    bulk({ action: "categorize", category_id: $("bulk-category").value || null }, (n) => `${n} opération(s) catégorisée(s).`));
  $("bulk-reconcile").addEventListener("click", () =>
    bulk({ action: "status", status: "rapproche" }, (n) => `${n} opération(s) rapprochée(s).`));
  $("bulk-delete").addEventListener("click", async () => {
    const n = state.selected.size;
    if (await AT.confirm(`Supprimer définitivement ${n} opération(s) ? Les virements liés seront supprimés avec.`, { confirmLabel: "Supprimer" })) {
      bulk({ action: "delete" }, (k) => `${k} opération(s) supprimée(s).`);
    }
  });
  $("bulk-clear").addEventListener("click", () => { state.selected.clear(); render(); });

  // ======================================================================= import (assistant)
  // 1. fichier → 2. vérification (classement en cascade, virements, corrections, IA) → 3. rapport

  const importDialog = $("import-dialog");
  const fileInput = $("imp-file");
  const drop = $("imp-drop");
  const MAPPING_FIELDS = [
    ["date", "Date"], ["label", "Libellé"], ["amount", "Montant"],
    ["debit", "Débit"], ["credit", "Crédit"], ["category", "Catégorie"],
  ];
  const PREVIEW_LIMIT = 300;
  const imp = { file: null, preview: null, selected: new Set(), learn: new Map(), view: "all", step: "file", batchId: null };
  let categoryOptions = "";

  /** Message affiché dans la fenêtre (les toasts passent derrière une fenêtre modale). */
  function note(text) {
    $("imp-note").textContent = text;
    $("imp-note").classList.toggle("hidden", !text);
  }

  function setStep(step) {
    imp.step = step;
    $("import-step-file").classList.toggle("hidden", step === "report");
    $("import-step-preview").classList.toggle("hidden", step !== "preview");
    $("import-step-report").classList.toggle("hidden", step !== "report");
    $("imp-commit").classList.toggle("hidden", step === "report");
    $("imp-cancel").textContent = step === "report" ? "Fermer" : "Annuler";
    drop.classList.toggle("is-compact", step === "preview");
    note("");
    $("import-dialog-title").textContent = step === "report" ? "Rapport d'import" : "Importer un relevé";
    document.querySelectorAll("#imp-steps [data-step]").forEach((li) => {
      li.classList.toggle("font-bold", li.dataset.step === step);
      li.classList.toggle("text-brand", li.dataset.step === step);
    });
  }

  function resetImport() {
    Object.assign(imp, { file: null, preview: null, batchId: null, view: "all" });
    imp.selected.clear();
    imp.learn.clear();
    fileInput.value = "";
    document.querySelector('input[name="imp-view"][value="all"]').checked = true;
    $("imp-file-name").textContent = "Glissez un fichier ici ou cliquez pour choisir";
    $("import-step-report").innerHTML = "";
    setStep("file");
    $("imp-commit").disabled = true;
    $("imp-commit").textContent = "Importer";
  }

  function openImport() {
    if (!state.accounts.some((a) => !a.archived)) {
      toast("Créez d'abord un compte (page Comptes & Soldes).", "error");
      return;
    }
    resetImport();
    if (state.filters.account_id) $("imp-account").value = state.filters.account_id;
    categoryOptions = '<option value="">À classer</option>' + state.categories
      .map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("");
    importDialog.showModal();
  }

  function currentMapping() {
    const mapping = {};
    document.querySelectorAll("#imp-mapping select").forEach((s) => { mapping[s.name] = s.value === "" ? null : Number(s.value); });
    return mapping;
  }

  async function runPreview(mapping = null) {
    if (!imp.file) return;
    const fd = new FormData();
    fd.append("file", imp.file);
    fd.append("account_id", $("imp-account").value);
    if (mapping) fd.append("mapping", JSON.stringify(mapping));
    $("imp-file-name").textContent = `Analyse de ${imp.file.name}…`;
    try {
      imp.preview = await api("POST", "/api/import/preview", fd);
      imp.selected = new Set(imp.preview.rows.map((r, i) => (r.status === "ok" ? i : -1)).filter((i) => i >= 0));
      imp.learn.clear();
      setStep("preview");
      $("imp-mapping-box").open = !!imp.preview.mapping_errors;
      renderPreview();
    } catch (err) {
      toast(err.message, "error");
    } finally {
      $("imp-file-name").textContent = imp.file ? imp.file.name : "";
    }
  }

  function renderMapping(p) {
    const options = ['<option value="">—</option>']
      .concat(p.headers.map((h, i) => `<option value="${i}">${esc(h)}</option>`)).join("");
    $("imp-mapping").innerHTML = MAPPING_FIELDS.map(([key, label]) => `
      <div>
        <label class="field-label" for="map-${key}">${label}</label>
        <select id="map-${key}" name="${key}" class="input h-9 text-sm">${options}</select>
      </div>`).join("");
    for (const [key] of MAPPING_FIELDS) {
      const v = p.mapping[key];
      $(`map-${key}`).value = v === null || v === undefined ? "" : String(v);
    }
  }

  const okRows = () => (imp.preview ? imp.preview.rows.filter((r) => r.status === "ok") : []);
  const todoRows = () => okRows().filter((r) => !r.category_id);

  function renderImportSummary() {
    const s = imp.preview.summary;
    $("imp-summary").innerHTML = `
      <span class="badge">${s.total} ligne${s.total > 1 ? "s" : ""}</span>
      <span class="badge badge-gain">${s.ok} nouvelle${s.ok > 1 ? "s" : ""}</span>
      ${s.duplicates ? `<span class="badge badge-warn">${s.duplicates} déjà présente${s.duplicates > 1 ? "s" : ""}</span>` : ""}
      ${s.errors ? `<span class="badge badge-loss">${s.errors} illisible${s.errors > 1 ? "s" : ""}</span>` : ""}`;
    // Origine des catégories, recalculée après chaque correction
    const counts = {};
    okRows().forEach((r) => { const k = r.category_id ? r.category_source || "manuel" : "aucune"; counts[k] = (counts[k] || 0) + 1; });
    const order = ["regle", "manuel", "fichier", "historique", "defaut", "ia", "virement", "aucune"];
    $("imp-sources").innerHTML = okRows().length
      ? '<span class="text-muted">Classement :</span>' + order.filter((k) => counts[k])
        .map((k) => `<span class="inline-flex items-center gap-1">${AT.sourceBadge(k)}<span class="num">${counts[k]}</span></span>`).join("")
      : "";
    const todo = todoRows().length;
    $("imp-ai").classList.toggle("hidden", !todo);
    $("imp-ai").querySelector("span").textContent = `Classer ${todo > 1 ? `les ${todo} restantes` : "la dernière"} avec l'IA`;
    const n = imp.learn.size;
    $("imp-learn-row").classList.toggle("hidden", !n);
    $("imp-learn-row").classList.toggle("flex", !!n);
    $("imp-learn-label").textContent = `Mémoriser mes corrections comme règle${n > 1 ? "s" : ""} pour les prochains imports (${n} commerçant${n > 1 ? "s" : ""})`;
  }

  function rowHtmlImport(r, i) {
    if (r.status === "error") {
      return `<tr class="text-muted">
        <td></td><td class="hidden md:table-cell num">l. ${r.line}</td>
        <td colspan="3" class="text-xs">${esc((r.raw || []).join(" · ")).slice(0, 160)}</td><td></td>
        <td class="hidden sm:table-cell"><span class="badge badge-loss" title="${esc(r.error)}">${esc(r.error)}</span></td></tr>`;
    }
    const dup = r.status === "duplicate";
    const badge = dup ? '<span class="badge badge-warn">Doublon</span>'
      : r.transfer ? `<span class="badge" title="${esc(r.transfer.label)} du ${AT.date(r.transfer.date)}">↔ ${esc(r.transfer.account_name)}</span>`
        : '<span class="badge badge-gain">Nouvelle</span>';
    return `<tr class="${dup ? "text-muted" : ""}">
      <td><input type="checkbox" class="checkbox" data-imp="${i}" ${imp.selected.has(i) ? "checked" : ""} aria-label="Importer la ligne ${r.line}"></td>
      <td class="hidden whitespace-nowrap md:table-cell num">${AT.date(r.date)}</td>
      <td class="max-w-[16rem]"><span class="block truncate font-semibold" title="${esc(r.label)}">${esc(r.merchant || r.label)}</span>
        <span class="block truncate text-xs text-muted">${esc(r.label)}</span></td>
      <td>${dup ? esc(r.category_name || "—")
        : `<select class="input h-8 min-w-[9rem] py-0 text-sm" data-cat="${i}" aria-label="Catégorie de la ligne ${r.line}">${categoryOptions}</select>`}</td>
      <td class="hidden lg:table-cell">${dup ? "" : AT.sourceBadge(r.category_id ? r.category_source : null)}</td>
      <td class="num whitespace-nowrap text-right font-semibold ${AT.amountClass(r.amount_cents)}">${eur(r.amount_cents, { signed: true })}</td>
      <td class="hidden sm:table-cell">${badge}</td></tr>`;
  }

  function renderRows() {
    const p = imp.preview;
    const visible = p.rows.map((r, i) => [r, i]).filter(([r]) =>
      imp.view === "todo" ? r.status === "ok" && !r.category_id
        : imp.view === "transfer" ? !!r.transfer : true);
    $("imp-rows").innerHTML = visible.slice(0, PREVIEW_LIMIT).map(([r, i]) => rowHtmlImport(r, i)).join("")
      || `<tr><td colspan="7" class="p-6 text-center text-muted">${imp.view === "todo" ? "Tout est classé." : "Aucune ligne."}</td></tr>`;
    $("imp-rows").querySelectorAll("[data-cat]").forEach((sel) => { sel.value = p.rows[sel.dataset.cat].category_id || ""; });
    $("imp-more").textContent = visible.length > PREVIEW_LIMIT
      ? `Aperçu limité aux ${PREVIEW_LIMIT} premières lignes ; les ${visible.length - PREVIEW_LIMIT} suivantes seront importées selon leur état.`
      : "";
  }

  function renderPreview() {
    const p = imp.preview;
    renderMapping(p);
    if (p.mapping_errors) {
      // Colonnes non reconnues automatiquement : l'utilisateur les choisit ci-dessus
      $("imp-summary").innerHTML = `<p class="rounded-xl bg-warn/15 px-3 py-2 text-sm">
        Certaines colonnes n'ont pas été reconnues : ${esc(Object.values(p.mapping_errors).join(" "))}</p>`;
      $("imp-sources").innerHTML = "";
      $("imp-rows").innerHTML = "";
      $("imp-more").textContent = "";
      $("imp-ai").classList.add("hidden");
      updateCommitButton();
      return;
    }
    renderImportSummary();
    renderRows();
    updateCommitButton();
  }

  /** Correction d'une catégorie : appliquée aux autres lignes du même commerçant, puis mémorisable. */
  function setCategory(index, categoryId) {
    const row = imp.preview.rows[index];
    const cat = state.categories.find((c) => c.id === categoryId) || null;
    const apply = (r) => Object.assign(r, {
      category_id: categoryId, category_name: cat ? cat.name : null,
      category_source: categoryId ? "manuel" : null, transfer: categoryId && cat?.kind === "transfert" ? r.transfer : null,
    });
    apply(row);
    let others = 0;
    if (row.merchant_key && categoryId) {
      imp.preview.rows.forEach((r) => {
        if (r !== row && r.status === "ok" && r.merchant_key === row.merchant_key && !r.transfer
            && !["regle", "fichier", "manuel"].includes(r.category_source)
            && Math.sign(r.amount_cents) === Math.sign(row.amount_cents)) {
          apply(r);
          others += 1;
        }
      });
      imp.learn.set(row.merchant_key, categoryId);
    } else if (row.merchant_key) {
      imp.learn.delete(row.merchant_key);
    }
    note(others ? `Appliqué aussi aux ${others} autre(s) ligne(s) « ${row.merchant} ».` : "");
    renderImportSummary();
    renderRows();
  }

  async function classifyWithAI() {
    const todo = imp.preview.rows.map((r, i) => [r, i]).filter(([r]) => r.status === "ok" && !r.category_id);
    if (!todo.length) return;
    const btn = $("imp-ai");
    let engine;
    try { engine = await api("GET", "/api/ai/status"); } catch { engine = { local: true }; }
    if (!engine.local && !(await AT.confirm(
      `Votre moteur d'IA est ${engine.label || "Claude"} : les libellés des ${todo.length} opération(s) à classer seront envoyés à Anthropic (sans montant de solde ni nom de compte). Continuer ?`,
      { confirmLabel: "Envoyer", danger: false }))) return;
    btn.disabled = true;
    const label = btn.querySelector("span");
    let done = 0;
    try {
      // Par paquets de commerçants : l'IA ne voit chaque commerçant qu'une fois
      const groups = new Map();
      todo.forEach(([r, i]) => {
        const k = `${r.merchant_key || r.label}|${r.amount_cents > 0}`;
        if (!groups.has(k)) groups.set(k, []);
        groups.get(k).push([r, i]);
      });
      const keys = [...groups.keys()];
      for (let start = 0; start < keys.length; start += 30) {
        label.textContent = `L'IA classe… ${Math.min(start + 30, keys.length)}/${keys.length} commerçants`;
        const items = keys.slice(start, start + 30).flatMap((k) => groups.get(k))
          .map(([r, i]) => ({ key: i, label: r.label, amount_cents: r.amount_cents }));
        const res = await api("POST", "/api/import/ai-categorize", { items });
        res.items.forEach((s) => {
          const r = imp.preview.rows[s.key];
          if (r && !r.category_id) {
            Object.assign(r, { category_id: s.category_id, category_name: s.category_name, category_source: "ia" });
            done += 1;
          }
        });
      }
      note(done ? `L'IA a proposé une catégorie pour ${done} opération(s) : vérifiez les lignes marquées « IA ».`
        : "L'IA n'a pas trouvé de catégorie sûre pour ces opérations.");
    } catch (err) {
      note(err.message);
    } finally {
      btn.disabled = false;
      renderImportSummary();
      renderRows();
    }
  }

  function updateCommitButton() {
    const n = imp.selected.size;
    $("imp-commit").disabled = n === 0;
    $("imp-commit").textContent = n ? `Importer ${n} opération${n > 1 ? "s" : ""}` : "Importer";
    const selectable = imp.preview ? imp.preview.rows.filter((r) => r.status !== "error").length : 0;
    $("imp-select-all").checked = n > 0 && n === selectable;
    $("imp-select-all").indeterminate = n > 0 && n < selectable;
  }

  async function showReport(batchId) {
    imp.batchId = batchId;
    setStep("report");
    const box = $("import-step-report");
    box.innerHTML = '<div class="skeleton h-40"></div>';
    try {
      const report = await api("GET", `/api/imports/${batchId}/report`);
      AT.importReport.render(box, report, {
        onUndo: () => { importDialog.close(); load(); },
      });
    } catch (err) {
      box.innerHTML = `<p class="text-muted">${esc(err.message)}</p>`;
    }
  }

  function chooseFile(file) {
    if (!file) return;
    imp.file = file;
    imp.preview = null;
    runPreview();
  }

  fileInput.addEventListener("change", () => chooseFile(fileInput.files[0]));
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("is-over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, () => drop.classList.remove("is-over")));
  drop.addEventListener("drop", (e) => { e.preventDefault(); chooseFile(e.dataTransfer.files[0]); });
  $("imp-account").addEventListener("change", () => imp.file && runPreview(imp.preview ? currentMapping() : null));
  $("imp-mapping").addEventListener("change", () => runPreview(currentMapping()));
  $("imp-ai").addEventListener("click", classifyWithAI);
  document.querySelectorAll('input[name="imp-view"]').forEach((el) => el.addEventListener("change", () => {
    imp.view = el.value;
    renderRows();
  }));

  $("imp-rows").addEventListener("change", (e) => {
    if (e.target.dataset.cat !== undefined) {
      setCategory(Number(e.target.dataset.cat), e.target.value ? Number(e.target.value) : null);
      return;
    }
    const i = e.target.dataset.imp;
    if (i === undefined) return;
    e.target.checked ? imp.selected.add(Number(i)) : imp.selected.delete(Number(i));
    updateCommitButton();
  });
  $("imp-select-all").addEventListener("change", (e) => {
    imp.selected = new Set(e.target.checked
      ? imp.preview.rows.map((r, i) => (r.status !== "error" ? i : -1)).filter((i) => i >= 0)
      : []);
    renderRows();
    updateCommitButton();
  });

  $("imp-commit").addEventListener("click", async () => {
    const rows = [...imp.selected].sort((a, b) => a - b).map((i) => imp.preview.rows[i])
      .map((r) => ({
        date: r.date, label: r.label, amount_cents: r.amount_cents, category_id: r.category_id,
        category_source: r.category_source, import_hash: r.import_hash,
        transfer_with: r.transfer ? r.transfer.transaction_id : null,
      }));
    const learn = $("imp-learn").checked
      ? [...imp.learn].map(([pattern, category_id]) => ({ pattern, category_id }))
      : [];
    $("imp-commit").disabled = true;
    try {
      const res = await api("POST", "/api/import/commit", {
        account_id: imp.preview.account_id, filename: imp.preview.filename, rows, learn,
      });
      const extras = [
        res.skipped ? `${res.skipped} doublon(s) ignoré(s)` : "",
        res.transfers_linked ? `${res.transfers_linked} virement(s) lié(s)` : "",
        res.rules_created ? `${res.rules_created} règle(s) mémorisée(s)` : "",
      ].filter(Boolean).join(", ");
      toast(`${res.inserted} opération(s) importée(s)${extras ? ` — ${extras}` : ""}.`);
      state.page = 1;
      load();
      if (res.batch_id) showReport(res.batch_id);
      else importDialog.close();
    } catch (err) {
      toast(err.message, "error");
      $("imp-commit").disabled = false;
    }
  });

  // ======================================================================= événements

  let searchTimer;
  filtersForm.addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { state.page = 1; state.selected.clear(); load(); }, e.target.name === "q" ? 300 : 0);
  });
  filtersForm.addEventListener("submit", (e) => e.preventDefault());
  $("btn-reset").addEventListener("click", () => {
    filtersForm.reset();
    state.page = 1;
    state.selected.clear();
    load();
  });

  $("page-prev").addEventListener("click", () => { state.page -= 1; load(); });
  $("page-next").addEventListener("click", () => { state.page += 1; load(); });
  document.querySelectorAll("[data-sort]").forEach((b) => b.addEventListener("click", () => {
    if (state.sort === b.dataset.sort) state.order = state.order === "asc" ? "desc" : "asc";
    else { state.sort = b.dataset.sort; state.order = b.dataset.sort === "label" ? "asc" : "desc"; }
    load();
  }));

  rowsEl.addEventListener("click", (e) => {
    const box = e.target.closest("[data-select]");
    if (box) {
      const id = Number(box.dataset.select);
      box.checked ? state.selected.add(id) : state.selected.delete(id);
      box.closest("tr").classList.toggle("is-selected", box.checked);
      renderBulk();
      return;
    }
    const tr = e.target.closest("tr[data-id]");
    if (tr) openTx(state.data.items.find((t) => t.id === Number(tr.dataset.id)));
  });
  $("select-all").addEventListener("change", (e) => {
    state.data.items.forEach((t) => (e.target.checked ? state.selected.add(t.id) : state.selected.delete(t.id)));
    render();
  });
  emptyEl.addEventListener("click", (e) => { if (e.target.closest("[data-new]")) openTx(); });

  $("btn-new").addEventListener("click", () => openTx());
  $("btn-import").addEventListener("click", openImport);
  [txDialog, importDialog].forEach((d) => {
    AT.closeOnBackdrop(d);
    d.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => d.close()));
  });

  // Raccourci clavier : « n » pour une nouvelle opération
  document.addEventListener("keydown", (e) => {
    if (e.key === "n" && !e.metaKey && !e.ctrlKey && !document.querySelector("dialog[open]")
        && !["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName)) {
      e.preventDefault();
      openTx();
    }
  });

  // ======================================================================= démarrage
  (async () => {
    try {
      await loadReferences();
    } catch (err) {
      toast(err.message, "error");
    }
    readUrl();
    load();
  })();
})();
