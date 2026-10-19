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
      <span>Solde net <strong class="num text-ink">${eur(d.net_cents, { signed: true })}</strong></span>`;
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
      txDialog.close();
      toast(editing ? "Opération mise à jour." : "Opération ajoutée.");
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

  // ======================================================================= import

  const importDialog = $("import-dialog");
  const fileInput = $("imp-file");
  const drop = $("imp-drop");
  const MAPPING_FIELDS = [
    ["date", "Date"], ["label", "Libellé"], ["amount", "Montant"],
    ["debit", "Débit"], ["credit", "Crédit"], ["category", "Catégorie"],
  ];
  const PREVIEW_LIMIT = 300;
  const imp = { file: null, preview: null, selected: new Set() };

  function resetImport() {
    imp.file = null;
    imp.preview = null;
    imp.selected.clear();
    fileInput.value = "";
    $("imp-file-name").textContent = "Glissez un fichier ici ou cliquez pour choisir";
    $("import-step-preview").classList.add("hidden");
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
      renderPreview();
    } catch (err) {
      toast(err.message, "error");
    } finally {
      $("imp-file-name").textContent = imp.file ? imp.file.name : "";
    }
  }

  function renderPreview() {
    const p = imp.preview;
    $("import-step-preview").classList.remove("hidden");
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

    if (p.mapping_errors) {
      // Colonnes non reconnues automatiquement : l'utilisateur les choisit ci-dessus
      $("imp-summary").innerHTML = `<p class="rounded-xl bg-warn/15 px-3 py-2 text-sm">
        Certaines colonnes n'ont pas été reconnues : ${esc(Object.values(p.mapping_errors).join(" "))}</p>`;
      $("imp-rows").innerHTML = "";
      $("imp-more").textContent = "";
      updateCommitButton();
      return;
    }
    const s = p.summary;
    $("imp-summary").innerHTML = `
      <span class="badge">${s.total} ligne${s.total > 1 ? "s" : ""}</span>
      <span class="badge badge-gain">${s.ok} nouvelle${s.ok > 1 ? "s" : ""}</span>
      ${s.duplicates ? `<span class="badge badge-warn">${s.duplicates} déjà présente${s.duplicates > 1 ? "s" : ""}</span>` : ""}
      ${s.errors ? `<span class="badge badge-loss">${s.errors} illisible${s.errors > 1 ? "s" : ""}</span>` : ""}`;

    const STATE = {
      ok: '<span class="badge badge-gain">Nouvelle</span>',
      duplicate: '<span class="badge badge-warn">Doublon</span>',
    };
    $("imp-rows").innerHTML = p.rows.slice(0, PREVIEW_LIMIT).map((r, i) => {
      if (r.status === "error") {
        return `<tr class="text-muted">
          <td></td><td class="num">${r.line}</td>
          <td colspan="4" class="text-xs">${esc((r.raw || []).join(" · ")).slice(0, 160)}</td>
          <td><span class="badge badge-loss" title="${esc(r.error)}">${esc(r.error)}</span></td></tr>`;
      }
      return `<tr>
        <td><input type="checkbox" class="checkbox" data-imp="${i}" ${imp.selected.has(i) ? "checked" : ""} aria-label="Importer la ligne ${r.line}"></td>
        <td class="num text-muted">${r.line}</td>
        <td class="num whitespace-nowrap">${AT.date(r.date)}</td>
        <td class="max-w-[18rem] truncate">${esc(r.label)}</td>
        <td class="whitespace-nowrap text-muted">${esc(r.category_name || "—")}</td>
        <td class="num whitespace-nowrap text-right font-semibold ${AT.amountClass(r.amount_cents)}">${eur(r.amount_cents, { signed: true })}</td>
        <td>${STATE[r.status]}</td></tr>`;
    }).join("");
    $("imp-more").textContent = p.rows.length > PREVIEW_LIMIT
      ? `Aperçu limité aux ${PREVIEW_LIMIT} premières lignes ; les ${p.rows.length - PREVIEW_LIMIT} suivantes seront importées selon leur état.`
      : "";
    updateCommitButton();
  }

  function updateCommitButton() {
    const n = imp.selected.size;
    $("imp-commit").disabled = n === 0;
    $("imp-commit").textContent = n ? `Importer ${n} opération${n > 1 ? "s" : ""}` : "Importer";
    const selectable = imp.preview ? imp.preview.rows.filter((r) => r.status !== "error").length : 0;
    $("imp-select-all").checked = n > 0 && n === selectable;
    $("imp-select-all").indeterminate = n > 0 && n < selectable;
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

  $("imp-rows").addEventListener("change", (e) => {
    const i = e.target.dataset.imp;
    if (i === undefined) return;
    e.target.checked ? imp.selected.add(Number(i)) : imp.selected.delete(Number(i));
    updateCommitButton();
  });
  $("imp-select-all").addEventListener("change", (e) => {
    imp.selected = new Set(e.target.checked
      ? imp.preview.rows.map((r, i) => (r.status !== "error" ? i : -1)).filter((i) => i >= 0)
      : []);
    renderPreview();
  });

  $("imp-commit").addEventListener("click", async () => {
    const rows = [...imp.selected].sort((a, b) => a - b).map((i) => imp.preview.rows[i])
      .map(({ date, label, amount_cents, category_id, import_hash }) => ({ date, label, amount_cents, category_id, import_hash }));
    $("imp-commit").disabled = true;
    try {
      const res = await api("POST", "/api/import/commit", { account_id: imp.preview.account_id, rows });
      importDialog.close();
      toast(`${res.inserted} opération(s) importée(s)${res.skipped ? `, ${res.skipped} doublon(s) ignoré(s)` : ""}.`);
      state.page = 1;
      load();
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
