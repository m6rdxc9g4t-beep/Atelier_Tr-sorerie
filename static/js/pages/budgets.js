// Page Budgets & Objectifs
(function () {
  "use strict";
  const { esc, eur, api, toast } = AT;
  const $ = (id) => document.getElementById(id);

  const TONE = { ok: "gain", attention: "warn", depasse: "loss" };
  const thisMonth = AT.today().slice(0, 7);
  const params = new URLSearchParams(location.search);
  let month = /^\d{4}-\d{2}$/.test(params.get("month") || "") ? params.get("month") : thisMonth;
  let data = null;
  let goals = [];
  let categories = [];
  let accounts = [];

  // ======================================================================= budgets

  function bar(percent, tone) {
    const width = Math.min(100, percent ?? 0);
    return `<div class="progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(width)}">
      <span style="width:${width}%; background: var(--${tone})"></span></div>`;
  }

  function renderTotal() {
    const el = $("budget-total");
    if (!data.items.length) {
      el.innerHTML = `
        <p class="font-bold">Aucun budget pour ${esc(AT.monthLabel(month).toLowerCase())}</p>
        <p class="mt-1 text-sm text-muted">Fixez un plafond par catégorie pour suivre vos dépenses, ou reprenez ceux du mois précédent.</p>`;
      return;
    }
    const pct = data.total_percent ?? 0;
    const tone = pct >= 100 ? "loss" : pct >= 80 ? "warn" : "gain";
    const left = data.total_limit_cents - data.total_spent_cents;
    el.innerHTML = `
      <div class="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p class="text-sm font-medium text-muted">Dépensé sur les catégories budgétées</p>
          <p class="num mt-1 text-3xl font-extrabold tracking-tight">${eur(data.total_spent_cents)}
            <span class="text-base font-semibold text-muted">/ ${eur(data.total_limit_cents)}</span></p>
        </div>
        <p class="num text-sm font-bold text-${tone}">
          ${left >= 0 ? `Reste ${eur(left)}` : `Dépassement de ${eur(-left)}`}
        </p>
      </div>
      <div class="mt-4">${bar(pct, tone)}</div>`;
  }

  function renderList() {
    const list = $("budget-list");
    if (!data.items.length) {
      list.innerHTML = '<p class="text-sm text-muted">Aucun budget défini pour ce mois.</p>';
      return;
    }
    list.innerHTML = data.items.map((b) => {
      const tone = TONE[b.status];
      const remaining = b.remaining_cents >= 0
        ? `<span class="text-muted">Reste</span> <strong class="num">${eur(b.remaining_cents)}</strong>`
        : `<strong class="num text-loss">Dépassé de ${eur(-b.remaining_cents)}</strong>`;
      return `
        <button class="block w-full rounded-xl p-2 -m-2 text-left transition hover:bg-raised/60" data-budget="${b.id}">
          <div class="flex items-center justify-between gap-3">
            <span class="flex min-w-0 items-center gap-2 font-semibold">
              <span class="h-2.5 w-2.5 shrink-0 rounded-full" style="background:${esc(b.category_color)}"></span>
              <span class="truncate">${esc(b.category_name)}</span>
            </span>
            <span class="num shrink-0 text-sm"><strong>${eur(b.spent_cents)}</strong>
              <span class="text-muted">/ ${eur(b.amount_limit_cents)}</span></span>
          </div>
          <div class="mt-2">${bar(b.percent, tone)}</div>
          <div class="mt-1.5 flex justify-between text-xs">
            <span class="num text-${tone} font-semibold">${b.percent === null ? "—" : `${Math.round(b.percent)} %`}</span>
            <span>${remaining}</span>
          </div>
        </button>`;
    }).join("");
  }

  function renderUnbudgeted() {
    const card = $("unbudgeted-card");
    card.classList.toggle("hidden", !data.unbudgeted.length);
    $("unbudgeted-list").innerHTML = data.unbudgeted.map((u) => `
      <li class="flex items-center justify-between gap-3 py-3">
        <span class="flex min-w-0 items-center gap-2">
          <span class="h-2.5 w-2.5 shrink-0 rounded-full" style="background:${esc(u.category_color)}"></span>
          <span class="truncate font-semibold">${esc(u.category_name)}</span>
        </span>
        <span class="flex items-center gap-3">
          <span class="num text-sm font-bold">${eur(u.spent_cents)}</span>
          <button class="btn btn-ghost btn-sm" data-quick="${u.category_id}" data-spent="${u.spent_cents}">Fixer un budget</button>
        </span>
      </li>`).join("");
  }

  async function loadBudgets() {
    $("month-label").textContent = AT.monthLabel(month);
    $("month-today").hidden = month === thisMonth;
    history.replaceState(null, "", month === thisMonth ? location.pathname : `?month=${month}`);
    try {
      data = await api("GET", `/api/budgets?month=${month}`);
      renderTotal();
      renderList();
      renderUnbudgeted();
    } catch (err) {
      toast(err.message, "error");
    }
  }

  // ---------------------------------------------------------------- fenêtre budget

  const budgetDialog = $("budget-dialog");
  const budgetForm = $("budget-form");
  const BF = budgetForm.elements;
  let editingBudget = null;

  function openBudget(budget = null, preset = {}) {
    editingBudget = budget;
    budgetForm.reset();
    AT.clearErrors(budgetForm);
    $("budget-dialog-title").textContent = budget ? `Budget ${budget.category_name}` : "Nouveau budget";
    $("bd-delete").hidden = !budget;
    const used = new Set(data.items.map((b) => b.category_id));
    const choices = categories.filter((c) => c.kind === "depense" && (!used.has(c.id) || (budget && c.id === budget.category_id)));
    if (!budget && !choices.length) {
      toast("Toutes les catégories de dépense ont déjà un budget ce mois-ci.", "error");
      return;
    }
    AT.fillSelect(BF.category_id, choices);
    BF.category_id.disabled = !!budget;
    if (budget) {
      BF.category_id.value = budget.category_id;
      BF.amount_limit.value = AT.toInput(budget.amount_limit_cents);
      $("bd-hint").textContent = `Dépensé ce mois-ci : ${eur(budget.spent_cents)}`;
    } else {
      if (preset.category_id) BF.category_id.value = preset.category_id;
      $("bd-hint").textContent = preset.spent ? `Dépensé ce mois-ci : ${eur(preset.spent)}` : `Pour ${AT.monthLabel(month).toLowerCase()}`;
    }
    budgetDialog.showModal();
    BF.amount_limit.focus();
  }

  budgetForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      if (editingBudget) {
        await api("PATCH", `/api/budgets/${editingBudget.id}`, { amount_limit: BF.amount_limit.value });
      } else {
        await api("POST", "/api/budgets", { category_id: BF.category_id.value, month, amount_limit: BF.amount_limit.value });
      }
      budgetDialog.close();
      toast("Budget enregistré.");
      loadBudgets();
    } catch (err) {
      AT.showErrors(budgetForm, err);
    }
  });

  $("bd-delete").addEventListener("click", async () => {
    if (!editingBudget || !(await AT.confirm(`Supprimer le budget « ${editingBudget.category_name} » de ce mois ?`, { confirmLabel: "Supprimer" }))) return;
    try {
      await api("DELETE", `/api/budgets/${editingBudget.id}`);
      budgetDialog.close();
      toast("Budget supprimé.");
      loadBudgets();
    } catch (err) {
      toast(err.message, "error");
    }
  });

  $("btn-copy").addEventListener("click", async () => {
    const from = AT.shiftMonth(month, -1);
    try {
      const res = await api("POST", "/api/budgets/copy", { from_month: from, to_month: month });
      toast(res.copied ? `${res.copied} budget(s) repris de ${AT.monthLabel(from).toLowerCase()}.` : "Ces budgets existent déjà ce mois-ci.");
      loadBudgets();
    } catch (err) {
      toast(err.status === 409 ? `Aucun budget défini en ${AT.monthLabel(from).toLowerCase()}.` : err.message, "error");
    }
  });

  // ======================================================================= objectifs

  function renderGoals() {
    const list = $("goal-list");
    if (!goals.length) {
      list.innerHTML = '<p class="text-sm text-muted">Aucun objectif. Ajoutez-en un pour suivre une épargne : vacances, fonds d\'urgence, apport…</p>';
      return;
    }
    list.innerHTML = goals.map((g) => {
      const done = g.percent >= 100;
      const meta = [];
      if (g.deadline) meta.push(`Échéance ${AT.date(g.deadline)}`);
      if (g.monthly_needed_cents) meta.push(`${eur(g.monthly_needed_cents)} / mois`);
      if (g.account_name) meta.push(`Suit « ${esc(g.account_name)} »`);
      return `
        <button class="block w-full rounded-xl border border-line p-4 text-left transition hover:bg-raised/60" data-goal="${g.id}">
          <div class="flex items-center justify-between gap-2">
            <span class="truncate font-semibold">${esc(g.name)}</span>
            ${done ? '<span class="badge badge-gain">Atteint</span>' : `<span class="num text-sm font-bold text-brand">${Math.round(g.percent)} %</span>`}
          </div>
          <p class="num mt-2 text-sm"><strong>${eur(g.progress_cents)}</strong> <span class="text-muted">/ ${eur(g.target_amount_cents)}</span></p>
          <div class="mt-2">${bar(g.percent, done ? "gain" : "brand")}</div>
          ${meta.length ? `<p class="mt-2 text-xs text-muted">${meta.join(" · ")}</p>` : ""}
        </button>`;
    }).join("");
  }

  async function loadGoals() {
    try {
      goals = (await api("GET", "/api/goals")).items;
      renderGoals();
    } catch (err) {
      toast(err.message, "error");
    }
  }

  const goalDialog = $("goal-dialog");
  const goalForm = $("goal-form");
  const GF = goalForm.elements;
  let editingGoal = null;

  function syncGoalAccount() {
    GF.current_amount.disabled = !!GF.account_id.value;
  }

  function openGoal(goal = null) {
    editingGoal = goal;
    goalForm.reset();
    AT.clearErrors(goalForm);
    $("goal-dialog-title").textContent = goal ? "Modifier l'objectif" : "Nouvel objectif";
    $("gl-delete").hidden = !goal;
    AT.fillSelect(GF.account_id, accounts.filter((a) => !a.archived), { placeholder: "Aucun (suivi manuel)" });
    if (goal) {
      GF.name.value = goal.name;
      GF.target_amount.value = AT.toInput(goal.target_amount_cents);
      GF.deadline.value = goal.deadline || "";
      GF.account_id.value = goal.account_id || "";
      GF.current_amount.value = AT.toInput(goal.current_amount_cents);
    }
    syncGoalAccount();
    goalDialog.showModal();
    GF.name.focus();
  }

  GF.account_id.addEventListener("change", syncGoalAccount);

  goalForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = {
      name: GF.name.value,
      target_amount: GF.target_amount.value,
      deadline: GF.deadline.value || null,
      account_id: GF.account_id.value || null,
    };
    if (!GF.current_amount.disabled) body.current_amount = GF.current_amount.value || "0";
    try {
      await api(editingGoal ? "PATCH" : "POST", editingGoal ? `/api/goals/${editingGoal.id}` : "/api/goals", body);
      goalDialog.close();
      toast("Objectif enregistré.");
      loadGoals();
    } catch (err) {
      AT.showErrors(goalForm, err);
    }
  });

  $("gl-delete").addEventListener("click", async () => {
    if (!editingGoal || !(await AT.confirm(`Supprimer l'objectif « ${editingGoal.name} » ?`, { confirmLabel: "Supprimer" }))) return;
    try {
      await api("DELETE", `/api/goals/${editingGoal.id}`);
      goalDialog.close();
      toast("Objectif supprimé.");
      loadGoals();
    } catch (err) {
      toast(err.message, "error");
    }
  });

  // ======================================================================= événements

  $("month-prev").addEventListener("click", () => { month = AT.shiftMonth(month, -1); loadBudgets(); });
  $("month-next").addEventListener("click", () => { month = AT.shiftMonth(month, 1); loadBudgets(); });
  $("month-today").addEventListener("click", () => { month = thisMonth; loadBudgets(); });
  $("btn-new-budget").addEventListener("click", () => openBudget());
  $("btn-new-goal").addEventListener("click", () => openGoal());
  $("budget-list").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-budget]");
    if (btn) openBudget(data.items.find((b) => b.id === Number(btn.dataset.budget)));
  });
  $("unbudgeted-list").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-quick]");
    if (btn) openBudget(null, { category_id: btn.dataset.quick, spent: Number(btn.dataset.spent) });
  });
  $("goal-list").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-goal]");
    if (btn) openGoal(goals.find((g) => g.id === Number(btn.dataset.goal)));
  });
  [budgetDialog, goalDialog].forEach((d) => {
    AT.closeOnBackdrop(d);
    d.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => d.close()));
  });

  (async () => {
    try {
      const [cat, acc] = await Promise.all([api("GET", "/api/categories"), api("GET", "/api/accounts")]);
      categories = cat.items;
      accounts = acc.items;
    } catch (err) {
      toast(err.message, "error");
    }
    loadBudgets();
    loadGoals();
  })();
})();
