// Tableau de bord : indicateurs, évolution du patrimoine, dépenses par catégorie, opérations, budgets
(function () {
  "use strict";
  const { esc, eur, api, toast } = AT;
  const $ = (id) => document.getElementById(id);

  const FONT = "Manrope, system-ui, sans-serif";
  const compact = new Intl.NumberFormat("fr-FR", { notation: "compact", maximumFractionDigits: 1 });
  const state = { data: null, months: 6, trend: "networth", charts: {} };

  /** Couleurs lues dans les jetons CSS : les graphiques suivent le thème clair / sombre. */
  function tokens() {
    const css = getComputedStyle(document.documentElement);
    const rgb = (name, alpha = 1) => `rgb(${css.getPropertyValue(`--${name}`).trim()} / ${alpha})`;
    return {
      ink: rgb("ink"), muted: rgb("muted"), line: rgb("line", 0.7), surface: rgb("surface"),
      // Courbe du patrimoine = donnée clé, en couleur signature (version lisible : éclaircie en sombre)
      brand: rgb("brand-text"), brandFill: rgb("brand", 0.14), gain: rgb("gain"), loss: rgb("loss"), lilac: rgb("lilac"),
    };
  }

  // ======================================================================= indicateurs

  function delta(el, value, { suffix = " %", goodWhenUp = true, label }) {
    if (value === null || value === undefined) { el.textContent = label ? `— ${label}` : ""; return; }
    const up = value > 0;
    const good = value === 0 ? null : up === goodWhenUp;
    const arrow = value === 0 ? "=" : up ? "▲" : "▼";
    const tone = good === null ? "text-muted" : good ? "text-gain" : "text-loss";
    const number = Math.abs(value).toLocaleString("fr-FR", { maximumFractionDigits: 1 });
    el.innerHTML = `<span class="${tone} font-semibold">${arrow} ${number}${suffix}</span> <span>${esc(label)}</span>`;
  }

  function renderKpis() {
    const { kpis: k, previous_month_label: prev, comparison_day: day } = state.data;
    const set = (id, text, cls = "") => {
      const v = $(`kpi-${id}`).querySelector("[data-value]");
      v.textContent = text;
      v.className = `num mt-2 text-2xl font-extrabold tracking-tight sm:text-3xl ${cls}`;
    };
    const atDate = `vs ${prev} (au ${day})`;
    set("networth", eur(k.net_worth_cents), k.net_worth_cents < 0 ? "text-loss" : "");
    $("kpi-networth").querySelector("[data-delta]").innerHTML =
      `<span class="${k.net_worth_change_cents >= 0 ? "text-gain" : "text-loss"} font-semibold">${eur(k.net_worth_change_cents, { signed: true })}</span> depuis fin ${esc(prev)}`;
    set("income", eur(k.income_cents), "text-gain");
    delta($("kpi-income").querySelector("[data-delta]"), k.income_change_percent, { label: atDate });
    set("expense", eur(-k.expense_cents), "text-loss");
    delta($("kpi-expense").querySelector("[data-delta]"), k.expense_change_percent, { label: atDate, goodWhenUp: false });
    set("savings", k.savings_rate === null ? "—" : `${k.savings_rate.toLocaleString("fr-FR")} %`, "text-brand");
    delta($("kpi-savings").querySelector("[data-delta]"), k.savings_rate_change, {
      suffix: " pt", label: k.savings_rate === null ? "aucun revenu ce mois-ci" : atDate,
    });
    $("as-of").textContent = `Données au ${AT.date(state.data.today)}`;
  }

  // ======================================================================= graphique d'évolution

  // Ligne verticale qui suit le pointeur : on vise une date, pas une ligne de 2 px
  const crosshair = {
    id: "crosshair",
    afterDatasetsDraw(chart) {
      const active = chart.tooltip?.getActiveElements?.() || [];
      if (!active.length || chart.config.type !== "line") return;
      const { ctx, chartArea } = chart;
      const x = active[0].element.x;
      ctx.save();
      ctx.strokeStyle = tokens().muted;
      ctx.globalAlpha = 0.5;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, chartArea.top);
      ctx.lineTo(x, chartArea.bottom);
      ctx.stroke();
      ctx.restore();
    },
  };

  function baseOptions(t) {
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 300 },
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false }, // légende HTML au-dessus (texte en couleur d'encre)
        tooltip: {
          backgroundColor: t.surface, titleColor: t.muted, bodyColor: t.ink, borderColor: t.line, borderWidth: 1,
          padding: 10, boxWidth: 12, boxHeight: 2, usePointStyle: false,
          bodyFont: { family: FONT, weight: "600" }, titleFont: { family: FONT },
          callbacks: { label: (ctx) => ` ${eur(Math.round(ctx.parsed.y * 100))}  ${ctx.dataset.label}` },
        },
      },
      scales: {
        x: { grid: { display: false }, border: { color: t.line }, ticks: { color: t.muted, font: { family: FONT } } },
        y: {
          grid: { color: t.line, drawTicks: false }, border: { display: false },
          ticks: { color: t.muted, padding: 8, font: { family: FONT }, callback: (v) => `${compact.format(v)} €` },
        },
      },
    };
  }

  function legend(items) {
    $("trend-legend").innerHTML = items.map((i) => `
      <span class="flex items-center gap-2 text-muted">
        <span class="inline-block ${i.kind === "bar" ? "h-2.5 w-2.5 rounded-sm" : "h-0.5 w-4 rounded"}" style="background:${i.color}${i.dashed ? ";background:repeating-linear-gradient(90deg," + i.color + " 0 4px,transparent 4px 7px)" : ""}"></span>
        <span class="text-ink">${esc(i.label)}</span>
      </span>`).join("");
  }

  function renderTrend() {
    const t = tokens();
    const h = state.data.history;
    const labels = h.map((m) => (m.partial ? `${m.label}*` : m.label));
    state.charts.trend?.destroy();
    const canvas = $("trend-chart");
    let config;

    if (state.trend === "networth") {
      $("trend-title").textContent = "Évolution du patrimoine";
      const hasInvest = h.some((m) => m.investments_cents);
      const datasets = [{
        label: "Patrimoine total", data: h.map((m) => m.total_cents / 100),
        borderColor: t.brand, backgroundColor: t.brandFill, fill: true, borderWidth: 2, tension: 0.3,
        pointRadius: 0, pointHoverRadius: 5, pointHoverBorderWidth: 2, pointHoverBorderColor: t.surface, pointHoverBackgroundColor: t.brand,
      }];
      if (hasInvest) {
        datasets.push({
          label: "dont liquidités", data: h.map((m) => m.cash_cents / 100),
          borderColor: t.muted, borderDash: [5, 4], borderWidth: 2, tension: 0.3, fill: false,
          pointRadius: 0, pointHoverRadius: 4, pointHoverBackgroundColor: t.muted,
        });
      }
      legend([{ label: "Patrimoine total", color: t.brand }, ...(hasInvest ? [{ label: "dont liquidités", color: t.muted, dashed: true }] : [])]);
      config = { type: "line", data: { labels, datasets }, options: baseOptions(t), plugins: [crosshair] };
      config.options.scales.y.grace = "5%";
      renderTable(["Mois", "Patrimoine", "Liquidités", "Placements"],
        h.map((m) => [labels[h.indexOf(m)], eur(m.total_cents), eur(m.cash_cents), eur(m.investments_cents)]));
    } else {
      $("trend-title").textContent = "Revenus et dépenses";
      const bar = { borderRadius: 4, borderSkipped: "start", maxBarThickness: 28, borderWidth: 0 };
      config = {
        type: "bar",
        data: {
          labels,
          datasets: [
            { ...bar, label: "Revenus", data: h.map((m) => m.income_cents / 100), backgroundColor: t.gain },
            { ...bar, label: "Dépenses", data: h.map((m) => -m.expense_cents / 100), backgroundColor: t.loss },
          ],
        },
        options: { ...baseOptions(t), datasets: { bar: { categoryPercentage: 0.6, barPercentage: 0.85 } } },
      };
      config.options.scales.y.beginAtZero = true;
      legend([{ label: "Revenus", color: t.gain, kind: "bar" }, { label: "Dépenses", color: t.loss, kind: "bar" }]);
      renderTable(["Mois", "Revenus", "Dépenses", "Solde"],
        h.map((m, i) => [labels[i], eur(m.income_cents), eur(-m.expense_cents), eur(m.income_cents + m.expense_cents, { signed: true })]));
    }
    canvas.setAttribute("aria-label", $("trend-title").textContent);
    state.charts.trend = new Chart(canvas, config);
  }

  function renderTable(head, rows) {
    const partial = state.data.history.some((m) => m.partial);
    $("trend-table").innerHTML = `
      <thead><tr>${head.map((x, i) => `<th class="${i ? "text-right" : ""}">${esc(x)}</th>`).join("")}</tr></thead>
      <tbody>${rows.map((r) => `<tr>${r.map((c, i) => `<td class="num ${i ? "text-right" : ""}">${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody>
      ${partial ? `<caption class="caption-bottom pt-2 text-left text-xs text-muted">* mois en cours, arrêté au ${AT.date(state.data.today)}</caption>` : ""}`;
  }

  // ======================================================================= dépenses par catégorie

  function renderDonut() {
    const t = tokens();
    const c = state.data.categories;
    $("donut-month").textContent = AT.monthLabel(c.month);
    $("donut-total").textContent = eur(c.total_cents);
    state.charts.donut?.destroy();
    if (!c.items.length) {
      $("donut-legend").innerHTML = '<li class="text-muted">Aucune dépense ce mois-ci.</li>';
      return;
    }
    state.charts.donut = new Chart($("donut-chart"), {
      type: "doughnut",
      data: {
        labels: c.items.map((i) => i.name),
        datasets: [{
          data: c.items.map((i) => i.amount_cents / 100),
          backgroundColor: c.items.map((i) => i.color),
          borderColor: t.surface, borderWidth: 2, hoverOffset: 6, hoverBorderColor: t.surface,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: "72%",
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: t.surface, titleColor: t.muted, bodyColor: t.ink, borderColor: t.line, borderWidth: 1, padding: 10,
            bodyFont: { family: FONT, weight: "600" },
            callbacks: { label: (ctx) => ` ${eur(Math.round(ctx.parsed * 100))} · ${c.items[ctx.dataIndex].percent.toLocaleString("fr-FR")} %` },
          },
        },
      },
    });
    // Légende = étiquettes directes : l'identité ne repose jamais sur la seule couleur
    $("donut-legend").innerHTML = c.items.map((i) => {
      const href = i.other ? `/transactions?month=${c.month}&type=expense`
        : `/transactions?month=${c.month}&category_id=${i.category_id ?? "none"}`;
      return `<li><a class="flex items-center justify-between gap-3 rounded-lg px-1 py-0.5 hover:bg-raised/60" href="${href}">
        <span class="flex min-w-0 items-center gap-2"><span class="h-2.5 w-2.5 shrink-0 rounded-sm" style="background:${esc(i.color)}"></span>
          <span class="truncate">${esc(i.name)}</span></span>
        <span class="num shrink-0"><strong>${eur(i.amount_cents)}</strong> <span class="text-muted">${Math.round(i.percent)} %</span></span>
      </a></li>`;
    }).join("");
  }

  // ======================================================================= opérations & budgets

  function renderRecent() {
    const items = state.data.recent;
    $("recent").innerHTML = items.length ? items.map((t) => `
      <tr>
        <td class="num hidden w-28 whitespace-nowrap pl-6 text-muted sm:table-cell">${AT.date(t.date)}</td>
        <td class="max-w-[13rem] pl-6 sm:max-w-[20rem] sm:pl-3"><p class="truncate font-semibold">${esc(t.label)}</p>
          <p class="truncate text-xs text-muted"><span class="sm:hidden">${AT.date(t.date)} · </span>${esc(t.account_name)}</p></td>
        <td class="hidden sm:table-cell">${t.category_id
          ? `<span class="badge"><span class="dot" style="background:${esc(t.category_color)}"></span>${esc(t.category_name)}</span>`
          : '<span class="badge text-muted">Non catégorisée</span>'}</td>
        <td class="num whitespace-nowrap pr-6 text-right font-bold ${AT.amountClass(t.amount_cents)}">${eur(t.amount_cents, { signed: true })}</td>
      </tr>`).join("")
      : '<tr><td class="px-6 py-8 text-center text-muted">Aucune opération pour le moment.</td></tr>';
  }

  function renderBudgets() {
    const b = state.data.budgets;
    if (!b.count) {
      $("budgets").innerHTML = `<p class="text-sm text-muted">Aucun budget ce mois-ci.
        <a class="font-semibold text-brand hover:underline" href="/budgets">Fixer des plafonds</a> pour suivre vos dépenses.</p>`;
      return;
    }
    const tone = (s) => ({ ok: "gain", attention: "warn", depasse: "loss" })[s];
    const pctTotal = b.total_limit_cents ? Math.round((b.total_spent_cents / b.total_limit_cents) * 100) : 0;
    $("budgets").innerHTML = `
      <p class="num text-sm"><strong>${eur(b.total_spent_cents)}</strong> <span class="text-muted">sur ${eur(b.total_limit_cents)} budgétés · ${pctTotal} %</span></p>
      ${b.items.map((i) => `
        <div>
          <div class="flex items-center justify-between gap-2 text-sm">
            <span class="truncate font-semibold">${esc(i.category_name)}</span>
            <span class="num shrink-0 text-xs text-muted">${eur(i.spent_cents)} / ${eur(i.amount_limit_cents)}</span>
          </div>
          <div class="progress mt-1.5"><span style="width:${Math.min(100, i.percent || 0)}%;background:rgb(var(--${tone(i.status)}))"></span></div>
          ${i.status === "depasse" ? `<p class="mt-1 text-xs font-semibold text-loss">⚠ Dépassé de ${eur(-i.remaining_cents)}</p>` : ""}
        </div>`).join("")}
      ${b.count > b.items.length ? `<p class="text-xs text-muted">+ ${b.count - b.items.length} autre(s) budget(s)</p>` : ""}`;
  }

  // ======================================================================= chargement

  function renderAll() {
    Chart.defaults.font.family = FONT;
    renderKpis();
    renderTrend();
    renderDonut();
    renderRecent();
    renderBudgets();
  }

  async function load() {
    const box = $("dashboard");
    box.style.opacity = state.data ? "0.6" : "1"; // on garde l'affichage pendant le rechargement
    try {
      state.data = await api("GET", `/api/dashboard?months=${state.months}`);
      if (typeof Chart === "undefined") {
        toast("Les graphiques n'ont pas pu se charger (connexion Internet nécessaire pour Chart.js).", "error");
        renderKpis(); renderRecent(); renderBudgets();
      } else {
        renderAll();
      }
    } catch (err) {
      toast(err.message, "error");
    } finally {
      box.style.opacity = "1";
    }
  }

  document.querySelectorAll('input[name="months"]').forEach((r) => r.addEventListener("change", () => {
    state.months = Number(r.value);
    load();
  }));
  document.querySelectorAll('input[name="trend"]').forEach((r) => r.addEventListener("change", () => {
    state.trend = r.value;
    renderTrend();
  }));
  // Changement de thème : les couleurs des graphiques sont relues dans les jetons CSS
  document.addEventListener("themechange", () => { if (state.data && typeof Chart !== "undefined") { renderTrend(); renderDonut(); } });

  load();
})();
