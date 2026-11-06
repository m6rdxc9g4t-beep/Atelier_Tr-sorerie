// Rapport d'import, partagé par la page Transactions (après un import) et la page Imports & règles.
// Expose AT.importReport.render(container, report, { onUndo, onClose }) et AT.SOURCES.
(function () {
  "use strict";
  const { esc, eur, api, toast } = AT;

  // Origine d'une catégorie : libellé court + style du badge
  AT.SOURCES = {
    regle: ["Règle", "badge-gain", "Une de vos règles"],
    fichier: ["Relevé", "", "Catégorie fournie par la banque"],
    historique: ["Historique", "", "Comme vos opérations précédentes"],
    defaut: ["Connu", "", "Commerçant reconnu"],
    ia: ["IA", "badge-warn", "Proposée par l'IA : à vérifier"],
    virement: ["Virement", "", "Virement entre vos comptes"],
    manuel: ["Manuel", "badge-gain", "Choisie par vous"],
    aucune: ["À classer", "badge-loss", "Aucune catégorie trouvée"],
  };
  AT.sourceBadge = (source) => {
    const [label, cls, title] = AT.SOURCES[source || "aucune"] || AT.SOURCES.aucune;
    return `<span class="badge ${cls}" title="${esc(title)}">${esc(label)}</span>`;
  };

  const FREQ = { hebdomadaire: "chaque semaine", mensuel: "chaque mois", trimestriel: "chaque trimestre", annuel: "chaque année" };
  AT.FREQ = FREQ;

  function kpi(label, value, cls = "") {
    return `<div class="rounded-xl border border-line p-4">
      <p class="text-xs font-medium text-muted">${label}</p>
      <p class="num mt-1 text-xl font-extrabold ${cls}">${value}</p></div>`;
  }

  function section(title, body, hint = "") {
    return `<section class="space-y-3">
      <h3 class="font-bold">${title}${hint ? ` <span class="text-sm font-normal text-muted">${hint}</span>` : ""}</h3>${body}</section>`;
  }

  function categoryBars(items, total) {
    return `<ul class="space-y-3">${items.map((c) => {
      const pct = total ? Math.round((Math.abs(c.amount_cents) / Math.abs(total)) * 100) : 0;
      return `<li>
        <div class="mb-1 flex items-center justify-between gap-3 text-sm">
          <span class="flex min-w-0 items-center gap-2"><span class="h-2.5 w-2.5 flex-none rounded-full" style="background:${esc(c.color || "var(--muted)")}"></span>
            <span class="truncate">${esc(c.name)}</span><span class="text-xs text-muted">${c.count} op.</span></span>
          <span class="num whitespace-nowrap font-semibold">${eur(Math.abs(c.amount_cents))} <span class="text-xs font-normal text-muted">${pct} %</span></span>
        </div>
        <div class="progress"><span style="width:${pct}%;background:${esc(c.color || "var(--muted)")}"></span></div>
      </li>`;
    }).join("")}</ul>`;
  }

  function render(container, r, { onUndo = null, onClose = null } = {}) {
    const b = r.batch;
    const debits = r.recurring.filter((i) => i.direction === "debit");
    const parts = [];

    parts.push(`<div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <p class="text-sm text-muted">${esc(b.filename)} · ${esc(b.account_name)} · importé le ${AT.date(b.created_at.slice(0, 10))}</p>
        ${r.period.start ? `<p class="mt-0.5 font-semibold">Du ${AT.date(r.period.start)} au ${AT.date(r.period.end)}</p>` : ""}
      </div>
      <div class="flex flex-wrap gap-2">
        <a class="btn btn-ghost btn-sm" href="/transactions?import_batch_id=${b.id}">Voir les opérations</a>
        ${onUndo ? '<button type="button" class="btn btn-danger btn-sm" data-undo>Annuler cet import</button>' : ""}
      </div></div>`);

    if (r.highlights.length) {
      parts.push(`<ul class="space-y-1.5 rounded-xl bg-brand/10 p-4 text-sm">${r.highlights.map((h) => `<li class="flex gap-2"><span aria-hidden="true">•</span><span>${esc(h)}</span></li>`).join("")}</ul>`);
    }

    parts.push(`<div class="grid grid-cols-2 gap-3 md:grid-cols-4">
      ${kpi("Entrées", eur(r.income_cents), "text-gain")}
      ${kpi("Sorties", eur(Math.abs(r.expense_cents)), "text-loss")}
      ${kpi("Solde de la période", eur(r.net_cents, { signed: true }), AT.amountClass(r.net_cents))}
      ${kpi("Solde du compte", r.balance_cents === null ? "—" : eur(r.balance_cents))}
    </div>`);

    const cols = [];
    if (r.expenses_by_category.length) cols.push(section("Où part l'argent", categoryBars(r.expenses_by_category, r.expense_cents)));
    if (r.income_by_category.length) cols.push(section("D'où il vient", categoryBars(r.income_by_category, r.income_cents)));
    if (cols.length) parts.push(`<div class="grid grid-cols-1 gap-6 lg:grid-cols-2">${cols.join("")}</div>`);

    parts.push(section("Comment les opérations ont été classées",
      `<div class="flex flex-wrap gap-2">${r.sources.map((s) => `<span class="inline-flex items-center gap-1.5">${AT.sourceBadge(s.source)}<span class="num text-sm">${s.count}</span></span>`).join("")}</div>
       ${r.uncategorized ? `<p class="text-sm text-muted">${r.uncategorized} opération(s) restent à classer : utilisez le filtre « Non catégorisées » ou l'Assistant IA.</p>` : ""}`));

    if (r.unusual.length) {
      parts.push(section("À vérifier", `<ul class="divide-y divide-line rounded-xl border border-line">${r.unusual.map((u) => `
        <li class="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
          <span class="min-w-0"><span class="block truncate font-semibold">${esc(u.merchant)}</span>
          <span class="text-xs text-muted">${AT.date(u.date)} · ${esc(u.reason)}</span></span>
          <span class="num whitespace-nowrap font-semibold text-loss">${eur(u.amount_cents)}</span></li>`).join("")}</ul>`, "montants inhabituels"));
    }

    if (debits.length || r.recurring.length) {
      parts.push(section("Échéances récurrentes", `<ul class="divide-y divide-line rounded-xl border border-line">${r.recurring.map((i) => `
        <li class="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
          <span class="min-w-0"><span class="block truncate font-semibold">${esc(i.merchant)}</span>
          <span class="text-xs text-muted">${FREQ[i.frequency] || i.frequency}${i.fixed ? "" : " · montant variable"} · prochaine vers le ${AT.date(i.next_date)}</span></span>
          <span class="num whitespace-nowrap font-semibold ${AT.amountClass(i.amount_cents)}">${eur(i.amount_cents, { signed: true })}</span></li>`).join("")}</ul>`,
      debits.length ? `${eur(Math.abs(debits.reduce((s, i) => s + i.monthly_cents, 0)))} de prélèvements par mois` : ""));
    }

    if (r.transfers.length) {
      parts.push(section("Virements entre vos comptes", `<ul class="space-y-1 text-sm">${r.transfers.map((t) => `
        <li class="flex justify-between gap-3"><span class="truncate">${AT.date(t.date)} · ${esc(t.label)} <span class="text-muted">↔ ${esc(t.transfer_account || "autre compte")}</span></span>
        <span class="num whitespace-nowrap">${eur(t.amount_cents, { signed: true })}</span></li>`).join("")}</ul>`, "exclus des revenus et dépenses"));
    }

    if (r.new_merchants.length) {
      parts.push(section("Nouveaux commerçants", `<div class="flex flex-wrap gap-2">${r.new_merchants.map((m) => `
        <span class="chip text-sm" title="${esc(m.category_name || "À classer")}">${esc(m.merchant)} <span class="num text-muted">${eur(m.amount_cents)}</span></span>`).join("")}</div>`,
      r.new_merchants_count > r.new_merchants.length ? `${r.new_merchants_count} au total` : ""));
    }

    parts.push(`<section class="rounded-xl border border-line p-4">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div><h3 class="font-bold">L'avis de l'assistant</h3>
          <p class="text-sm text-muted">Un résumé en quelques points de ce relevé, par votre moteur d'IA.</p></div>
        <button type="button" class="btn btn-ghost btn-sm" data-explain>Demander à l'IA</button>
      </div>
      <div data-explain-out class="mt-3 hidden text-sm leading-relaxed"></div>
    </section>`);

    container.innerHTML = `<div class="space-y-6">${parts.join("")}</div>`;

    container.querySelector("[data-undo]")?.addEventListener("click", async () => {
      const ok = await AT.confirm(`Annuler cet import ? Ses ${r.count} opération(s) seront supprimées, y compris si vous les avez modifiées depuis.`,
        { confirmLabel: "Annuler l'import" });
      if (!ok) return;
      try {
        const res = await api("DELETE", `/api/imports/${b.id}`);
        toast(`Import annulé : ${res.deleted} opération(s) supprimée(s).`);
        onUndo && onUndo(res);
      } catch (err) { toast(err.message, "error"); }
    });

    container.querySelector("[data-explain]").addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      const out = container.querySelector("[data-explain-out]");
      btn.disabled = true;
      btn.textContent = "L'IA réfléchit…";
      try {
        const res = await api("POST", `/api/imports/${b.id}/explain`, {});
        out.innerHTML = AT.markdown(res.text) + `<p class="mt-2 text-xs text-muted">${esc(res.label)} · ${res.local ? "calculé sur votre Mac" : "seuls des totaux par catégorie ont été envoyés"}</p>`;
        out.classList.remove("hidden");
        btn.textContent = "Redemander";
      } catch (err) {
        toast(err.message, "error");
        btn.textContent = "Demander à l'IA";
      } finally { btn.disabled = false; }
    });
    if (onClose) container.querySelector("[data-close-report]")?.addEventListener("click", onClose);
  }

  AT.importReport = { render };
})();
