// Page Imports & Règles : opérations récurrentes, historique des imports (rapport, annulation), règles de classement
(function () {
  "use strict";
  const { esc, eur, api, toast } = AT;
  const $ = (id) => document.getElementById(id);
  const state = { accounts: [], categories: [], rules: [], editing: null };
  const TYPE_LABELS = { contient: "contient", commence: "commence par", commercant: "commerçant =" };
  const DIR_LABELS = { tous: "Tous", debit: "Sorties", credit: "Entrées" };

  // ======================================================================= récurrences

  async function loadRecurring() {
    const account = $("rec-account").value;
    try {
      const d = await api("GET", `/api/insights/recurring${account ? `?account_id=${account}` : ""}`);
      $("kpi-debits").textContent = eur(Math.abs(d.monthly_debit_cents));
      $("kpi-credits").textContent = eur(d.monthly_credit_cents);
      const upcomingOut = d.upcoming.filter((i) => i.direction === "debit");
      $("kpi-upcoming").textContent = eur(Math.abs(upcomingOut.reduce((s, i) => s + i.amount_cents, 0)));
      $("kpi-upcoming-hint").textContent = upcomingOut.length
        ? `${upcomingOut.length} prélèvement(s) attendu(s), dont ${upcomingOut.slice(0, 3).map((i) => i.merchant).join(", ")}`
        : "Aucun prélèvement attendu.";
      $("rec-rows").innerHTML = d.items.map((i) => `<tr>
          <td><span class="font-semibold">${esc(i.merchant)}</span>
            <span class="block text-xs text-muted">${i.count} fois depuis le ${AT.date(i.first_date)}${i.fixed ? "" : " · montant variable"}</span></td>
          <td class="hidden md:table-cell">${i.category_name ? `<span class="badge"><span class="dot" style="background:${esc(i.category_color)}"></span>${esc(i.category_name)}</span>` : '<span class="text-muted">—</span>'}</td>
          <td>${esc(AT.FREQ[i.frequency] || i.frequency)}</td>
          <td class="hidden sm:table-cell num whitespace-nowrap">${AT.date(i.next_date)}</td>
          <td class="num whitespace-nowrap text-right font-semibold ${AT.amountClass(i.amount_cents)}">${eur(i.amount_cents, { signed: true })}</td>
          <td class="hidden lg:table-cell num whitespace-nowrap text-right text-muted">${eur(i.monthly_cents, { signed: true })}</td>
        </tr>`).join("")
        || '<tr><td colspan="6" class="p-8 text-center text-muted">Pas encore assez d\'historique : il faut au moins trois échéances régulières d\'un même commerçant.</td></tr>';
    } catch (err) { toast(err.message, "error"); }
  }

  // ======================================================================= imports

  async function loadBatches() {
    try {
      const { items } = await api("GET", "/api/imports");
      $("batch-rows").innerHTML = items.map((b) => `<tr>
          <td class="num whitespace-nowrap">${AT.date(b.created_at.slice(0, 10))}</td>
          <td class="max-w-[16rem]"><span class="block truncate font-semibold" title="${esc(b.filename)}">${esc(b.filename)}</span>
            <span class="block truncate text-xs text-muted">${esc(b.account_name)}</span></td>
          <td class="hidden md:table-cell whitespace-nowrap text-sm">${b.start ? `${AT.date(b.start)} → ${AT.date(b.end)}` : "—"}</td>
          <td class="num text-right">${b.count}${b.uncategorized ? `<span class="block text-xs text-loss">${b.uncategorized} à classer</span>` : ""}</td>
          <td class="hidden lg:table-cell num whitespace-nowrap text-right text-gain">${eur(b.income_cents)}</td>
          <td class="hidden lg:table-cell num whitespace-nowrap text-right text-loss">${eur(Math.abs(b.expense_cents))}</td>
          <td class="whitespace-nowrap text-right"><button class="btn btn-ghost btn-sm" data-report="${b.id}">Rapport</button></td>
        </tr>`).join("")
        || '<tr><td colspan="7" class="p-8 text-center text-muted">Aucun import pour le moment. Importez un relevé depuis la page Transactions.</td></tr>';
    } catch (err) { toast(err.message, "error"); }
  }

  async function openReport(id) {
    const dlg = $("report-dialog");
    $("report-body").innerHTML = '<div class="skeleton h-40"></div>';
    dlg.showModal();
    try {
      const report = await api("GET", `/api/imports/${id}/report`);
      AT.importReport.render($("report-body"), report, {
        onUndo: () => { dlg.close(); loadBatches(); loadRecurring(); loadRules(); },
      });
    } catch (err) {
      $("report-body").innerHTML = `<p class="text-muted">${esc(err.message)}</p>`;
    }
  }

  $("batch-rows").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-report]");
    if (btn) openReport(Number(btn.dataset.report));
  });

  // ======================================================================= règles

  async function loadRules() {
    try {
      state.rules = (await api("GET", "/api/rules")).items;
      $("rule-rows").innerHTML = state.rules.map((r) => `<tr data-id="${r.id}" class="cursor-pointer">
          <td><span class="text-muted">${TYPE_LABELS[r.match_type]}</span> <strong>« ${esc(r.pattern)} »</strong></td>
          <td><span class="badge"><span class="dot" style="background:${esc(r.category_color)}"></span>${esc(r.category_name)}</span></td>
          <td class="hidden md:table-cell">${DIR_LABELS[r.direction]}</td>
          <td class="hidden md:table-cell">${r.account_name ? esc(r.account_name) : '<span class="text-muted">Tous</span>'}</td>
          <td class="hidden sm:table-cell num text-right">${r.matches}</td>
          <td class="text-right"><button class="btn btn-ghost btn-sm" type="button">Modifier</button></td>
        </tr>`).join("")
        || '<tr><td colspan="6" class="p-8 text-center text-muted">Aucune règle. Créez-en une, ou corrigez une catégorie pendant un import : elle sera proposée comme règle.</td></tr>';
    } catch (err) { toast(err.message, "error"); }
  }

  const ruleDialog = $("rule-dialog");
  const ruleForm = $("rule-form");
  const R = ruleForm.elements;

  function openRule(rule = null) {
    state.editing = rule;
    ruleForm.reset();
    AT.clearErrors(ruleForm);
    $("rule-title").textContent = rule ? "Modifier la règle" : "Nouvelle règle";
    $("rule-delete").hidden = !rule;
    if (rule) {
      R.match_type.value = rule.match_type;
      R.pattern.value = rule.pattern;
      R.category_id.value = rule.category_id;
      R.direction.value = rule.direction;
      R.account_id.value = rule.account_id || "";
    }
    ruleDialog.showModal();
    R.pattern.focus();
  }

  ruleForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = {
      match_type: R.match_type.value, pattern: R.pattern.value, category_id: R.category_id.value || null,
      direction: R.direction.value, account_id: R.account_id.value || null,
    };
    try {
      const rule = await api(state.editing ? "PATCH" : "POST", state.editing ? `/api/rules/${state.editing.id}` : "/api/rules", body);
      ruleDialog.close();
      const applied = await api("POST", "/api/rules/apply", { rule_id: rule.id });
      toast(`Règle enregistrée${applied.updated ? ` : ${applied.updated} opération(s) reclassée(s)` : ""}.`);
      loadRules();
    } catch (err) { AT.showErrors(ruleForm, err); }
  });

  $("rule-delete").addEventListener("click", async () => {
    if (!state.editing || !(await AT.confirm("Supprimer cette règle ? Les opérations déjà classées gardent leur catégorie.", { confirmLabel: "Supprimer" }))) return;
    try {
      await api("DELETE", `/api/rules/${state.editing.id}`);
      ruleDialog.close();
      toast("Règle supprimée.");
      loadRules();
    } catch (err) { toast(err.message, "error"); }
  });

  $("rule-rows").addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-id]");
    if (tr) openRule(state.rules.find((r) => r.id === Number(tr.dataset.id)));
  });
  $("btn-new-rule").addEventListener("click", () => openRule());
  $("btn-apply-rules").addEventListener("click", async () => {
    try {
      const res = await api("POST", "/api/rules/apply", {});
      toast(res.updated ? `${res.updated} opération(s) reclassée(s).`
        : "Rien à changer : les catégories choisies à la main ne sont jamais écrasées.");
      loadRules();
    } catch (err) { toast(err.message, "error"); }
  });

  [ruleDialog, $("report-dialog")].forEach((d) => {
    AT.closeOnBackdrop(d);
    d.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => d.close()));
  });

  // ======================================================================= démarrage
  (async () => {
    try {
      const [acc, cat] = await Promise.all([api("GET", "/api/accounts?archived=1"), api("GET", "/api/categories")]);
      state.accounts = acc.items;
      state.categories = cat.items;
      const byKind = (c) => AT.KIND_LABELS[c.kind] || c.kind;
      AT.fillSelect($("rec-account"), state.accounts, { placeholder: "Tous les comptes" });
      AT.fillSelect(R.category_id, state.categories, { groupBy: byKind });
      AT.fillSelect(R.account_id, state.accounts.filter((a) => !a.archived), { placeholder: "Tous les comptes" });
    } catch (err) { toast(err.message, "error"); }
    $("rec-account").addEventListener("change", loadRecurring);
    loadRecurring();
    loadBatches();
    loadRules();
    const batch = new URLSearchParams(location.search).get("report");
    if (batch) openReport(Number(batch));
  })();
})();
