// Page Comptes & Soldes
(function () {
  "use strict";
  const { esc, eur, api, toast } = AT;

  const TYPE_ORDER = ["courant", "epargne", "investissement", "credit", "especes"];
  const TYPE_TITLES = {
    courant: "Comptes courants", epargne: "Épargne", investissement: "Investissements",
    credit: "Crédits", especes: "Espèces",
  };

  const groupsEl = document.getElementById("accounts-groups");
  const totalEl = document.getElementById("total-balance");
  const archivedToggle = document.getElementById("show-archived");
  const dialog = document.getElementById("account-dialog");
  const form = document.getElementById("account-form");
  const transferDialog = document.getElementById("transfer-dialog");
  const transferForm = document.getElementById("transfer-form");

  let accounts = [];
  let editing = null;

  // ------------------------------------------------------------------ rendu

  function accountCard(a) {
    const color = a.color || "#a5b4fc";
    const last = a.last_transaction_date ? `Dernière opération : ${AT.date(a.last_transaction_date)}` : "Aucune opération";
    return `
      <article class="card group relative overflow-hidden p-5 ${a.archived ? "opacity-60" : ""}">
        <span class="absolute inset-x-0 top-0 h-1" style="background:${esc(color)}"></span>
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <h3 class="truncate font-bold">${esc(a.name)}</h3>
            <p class="truncate text-sm text-muted">${esc(a.type_label)}${a.institution ? ` · ${esc(a.institution)}` : ""}</p>
          </div>
          <button class="icon-btn h-9 w-9 shrink-0" data-edit="${a.id}" aria-label="Modifier ${esc(a.name)}">
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h4L18.5 9.5a2.1 2.1 0 0 0-4-4L4 16v4zM13.5 6.5l4 4"/></svg>
          </button>
        </div>
        <p class="num mt-5 text-2xl font-extrabold tracking-tight ${a.balance_cents < 0 ? "text-loss" : ""}">${eur(a.balance_cents)}</p>
        <div class="mt-4 flex items-center justify-between gap-2 text-xs text-muted">
          <span class="truncate">${esc(last)}</span>
          <a class="shrink-0 font-semibold text-brand hover:underline" href="/transactions?account_id=${a.id}">
            ${a.transaction_count} opération${a.transaction_count > 1 ? "s" : ""} →
          </a>
        </div>
        ${a.archived ? '<span class="badge mt-3">Archivé</span>' : ""}
      </article>`;
  }

  function render() {
    const active = accounts.filter((a) => !a.archived);
    totalEl.textContent = eur(active.reduce((s, a) => s + a.balance_cents, 0));
    totalEl.classList.toggle("text-loss", active.reduce((s, a) => s + a.balance_cents, 0) < 0);

    if (!accounts.length) {
      groupsEl.innerHTML = `
        <div class="card mx-auto max-w-lg p-10 text-center">
          <p class="text-lg font-bold">Aucun compte pour le moment</p>
          <p class="mt-2 text-muted">Créez votre premier compte pour commencer à suivre vos opérations.</p>
          <button class="btn btn-primary mt-6" data-new>Créer un compte</button>
        </div>`;
      return;
    }
    // Répartition par type, puis une seule grille de cartes (compacte même avec peu de comptes)
    const types = TYPE_ORDER.filter((type) => accounts.some((a) => a.type === type && !a.archived));
    const breakdown = types.map((type) => {
      const subtotal = accounts.filter((a) => a.type === type && !a.archived).reduce((s, a) => s + a.balance_cents, 0);
      return `<span class="chip"><span class="font-semibold text-ink">${TYPE_TITLES[type]}</span>
        <span class="num ml-1">${eur(subtotal)}</span></span>`;
    }).join("");
    const sorted = [...accounts].sort((a, b) =>
      a.archived - b.archived || TYPE_ORDER.indexOf(a.type) - TYPE_ORDER.indexOf(b.type) || a.name.localeCompare(b.name));
    groupsEl.innerHTML = `
      <div class="flex flex-wrap gap-2">${breakdown}</div>
      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">${sorted.map(accountCard).join("")}</div>`;
  }

  async function load() {
    try {
      const data = await api("GET", `/api/accounts${archivedToggle.checked ? "?archived=1" : ""}`);
      accounts = data.items;
      render();
    } catch (err) {
      groupsEl.innerHTML = `<p class="text-loss">${esc(err.message)}</p>`;
    }
  }

  // ------------------------------------------------------------------ formulaire compte

  document.getElementById("acc-colors").innerHTML = AT.PASTELS.map((c, i) => `
    <label class="relative">
      <input type="radio" name="color" value="${c}" class="swatch-input" ${i === 0 ? "checked" : ""}>
      <span class="swatch block" style="background:${c}" title="${c}"></span>
    </label>`).join("");

  function openAccount(account = null) {
    editing = account;
    form.reset();
    AT.clearErrors(form);
    document.getElementById("account-dialog-title").textContent = account ? "Modifier le compte" : "Nouveau compte";
    document.getElementById("acc-delete").hidden = !account;
    document.getElementById("acc-archived-row").hidden = !account;
    if (account) {
      form.elements.name.value = account.name;
      form.elements.type.value = account.type;
      form.elements.institution.value = account.institution || "";
      form.elements.opening_balance.value = AT.toInput(account.opening_balance_cents);
      form.elements.archived.checked = account.archived;
      const swatch = form.querySelector(`input[name="color"][value="${account.color}"]`);
      if (swatch) swatch.checked = true;
    }
    dialog.showModal();
    form.elements.name.focus();
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = {
      name: form.elements.name.value,
      type: form.elements.type.value,
      institution: form.elements.institution.value,
      opening_balance: form.elements.opening_balance.value || "0",
      color: form.elements.color.value,
    };
    if (editing) body.archived = form.elements.archived.checked;
    try {
      await api(editing ? "PATCH" : "POST", editing ? `/api/accounts/${editing.id}` : "/api/accounts", body);
      dialog.close();
      toast(editing ? "Compte mis à jour." : "Compte créé.");
      load();
    } catch (err) {
      AT.showErrors(form, err);
    }
  });

  document.getElementById("acc-delete").addEventListener("click", async () => {
    if (!editing) return;
    const n = editing.transaction_count;
    const message = n
      ? `Supprimer « ${editing.name} » et ses ${n} opération(s) ? Cette action est définitive. Pour garder l'historique, archivez plutôt le compte.`
      : `Supprimer le compte « ${editing.name} » ?`;
    if (!(await AT.confirm(message, { confirmLabel: "Supprimer" }))) return;
    try {
      await api("DELETE", `/api/accounts/${editing.id}${n ? "?force=1" : ""}`);
      dialog.close();
      toast("Compte supprimé.");
      load();
    } catch (err) {
      toast(err.message, "error");
    }
  });

  // ------------------------------------------------------------------ virement

  function openTransfer() {
    const active = accounts.filter((a) => !a.archived);
    if (active.length < 2) {
      toast("Il faut au moins deux comptes actifs pour faire un virement.", "error");
      return;
    }
    transferForm.reset();
    AT.clearErrors(transferForm);
    AT.fillSelect(transferForm.from_account_id, active);
    AT.fillSelect(transferForm.to_account_id, active);
    transferForm.to_account_id.selectedIndex = 1;
    transferForm.date.value = AT.today();
    transferDialog.showModal();
    transferForm.amount.focus();
  }

  transferForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("POST", "/api/transfers", Object.fromEntries(new FormData(transferForm)));
      transferDialog.close();
      toast("Virement enregistré.");
      load();
    } catch (err) {
      AT.showErrors(transferForm, err);
    }
  });

  // ------------------------------------------------------------------ événements

  document.getElementById("btn-new-account").addEventListener("click", () => openAccount());
  document.getElementById("btn-transfer").addEventListener("click", openTransfer);
  archivedToggle.addEventListener("change", load);
  groupsEl.addEventListener("click", (e) => {
    const edit = e.target.closest("[data-edit]");
    if (edit) openAccount(accounts.find((a) => a.id === Number(edit.dataset.edit)));
    if (e.target.closest("[data-new]")) openAccount();
  });
  [dialog, transferDialog].forEach((d) => {
    AT.closeOnBackdrop(d);
    d.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => d.close()));
  });

  load();
})();
