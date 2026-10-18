// Page Placements : positions, cours, import Trading 212
(function () {
  "use strict";
  const { esc, eur, api, toast } = AT;
  const $ = (id) => document.getElementById(id);

  const TYPE_COLORS = {
    etf: "#a5b4fc", action: "#7dd3fc", fonds: "#c4b5fd", obligation: "#cbd5e1",
    crypto: "#fdba74", metal: "#fcd34d", autre: "#d6d3d1",
  };
  const METAL_LABELS = { or: "Or", argent: "Argent", platine: "Platine", palladium: "Palladium" };
  const UNIT_PRICE = { titre: "par titre", g: "par gramme", oz: "par once", piece: "par pièce" };
  const qtyFormat = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 8 });
  const gramsFormat = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 2 });

  const state = { accounts: [], accountId: null, data: null };

  const qty = (h) => `${qtyFormat.format(h.quantity)}${h.unit === "titre" ? "" : ` ${h.unit_label}${h.unit === "piece" && h.quantity > 1 ? "s" : ""}`}`;
  const gainClass = (c) => (c > 0 ? "text-gain" : c < 0 ? "text-loss" : "text-muted");
  const pct = (p) => (p === null || p === undefined ? "" : `${p > 0 ? "+" : ""}${p.toLocaleString("fr-FR", { maximumFractionDigits: 2 })} %`);

  // ======================================================================= affichage

  function setKpi(id, value, { tone, hint } = {}) {
    const card = $(id);
    const v = card.querySelector("[data-kpi-value]");
    v.textContent = value;
    if (tone) v.className = v.className.replace(/text-(ink|gain|loss|brand)/, `text-${tone}`);
    const h = card.querySelector("[data-kpi-hint]");
    if (h && hint !== undefined) h.textContent = hint;
  }

  function renderPills() {
    const pills = [{ id: null, name: "Tous les comptes" }, ...state.accounts];
    $("account-pills").innerHTML = pills.map((a) => {
      const active = state.accountId === a.id;
      return `<button type="button" role="tab" aria-selected="${active}" data-account="${a.id ?? ""}"
        class="btn btn-sm ${active ? "btn-primary" : "btn-ghost"}">${esc(a.name)}</button>`;
    }).join("");
  }

  function renderKpis() {
    const t = state.data.totals;
    const accounts = state.accountId ? state.accounts.filter((a) => a.id === state.accountId) : state.accounts;
    const cash = accounts.reduce((s, a) => s + a.balance_cents, 0);
    setKpi("kpi-value", eur(t.value_cents));
    setKpi("kpi-cost", eur(t.cost_cents));
    setKpi("kpi-gain", eur(t.gain_cents, { signed: true }), {
      tone: t.gain_cents < 0 ? "loss" : "gain",
      hint: t.gain_percent === null ? "Aucun prix de revient" : `${pct(t.gain_percent)} sur le montant investi`,
    });
    setKpi("kpi-cash", eur(cash), { hint: `Valeur totale : ${eur(cash + t.value_cents)}` });
  }

  function renderAllocation() {
    const { by_type: byType, totals } = state.data;
    const el = $("allocation");
    if (!totals.value_cents) { el.classList.add("hidden"); return; }
    el.classList.remove("hidden");
    const parts = byType.map((t) => ({ ...t, share: (t.value_cents / totals.value_cents) * 100 }));
    el.innerHTML = `
      <div class="mb-3 flex items-center justify-between">
        <h2 class="font-bold">Répartition</h2>
        <span class="num text-sm text-muted">${eur(totals.value_cents)}</span>
      </div>
      <div class="flex h-3 overflow-hidden rounded-full bg-raised" role="img"
           aria-label="${esc(parts.map((p) => `${p.label} ${Math.round(p.share)} %`).join(", "))}">
        ${parts.map((p) => `<span style="width:${p.share}%;background:${TYPE_COLORS[p.asset_type]}" title="${esc(p.label)}"></span>`).join("")}
      </div>
      <div class="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm">
        ${parts.map((p) => `<span class="flex items-center gap-2">
          <span class="h-2.5 w-2.5 rounded-full" style="background:${TYPE_COLORS[p.asset_type]}"></span>
          ${esc(p.label)} <strong class="num">${Math.round(p.share)} %</strong>
          <span class="num text-muted">${eur(p.value_cents)}</span></span>`).join("")}
      </div>`;
  }

  function subtitle(h) {
    if (h.asset_type === "metal") {
      const bits = [METAL_LABELS[h.metal] || "Métal"];
      if (h.purity) bits.push(`${gramsFormat.format(h.purity)} ‰`);
      if (h.fine_grams) bits.push(`${gramsFormat.format(h.fine_grams)} g fin`);
      return bits.join(" · ");
    }
    return [h.symbol, h.isin].filter(Boolean).join(" · ");
  }

  function rowHtml(h) {
    const priceDate = h.price_updated_at ? `<p class="text-xs text-muted">${AT.date(h.price_updated_at)}</p>` : "";
    return `
      <tr class="cursor-pointer ${h.closed ? "opacity-60" : ""}" data-id="${h.id}">
        <td class="max-w-[16rem] sm:max-w-[22rem]">
          <div class="flex items-center gap-2">
            <span class="h-2.5 w-2.5 shrink-0 rounded-full" style="background:${TYPE_COLORS[h.asset_type]}" title="${esc(h.asset_label)}"></span>
            <p class="truncate font-semibold">${esc(h.name)}</p>
            ${h.closed ? '<span class="badge">Soldée</span>' : ""}
          </div>
          <p class="truncate pl-[1.1rem] text-xs text-muted">${esc(h.asset_label)}${subtitle(h) ? ` · ${esc(subtitle(h))}` : ""}</p>
        </td>
        <td class="hidden whitespace-nowrap text-muted md:table-cell">${esc(h.account_name)}</td>
        <td class="num hidden whitespace-nowrap text-right sm:table-cell">${qty(h)}</td>
        <td class="num hidden whitespace-nowrap text-right lg:table-cell">
          ${eur(h.cost_basis_cents)}
          ${h.average_price_cents ? `<p class="text-xs text-muted">${eur(h.average_price_cents)} ${UNIT_PRICE[h.unit]}</p>` : ""}
        </td>
        <td class="num hidden whitespace-nowrap text-right md:table-cell">
          ${h.price_cents === null ? '<span class="text-muted">—</span>' : eur(h.price_cents)}${priceDate}
        </td>
        <td class="num whitespace-nowrap text-right font-bold">
          ${eur(h.value_cents)}<p class="text-xs font-normal text-muted">${h.weight_percent} %</p>
        </td>
        <td class="num hidden whitespace-nowrap text-right font-semibold sm:table-cell ${gainClass(h.gain_cents)}">
          ${h.price_cents === null ? '<span class="text-muted">—</span>' : `${eur(h.gain_cents, { signed: true })}<p class="text-xs">${pct(h.gain_percent)}</p>`}
        </td>
      </tr>`;
  }

  function renderTable() {
    const items = state.data.items;
    $("rows").innerHTML = items.map(rowHtml).join("");
    $("empty").classList.toggle("hidden", items.length > 0);
    $("empty").innerHTML = 'Aucune position. <button class="font-semibold text-brand hover:underline" data-new>Ajoutez-en une</button> ou importez votre historique Trading 212.';
  }

  async function loadAccounts() {
    const data = await api("GET", "/api/accounts");
    state.accounts = data.items.filter((a) => a.type === "investissement");
    const hasAccounts = state.accounts.length > 0;
    $("no-account").classList.toggle("hidden", hasAccounts);
    $("main").classList.toggle("hidden", !hasAccounts);
    if (state.accountId && !state.accounts.some((a) => a.id === state.accountId)) state.accountId = null;
    return hasAccounts;
  }

  async function load() {
    try {
      if (!(await loadAccounts())) return;
      const params = new URLSearchParams();
      if (state.accountId) params.set("account_id", state.accountId);
      if ($("show-closed").checked) params.set("closed", "1");
      state.data = await api("GET", `/api/holdings?${params}`);
      renderPills();
      renderKpis();
      renderAllocation();
      renderTable();
    } catch (err) {
      toast(err.message, "error");
    }
  }

  // ======================================================================= fenêtre position

  const holdingDialog = $("holding-dialog");
  const form = $("holding-form");
  const F = form.elements;
  let editing = null;

  function syncFormVisibility() {
    const metal = F.asset_type.value === "metal";
    form.querySelectorAll('[data-for="titre"]').forEach((el) => (el.hidden = metal));
    form.querySelectorAll('[data-for="metal"]').forEach((el) => (el.hidden = !metal));
    const unit = metal ? F.unit.value : "titre";
    form.querySelector('[data-for="piece"]').hidden = unit !== "piece";
    $("hd-unit-hint").textContent = metal ? `(${{ g: "grammes", oz: "onces", piece: "pièces" }[unit]})` : "";
    $("hd-price-unit").textContent = UNIT_PRICE[unit];
  }

  function openHolding(h = null) {
    editing = h;
    form.reset();
    AT.clearErrors(form);
    AT.fillSelect(F.account_id, state.accounts);
    $("holding-dialog-title").textContent = h ? "Modifier la position" : "Nouvelle position";
    $("hd-delete").hidden = !h;
    const imported = !!(h && h.trade_count);
    F.quantity.disabled = imported;
    F.cost_basis.disabled = imported;
    $("hd-imported-note").classList.toggle("hidden", !imported);
    if (h) {
      F.asset_type.value = h.asset_type;
      F.account_id.value = h.account_id;
      F.name.value = h.name;
      F.symbol.value = h.symbol || "";
      F.isin.value = h.isin || "";
      if (h.metal) F.metal.value = h.metal;
      if (h.unit !== "titre") F.unit.value = h.unit;
      F.purity.value = h.purity ? String(h.purity).replace(".", ",") : "";
      F.weight_g.value = h.weight_g ? String(h.weight_g).replace(".", ",") : "";
      F.quantity.value = String(h.quantity).replace(".", ",");
      F.cost_basis.value = AT.toInput(h.cost_basis_cents);
      F.price.value = h.price_cents === null ? "" : AT.toInput(h.price_cents);
      F.notes.value = h.notes || "";
    } else if (state.accountId) {
      F.account_id.value = state.accountId;
    }
    syncFormVisibility();
    holdingDialog.showModal();
    F.name.focus();
  }

  F.asset_type.addEventListener("change", () => {
    if (F.asset_type.value === "metal" && !F.purity.value) F.purity.value = "999,9";
    syncFormVisibility();
  });
  F.unit.addEventListener("change", syncFormVisibility);

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const metal = F.asset_type.value === "metal";
    const body = {
      account_id: F.account_id.value,
      asset_type: F.asset_type.value,
      name: F.name.value,
      symbol: metal ? null : F.symbol.value,
      isin: metal ? null : F.isin.value,
      metal: metal ? F.metal.value : null,
      unit: metal ? F.unit.value : "titre",
      purity: metal ? F.purity.value : null,
      weight_g: metal && F.unit.value === "piece" ? F.weight_g.value : null,
      notes: F.notes.value,
    };
    if (!F.quantity.disabled) {
      body.quantity = F.quantity.value || "0";
      body.cost_basis = F.cost_basis.value || "0";
    }
    if (F.price.value.trim()) body.price = F.price.value;
    try {
      await api(editing ? "PATCH" : "POST", editing ? `/api/holdings/${editing.id}` : "/api/holdings", body);
      holdingDialog.close();
      toast(editing ? "Position mise à jour." : "Position ajoutée.");
      load();
    } catch (err) {
      AT.showErrors(form, err);
    }
  });

  $("hd-delete").addEventListener("click", async () => {
    if (!editing) return;
    const extra = editing.trade_count
      ? " Les opérations de trésorerie importées restent sur le compte." : "";
    if (!(await AT.confirm(`Supprimer la position « ${editing.name} » ?${extra}`, { confirmLabel: "Supprimer" }))) return;
    try {
      await api("DELETE", `/api/holdings/${editing.id}`);
      holdingDialog.close();
      toast("Position supprimée.");
      load();
    } catch (err) {
      toast(err.message, "error");
    }
  });

  // ======================================================================= fenêtre cours

  const pricesDialog = $("prices-dialog");
  const pricesForm = $("prices-form");

  function openPrices() {
    const items = state.data.items.filter((h) => !h.closed);
    if (!items.length) { toast("Aucune position à mettre à jour.", "error"); return; }
    $("prices-rows").innerHTML = items.map((h) => `
      <tr>
        <td><p class="font-semibold">${esc(h.name)}</p><p class="text-xs text-muted">${esc(UNIT_PRICE[h.unit])}${subtitle(h) ? ` · ${esc(subtitle(h))}` : ""}</p></td>
        <td class="num text-right">${h.price_cents === null ? "—" : eur(h.price_cents)}
          ${h.price_updated_at ? `<p class="text-xs text-muted">${AT.date(h.price_updated_at)}</p>` : ""}</td>
        <td data-field><input class="input num h-9" name="p-${h.id}" data-id="${h.id}" inputmode="decimal"
             placeholder="${h.price_cents === null ? "0,00" : AT.toInput(h.price_cents)}" aria-label="Nouveau cours de ${esc(h.name)}"></td>
      </tr>`).join("");
    pricesDialog.showModal();
    pricesForm.querySelector("input")?.focus();
  }

  pricesForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const prices = [...pricesForm.querySelectorAll("input[data-id]")]
      .filter((i) => i.value.trim())
      .map((i) => ({ id: Number(i.dataset.id), price: i.value }));
    if (!prices.length) { pricesDialog.close(); return; }
    try {
      const res = await api("POST", "/api/holdings/prices", { prices });
      pricesDialog.close();
      toast(`${res.updated} cours mis à jour.`);
      load();
    } catch (err) {
      // Les erreurs sont indexées par identifiant de position
      AT.showErrors(pricesForm, { ...err, fields: Object.fromEntries(Object.entries(err.fields || {}).map(([id, m]) => [`p-${id}`, m])) });
    }
  });

  // ======================================================================= import Trading 212

  const t212Dialog = $("t212-dialog");
  const t212 = { file: null, preview: null };

  function resetT212() {
    t212.file = null;
    t212.preview = null;
    $("t212-file").value = "";
    $("t212-file-name").textContent = "Glissez l'export CSV ici ou cliquez pour choisir";
    $("t212-preview").classList.add("hidden");
    $("t212-commit").disabled = true;
    $("t212-commit").textContent = "Importer";
  }

  function openT212() {
    resetT212();
    AT.fillSelect($("t212-account"), state.accounts);
    const t212Account = state.accounts.find((a) => /trading\s*212|t212/i.test(a.name));
    if (state.accountId) $("t212-account").value = state.accountId;
    else if (t212Account) $("t212-account").value = t212Account.id;
    t212Dialog.showModal();
  }

  async function sendT212(dryRun) {
    const fd = new FormData();
    fd.append("file", t212.file);
    fd.append("account_id", $("t212-account").value);
    fd.append("dry_run", dryRun ? "1" : "0");
    return api("POST", "/api/import/trading212", fd);
  }

  function renderT212() {
    const p = t212.preview;
    const s = p.summary;
    $("t212-preview").classList.remove("hidden");
    $("t212-summary").innerHTML = `
      <span class="badge">${s.total} opération${s.total > 1 ? "s" : ""} lue${s.total > 1 ? "s" : ""}</span>
      <span class="badge badge-gain">${s.new} nouvelle${s.new > 1 ? "s" : ""}</span>
      ${s.duplicates ? `<span class="badge badge-warn">${s.duplicates} déjà importée${s.duplicates > 1 ? "s" : ""}</span>` : ""}
      ${s.ignored ? `<span class="badge">${s.ignored} ignorée${s.ignored > 1 ? "s" : ""}</span>` : ""}
      <span class="badge">Liquidités ${eur(s.cash_change_cents, { signed: true })}</span>`;
    $("t212-kinds").innerHTML = p.by_kind.length
      ? p.by_kind.map((k) => `<tr><td>${esc(k.label)}</td><td class="num text-right text-muted">${k.count}</td>
          <td class="num text-right font-semibold ${AT.amountClass(k.amount_cents)}">${eur(k.amount_cents, { signed: true })}</td></tr>`).join("")
      : '<tr><td class="text-muted">Rien de nouveau dans ce fichier.</td></tr>';
    $("t212-positions").innerHTML = p.positions.length
      ? p.positions.map((pos) => `<tr class="${pos.quantity ? "" : "text-muted"}">
          <td class="max-w-[14rem] truncate">${esc(pos.name)}</td>
          <td class="num whitespace-nowrap text-right">${qtyFormat.format(pos.quantity)}</td>
          <td class="num whitespace-nowrap text-right">${pos.quantity ? eur(pos.cost_basis_cents) : "Soldée"}</td></tr>`).join("")
      : '<tr><td class="text-muted">Aucun achat ni vente.</td></tr>';
    $("t212-ignored-box").hidden = !p.ignored.length;
    $("t212-ignored").innerHTML = p.ignored.map((i) =>
      `<li>Ligne ${i.line} · <strong>${esc(i.action)}</strong> — ${esc(i.reason)}</li>`).join("");
    $("t212-commit").disabled = s.new === 0;
    $("t212-commit").textContent = s.new ? `Importer ${s.new} opération${s.new > 1 ? "s" : ""}` : "Rien à importer";
  }

  async function previewT212() {
    if (!t212.file) return;
    $("t212-file-name").textContent = `Analyse de ${t212.file.name}…`;
    try {
      t212.preview = await sendT212(true);
      renderT212();
    } catch (err) {
      $("t212-preview").classList.add("hidden");
      toast(err.message, "error");
    } finally {
      $("t212-file-name").textContent = t212.file.name;
    }
  }

  function chooseT212(file) {
    if (!file) return;
    t212.file = file;
    previewT212();
  }

  const drop = $("t212-drop");
  $("t212-file").addEventListener("change", (e) => chooseT212(e.target.files[0]));
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("is-over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, () => drop.classList.remove("is-over")));
  drop.addEventListener("drop", (e) => { e.preventDefault(); chooseT212(e.dataTransfer.files[0]); });
  $("t212-account").addEventListener("change", previewT212);

  $("t212-commit").addEventListener("click", async () => {
    $("t212-commit").disabled = true;
    try {
      const res = await sendT212(false);
      t212Dialog.close();
      toast(`${res.inserted} opération(s) importée(s), ${res.positions_updated} position(s) mise(s) à jour.`);
      state.accountId = Number($("t212-account").value);
      load();
    } catch (err) {
      toast(err.message, "error");
      $("t212-commit").disabled = false;
    }
  });

  // ======================================================================= événements

  $("account-pills").addEventListener("click", (e) => {
    const b = e.target.closest("[data-account]");
    if (!b) return;
    state.accountId = b.dataset.account ? Number(b.dataset.account) : null;
    load();
  });
  $("show-closed").addEventListener("change", load);
  $("btn-new").addEventListener("click", () => openHolding());
  $("btn-prices").addEventListener("click", openPrices);
  $("btn-t212").addEventListener("click", openT212);
  $("rows").addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-id]");
    if (tr) openHolding(state.data.items.find((h) => h.id === Number(tr.dataset.id)));
  });
  $("empty").addEventListener("click", (e) => { if (e.target.closest("[data-new]")) openHolding(); });
  $("quick-t212").addEventListener("click", async () => {
    try {
      await api("POST", "/api/accounts", { name: "Trading 212", type: "investissement", institution: "Trading 212", color: "#7dd3fc" });
      toast("Compte « Trading 212 » créé.");
      await load();
      openT212();
    } catch (err) {
      toast(err.message, "error");
    }
  });
  [holdingDialog, pricesDialog, t212Dialog].forEach((d) => {
    AT.closeOnBackdrop(d);
    d.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => d.close()));
  });

  load();
})();
