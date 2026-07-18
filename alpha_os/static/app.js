const REGIME_LABELS = {
  bull_market_expansion: "Expansión alcista",
  bull_market_exhaustion: "Agotamiento alcista",
  sideways_range: "Rango lateral",
  bear_market_distribution: "Distribución bajista",
  bear_market_capitulation: "Capitulación bajista",
  risk_on: "Risk On",
  risk_off: "Risk Off",
  liquidity_expansion: "Liquidez en expansión",
  liquidity_contraction: "Liquidez en contracción",
};

const TREND_CLASS = {
  bull_market_expansion: "bull",
  bull_market_exhaustion: "bull",
  sideways_range: "sideways",
  bear_market_distribution: "bear",
  bear_market_capitulation: "bear",
};

function fmtPct(value, digits = 1) {
  if (value === null || value === undefined) return "—";
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

function fmtMoney(value) {
  if (value === null || value === undefined) return "—";
  return `$${value.toFixed(2)}`;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

function renderMarketPulse(regime) {
  const trendClass = TREND_CLASS[regime.trend_regime] || "sideways";
  const riskClass = regime.risk_regime === "risk_on" ? "risk-on" : "risk-off";
  const liqClass = regime.liquidity_regime === "liquidity_expansion" ? "expansion" : "contraction";

  const badges = `
    <div class="regime-badges">
      <span class="badge ${trendClass}"><span class="badge-dot ${trendClass}"></span>${REGIME_LABELS[regime.trend_regime] || regime.trend_regime}</span>
      <span class="badge ${riskClass}"><span class="badge-dot ${riskClass}"></span>${REGIME_LABELS[regime.risk_regime] || regime.risk_regime}</span>
      <span class="badge ${liqClass}"><span class="badge-dot ${liqClass}"></span>${REGIME_LABELS[regime.liquidity_regime] || regime.liquidity_regime}</span>
      ${regime.high_volatility_event ? '<span class="badge bear"><span class="badge-dot bear"></span>Alta volatilidad</span>' : ""}
    </div>`;

  const confidence = `<div class="confidence">Confianza del régimen: ${(regime.confidence * 100).toFixed(0)}% · referencia ${escapeHtml(regime.reference_index)}</div>`;

  const text = regime.justification.length
    ? `<div class="regime-text">${regime.justification.map((j) => `<p>${escapeHtml(j)}</p>`).join("")}</div>`
    : `<p class="empty-note">Sin justificación disponible.</p>`;

  document.getElementById("market-pulse").innerHTML = `
    <div class="card-heading">Market Pulse</div>
    ${badges}
    ${confidence}
    ${text}
  `;
}

function renderBrokerAccount(account) {
  const el = document.getElementById("broker-account");
  if (!account) {
    el.innerHTML = `
      <div class="card-heading">Cuenta IBKR</div>
      <p class="empty-note">Sin conexión a TWS/IB Gateway — corre la app localmente con la API habilitada para ver tu cuenta paper aquí.</p>
    `;
    return;
  }
  el.innerHTML = `
    <div class="card-heading">Cuenta IBKR ${account.is_paper_account ? '<span class="badge risk-on" style="margin-left:8px;"><span class="badge-dot risk-on"></span>Paper</span>' : '<span class="badge bear" style="margin-left:8px;"><span class="badge-dot bear"></span>Real</span>'}</div>
    <div class="levels" style="margin-top:0;">
      <div><span>Cuenta</span><b>${escapeHtml(account.account)}</b></div>
      <div><span>Liquidación neta</span><b>${fmtMoney(account.net_liquidation)}</b></div>
      <div><span>Cash</span><b>${fmtMoney(account.total_cash)}</b></div>
      <div><span>Poder de compra</span><b>${fmtMoney(account.buying_power)}</b></div>
    </div>
  `;
}

function renderBotActivity(lastRun) {
  const el = document.getElementById("bot-activity");
  const header = `
    <div class="card-top" style="margin-bottom:10px;">
      <div class="card-heading" style="margin:0;">Bot de trading diario</div>
      <button id="run-now-btn" class="btn-refresh">Ejecutar ahora</button>
    </div>`;

  if (!lastRun) {
    el.innerHTML = `${header}<p class="empty-note">Todavía no ha corrido. Corre una vez cada 24h automáticamente, o dale a "Ejecutar ahora".</p>`;
  } else {
    const when = new Date(lastRun.ran_at).toLocaleString("es-MX");
    const lines = lastRun.actions.length
      ? lastRun.actions.map((a) => `<div class="headline-item">${escapeHtml(a)}</div>`).join("")
      : `<p class="empty-note">Sin acciones en la última corrida.</p>`;
    el.innerHTML = `${header}<div class="confidence" style="margin-bottom:10px;">Última corrida: ${when}</div>${lines}`;
  }

  document.getElementById("run-now-btn").addEventListener("click", async (e) => {
    e.target.disabled = true;
    e.target.textContent = "Ejecutando…";
    try {
      const response = await fetch("/jobs/daily-trading/run-now", { method: "POST" });
      const result = await response.json();
      renderBotActivity(result);
    } catch (err) {
      e.target.disabled = false;
      e.target.textContent = "Ejecutar ahora";
      alert(`No se pudo ejecutar el bot: ${err.message}`);
    }
  });
}

function renderHeadlines(headlines) {
  const items = headlines.length
    ? headlines
        .map(
          (h) => `
        <div class="headline-item">
          <a href="${escapeHtml(h.url || "#")}" target="_blank" rel="noopener">${escapeHtml(h.claim)}</a>
          <span class="headline-source">${escapeHtml(h.source_name)}</span>
        </div>`
        )
        .join("")
    : `<p class="empty-note">Sin NEWSAPI_API_KEY configurada, o sin titulares disponibles ahora.</p>`;

  document.getElementById("headlines").innerHTML = `
    <div class="card-heading">Qué está moviendo el mercado</div>
    ${items}
  `;
}

function renderLearning(learning) {
  document.getElementById("learning").innerHTML = `
    <div class="card-heading">Aprendizaje continuo</div>
    <p class="learning-text">${escapeHtml(learning.rationale)}</p>
  `;
}

function renderPositions(positions) {
  const el = document.getElementById("positions");
  if (!positions.length) {
    el.innerHTML = `<p class="empty-note">No tienes posiciones abiertas registradas en AlphaOS.</p>`;
    return;
  }
  el.innerHTML = positions
    .map((p) => {
      const pnlClass = (p.floating_pnl_pct ?? 0) >= 0 ? "pos" : "neg";
      const thesis = p.thesis;
      const thesisBlock = thesis
        ? `
          <div class="thesis-status ${thesis.still_valid ? "valid" : "invalid"}">
            ${thesis.still_valid ? "✓ Tesis vigente" : "⚠ Tesis en duda"} (${fmtPct(thesis.success_probability_delta)})
          </div>
          <div class="thesis-text">${escapeHtml(thesis.what_changed)}</div>`
        : `<p class="empty-note">Sin reevaluación de tesis disponible.</p>`;

      return `
        <div class="position-card">
          <div class="card-top">
            <span class="ticker">${escapeHtml(p.ticker)}</span>
            <span class="pnl ${pnlClass}">${fmtPct(p.floating_pnl_pct)}</span>
          </div>
          <div class="price-line">${p.side.toUpperCase()} · entrada ${fmtMoney(p.entry_price)} → actual ${fmtMoney(p.current_price)}</div>
          ${thesisBlock}
        </div>`;
    })
    .join("");
}

function renderOpportunities(opportunities) {
  const el = document.getElementById("opportunities");
  if (!opportunities.length) {
    el.innerHTML = `<p class="empty-note">Ningún ticker del watchlist generó señal en este escaneo.</p>`;
    return;
  }
  el.innerHTML = opportunities
    .map((s, i) => `
        <div class="opp-card" data-idx="${i}">
          <div class="card-top">
            <span class="ticker">${escapeHtml(s.ticker)}</span>
            <span class="direction-badge ${s.direction}">${s.direction}</span>
          </div>
          <div class="conviction-label">Convicción</div>
          <div class="conviction">${s.conviction_score.toFixed(0)}</div>
          <div class="levels">
            <div><span>Entrada</span><b>${fmtMoney(s.suggested_entry)}</b></div>
            <div><span>SL</span><b>${fmtMoney(s.stop_loss)}</b></div>
            <div><span>TP</span><b>${fmtMoney((s.take_profit_targets || [])[0])}</b></div>
          </div>
        </div>`)
    .join("");

  el.querySelectorAll(".opp-card").forEach((card) => {
    card.addEventListener("click", () => openSignalDetail(opportunities[Number(card.dataset.idx)]));
  });
}

function openSignalDetail(signal) {
  const factors = signal.factors
    .slice()
    .sort((a, b) => Math.abs(b.weight_pct) - Math.abs(a.weight_pct))
    .map(
      (f) => `
      <div class="factor-row">
        <span class="factor-label">${escapeHtml(f.label)}</span>
        <span class="factor-weight ${f.weight_pct >= 0 ? "pos" : "neg"}">${fmtPct(f.weight_pct, 0)}</span>
        <div class="factor-rationale">${escapeHtml(f.rationale)}</div>
      </div>`
    )
    .join("");

  document.getElementById("modal-body").innerHTML = `
    <div class="card-heading">${escapeHtml(signal.ticker)} — ¿por qué esta señal?</div>
    <p class="regime-text">${escapeHtml(signal.rationale)}</p>
    <div class="section-title" style="margin-top:20px;">Factores</div>
    ${factors}
  `;
  document.getElementById("detail-modal").classList.remove("hidden");
}

function closeModal() {
  document.getElementById("detail-modal").classList.add("hidden");
}

async function loadBrief() {
  document.getElementById("loading").classList.remove("hidden");
  document.getElementById("content").classList.add("hidden");
  document.getElementById("error").classList.add("hidden");

  try {
    const response = await fetch("/brief");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const brief = await response.json();

    renderMarketPulse(brief.market_regime);
    renderBrokerAccount(brief.broker_account);
    renderHeadlines(brief.headlines);
    renderLearning(brief.learning);
    renderPositions(brief.open_positions);
    renderOpportunities(brief.opportunities);

    const lastRunResponse = await fetch("/jobs/daily-trading/last-run");
    renderBotActivity(lastRunResponse.ok ? await lastRunResponse.json() : null);

    document.getElementById("generated-at").textContent = new Date(brief.generated_at).toLocaleString("es-MX");
    document.getElementById("loading").classList.add("hidden");
    document.getElementById("content").classList.remove("hidden");
  } catch (err) {
    document.getElementById("loading").classList.add("hidden");
    const errEl = document.getElementById("error");
    errEl.textContent = `No se pudo cargar el brief: ${err.message}. ¿Está el servidor de AlphaOS corriendo?`;
    errEl.classList.remove("hidden");
  }
}

document.getElementById("refresh-btn").addEventListener("click", loadBrief);
document.getElementById("modal-close").addEventListener("click", closeModal);
document.querySelector(".modal-backdrop").addEventListener("click", closeModal);

loadBrief();
