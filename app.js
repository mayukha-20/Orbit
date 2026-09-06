/* ═══════════════════════════════════════════════════════════════
   Orbit — app.js  (complete rewrite)
   Features: onboarding panel · snapshot history chart · vol trend
             · badge tooltips · score explainer · data-delay note
═══════════════════════════════════════════════════════════════ */

const API = '';

// ── State ─────────────────────────────────────────────────────
let watchlistData  = [];
let calmExpanded   = false;
let historyCache   = {};   // { SYMBOL: [{price, ewma_volatility, taken_at}] }

// ── DOM refs ──────────────────────────────────────────────────
const symbolInput    = document.getElementById('symbol-input');
const btnAdd         = document.getElementById('btn-add');
const btnRefresh     = document.getElementById('btn-refresh');
const refreshIcon    = document.getElementById('refresh-icon');
const addFeedback    = document.getElementById('add-feedback');
const visitLabel     = document.getElementById('visit-label');
const visitChip      = document.getElementById('last-visit-banner');
const hTotal         = document.getElementById('h-total');
const hAlert         = document.getElementById('h-alert');
const hCalm          = document.getElementById('h-calm');
const loadingState   = document.getElementById('loading-state');
const emptyState     = document.getElementById('empty-state');
const digestAlert    = document.getElementById('digest-alert');
const digestCalm     = document.getElementById('digest-calm');
const cardsAlert     = document.getElementById('cards-alert');
const cardsCalm      = document.getElementById('cards-calm');
const btnToggleCalm  = document.getElementById('btn-toggle-calm');
const calmToggleLabel= document.getElementById('calm-toggle-label');
const searchDropdown = document.getElementById('search-dropdown');

// ── Boot ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  setupEvents();
  loadLastVisit();
  loadWatchlist();
  renderTooltip();
});

// ── Search state ──────────────────────────────────────────────
let searchResults   = [];
let searchActiveIdx = -1;
let searchDebounce  = null;

function setupEvents() {
  btnAdd.addEventListener('click', handleAdd);
  btnRefresh.addEventListener('click', loadWatchlist);
  if (btnToggleCalm) btnToggleCalm.addEventListener('click', toggleCalm);

  // Explainer panel toggle
  const explainerToggle = document.getElementById('explainer-toggle');
  const explainerPanel  = document.getElementById('explainer-panel');
  if (explainerToggle && explainerPanel) {
    explainerToggle.addEventListener('click', () => {
      const open = explainerPanel.classList.toggle('open');
      explainerToggle.setAttribute('aria-expanded', String(open));
    });
  }

  // Search autocomplete
  symbolInput.addEventListener('keydown', handleInputKeydown);
  symbolInput.addEventListener('input',   handleSearchInput);
  symbolInput.addEventListener('focus',   () => {
    if (symbolInput.value.trim().length >= 2) doSearch(symbolInput.value.trim());
  });
  document.addEventListener('click', e => {
    if (!e.target.closest('.add-form')) closeDropdown();
  });
}

function handleSearchInput() {
  const q = symbolInput.value.trim();
  clearFeedback();
  searchActiveIdx = -1;
  if (searchDebounce) clearTimeout(searchDebounce);
  if (q.length < 2) { closeDropdown(); return; }
  showDropdown();
  searchDropdown.innerHTML = `<div class="sr-loading"><div class="sr-spinner"></div>Searching…</div>`;
  searchDebounce = setTimeout(() => doSearch(q), 280);
}

async function doSearch(q) {
  try {
    const res = await fetch(`${API}/search?q=${encodeURIComponent(q)}`);
    searchResults = await res.json();
    renderDropdown(q, searchResults);
  } catch (_) { closeDropdown(); }
}

function renderDropdown(query, results) {
  if (!results.length) {
    showDropdown();
    searchDropdown.innerHTML = `<div class="sr-empty">No results for "<strong>${esc(query)}</strong>".<br>Try a different spelling, or type the ticker directly (e.g. <em>AAPL</em>).</div>`;
    return;
  }
  showDropdown();
  const html = results.map((r, idx) => {
    const typeCls = {EQUITY:'equity',ETF:'etf',CRYPTOCURRENCY:'crypto',MUTUALFUND:'mutual'}[r.type] || '';
    const typeLbl = {EQUITY:'Stock',ETF:'ETF',CRYPTOCURRENCY:'Crypto',MUTUALFUND:'Fund'}[r.type] || r.type;
    const nameHl  = highlightMatch(esc(r.name), query);
    return `
      <div class="search-result" role="option" data-idx="${idx}" data-symbol="${esc(r.symbol)}">
        <div class="sr-icon">${esc(r.symbol.slice(0,4))}</div>
        <div class="sr-info">
          <div class="sr-name">${nameHl}</div>
          <div class="sr-meta"><span class="sr-symbol">${esc(r.symbol)}</span><span>${esc(r.exchange)}</span></div>
        </div>
        <span class="sr-type-badge ${typeCls}">${esc(typeLbl)}</span>
      </div>`;
  }).join('');
  searchDropdown.innerHTML = html;
  searchDropdown.querySelectorAll('.search-result').forEach(el => {
    el.addEventListener('mousedown', (e) => {
      e.preventDefault(); // prevent focus loss
      selectResult(parseInt(el.dataset.idx));
    });
    el.addEventListener('mouseenter', () => { searchActiveIdx = parseInt(el.dataset.idx); updateActiveItem(); });
  });
}

function highlightMatch(name, query) {
  const q = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  try { return name.replace(new RegExp(`(${q})`, 'gi'), '<em>$1</em>'); } catch (_) { return name; }
}

function handleInputKeydown(e) {
  if (searchDropdown.classList.contains('hidden')) {
    if (e.key === 'Enter') handleAdd();
    return;
  }
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    searchActiveIdx = Math.min(searchActiveIdx + 1, searchResults.length - 1);
    updateActiveItem();
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    searchActiveIdx = Math.max(searchActiveIdx - 1, -1);
    updateActiveItem();
  } else if (e.key === 'Enter') {
    e.preventDefault();
    if (searchActiveIdx >= 0) selectResult(searchActiveIdx);
    else handleAdd();
  } else if (e.key === 'Escape') {
    closeDropdown(); symbolInput.blur();
  }
}

function updateActiveItem() {
  searchDropdown.querySelectorAll('.search-result').forEach((el, i) => {
    el.classList.toggle('active', i === searchActiveIdx);
  });
}

function selectResult(idx) {
  const r = searchResults[idx];
  if (!r) return;
  symbolInput.value = r.symbol;
  closeDropdown();
  handleAdd();
}

function showDropdown() { searchDropdown.classList.remove('hidden'); }
function closeDropdown() {
  if (searchDropdown) searchDropdown.classList.add('hidden');
  searchResults = [];
  searchActiveIdx = -1;
}

// ── Last-visit banner ─────────────────────────────────────────
async function loadLastVisit() {
  try {
    const res  = await fetch(`${API}/last-visit`);
    const data = await res.json();
    renderVisitChip(data.last_visit_time);
  } catch (_) {}
}

function renderVisitChip(isoTime) {
  if (!isoTime) {
    visitLabel.textContent = 'First visit';
    visitChip.classList.remove('fresh','away');
    return;
  }
  const diff    = Date.now() - new Date(isoTime).getTime();
  const minutes = Math.floor(diff / 60000);
  const hours   = Math.floor(minutes / 60);
  const days    = Math.floor(hours / 24);

  let label, cls;
  if (minutes < 2)       { label = 'Just refreshed';                cls = 'fresh'; }
  else if (minutes < 60) { label = `${minutes}m since last check`;   cls = 'away'; }
  else if (hours < 24)   { label = `${hours}h ${minutes%60}m away`;  cls = 'away'; }
  else                   { label = `${days}d since last visit`;       cls = 'away'; }

  visitLabel.textContent = label;
  visitChip.className    = `visit-chip ${cls}`;
}

// ── Add stock ─────────────────────────────────────────────────
async function handleAdd() {
  const symbol = symbolInput.value.trim().toUpperCase();
  if (!symbol) { setFeedback('Enter a ticker symbol.', 'error'); return; }

  btnAdd.disabled = true;
  setFeedback('Validating ticker…', 'loading');

  try {
    const res  = await fetch(`${API}/watchlist`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol }),
    });
    const data = await res.json();

    if (!res.ok) { setFeedback(data.error || 'Something went wrong.', 'error'); return; }

    symbolInput.value = '';
    setFeedback(`${symbol} added!`, 'success');
    await loadWatchlist();
    setTimeout(clearFeedback, 3000);
  } catch (e) {
    setFeedback('Network error — server unreachable.', 'error');
  } finally {
    btnAdd.disabled = false;
  }
}

// ── Remove stock ──────────────────────────────────────────────
async function handleRemove(symbol) {
  try {
    const res = await fetch(`${API}/watchlist/${encodeURIComponent(symbol)}`, { method: 'DELETE' });
    if (res.ok) {
      delete historyCache[symbol];
      await loadWatchlist();
    }
  } catch (e) { console.error('Remove failed:', e); }
}

// ── Load watchlist ────────────────────────────────────────────
async function loadWatchlist() {
  showLoading(true);
  setRefreshSpin(true);

  try {
    const res = await fetch(`${API}/watchlist`);
    if (!res.ok) throw new Error(`${res.status}`);
    watchlistData = await res.json();
    renderVisitChip(new Date().toISOString());
    renderDigest(watchlistData);

    // Pre-fetch snapshot histories for all symbols (async, don't block render)
    watchlistData.forEach(item => fetchHistory(item.symbol));

  } catch (e) {
    console.error('Load failed:', e);
  } finally {
    showLoading(false);
    setRefreshSpin(false);
  }
}

// ── Fetch snapshot history for one symbol ─────────────────────
async function fetchHistory(symbol) {
  try {
    const res  = await fetch(`${API}/history/${encodeURIComponent(symbol)}`);
    const data = await res.json();
    if (data.snapshots && data.snapshots.length > 1) {
      historyCache[symbol] = data.snapshots;
      // If card is already rendered, update its tracking-history chart
      updateTrackingChart(symbol, data.snapshots);
    }
  } catch (_) {}
}

// ── Update tracking chart after history arrives ───────────────
function updateTrackingChart(symbol, snapshots) {
  const containers = document.querySelectorAll(`.stock-card[data-symbol="${symbol}"] .tracking-sparkline`);
  containers.forEach(el => {
    const prices = snapshots.map(s => s.price).filter(Boolean);
    if (prices.length < 2) return;
    // Determine direction from first to last
    const dir = prices[prices.length-1] >= prices[0] ? 'up' : 'down';
    el.innerHTML = buildSparklineSVG(prices, dir);
    el.classList.remove('hidden');
    el.previousElementSibling?.classList.remove('hidden'); // show label
  });
}

// ── Render full digest ────────────────────────────────────────
function renderDigest(items) {
  cardsAlert.innerHTML = '';
  cardsCalm.innerHTML  = '';

  if (!items.length) {
    emptyState.classList.remove('hidden');
    digestAlert.classList.add('hidden');
    digestCalm.classList.add('hidden');
    updateHeroStats(0, 0, 0);
    return;
  }

  emptyState.classList.add('hidden');

  const alertItems = items.filter(i => i.is_meaningful || i.data_status === 'halted');
  const calmItems  = items.filter(i => !i.is_meaningful && i.data_status !== 'halted');

  updateHeroStats(items.length, alertItems.length, calmItems.length);

  // Alert section
  if (alertItems.length) {
    digestAlert.classList.remove('hidden');
    alertItems.forEach((item, idx) => cardsAlert.appendChild(buildCard(item, idx)));
  } else {
    digestAlert.classList.add('hidden');
  }

  // Calm section
  if (calmItems.length) {
    digestCalm.classList.remove('hidden');
    calmToggleLabel.textContent = `${calmItems.length} stock${calmItems.length !== 1 ? 's' : ''} with no significant change`;
    calmItems.forEach((item, idx) => cardsCalm.appendChild(buildCard(item, idx)));
  } else {
    digestCalm.classList.add('hidden');
  }
}

// ── Hero stat counters ────────────────────────────────────────
function updateHeroStats(total, alert, calm) {
  animateCount(hTotal, total);
  animateCount(hAlert, alert);
  animateCount(hCalm, calm);
}

function animateCount(el, target) {
  const start    = parseInt(el.textContent) || 0;
  const duration = 600;
  const startTs  = performance.now();
  const step = ts => {
    const progress = Math.min((ts - startTs) / duration, 1);
    const eased    = 1 - Math.pow(1 - progress, 3);
    el.textContent = Math.round(start + (target - start) * eased);
    if (progress < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// ── Build card ────────────────────────────────────────────────
function buildCard(item, idx) {
  const el = document.createElement('div');
  el.className   = `stock-card ${cardClass(item)}`;
  el.dataset.symbol = item.symbol;
  el.style.animationDelay = `${idx * 55}ms`;

  // Use cached history if available
  const hist  = historyCache[item.symbol] || [];
  const histPrices = hist.map(s => s.price).filter(Boolean);
  const histDir = histPrices.length >= 2
    ? (histPrices[histPrices.length-1] >= histPrices[0] ? 'up' : 'down')
    : item.direction;

  el.innerHTML = `
    <div class="card-accent"></div>
    <div class="card-body">

      ${buildCardTop(item)}
      ${buildSparklineSection(item)}
      ${buildPriceRow(item)}
      ${buildVolatilityMeter(item)}
      ${buildGauge(item)}
      ${buildTrackingHistory(histPrices, histDir)}
      ${buildReasonBox(item)}
      ${buildScoreExplainer(item)}
      ${buildCardFooter(item)}

    </div>
  `;

  el.querySelector('.btn-remove')?.addEventListener('click', () => handleRemove(item.symbol));
  return el;
}

// ── Card class ────────────────────────────────────────────────
function cardClass(item) {
  if (item.data_status === 'halted')      return 'card--halted';
  if (item.data_status === 'unavailable') return 'card--stale';
  if (item.first_visit)                   return 'card--first';
  if (!item.is_meaningful)                return 'card--calm';
  if (item.direction === 'up')            return 'card--up';
  if (item.direction === 'down')          return 'card--down';
  return 'card--flat';
}

// ── Card top: symbol + badges + remove ───────────────────────
function buildCardTop(item) {
  const badges = [];

  if (item.data_status === 'halted')       badges.push(`<span class="badge badge-halted" data-tip="Trading is paused — treating as notable">HALTED</span>`);
  else if (item.data_status === 'unavailable') badges.push(`<span class="badge badge-stale" data-tip="Could not refresh — showing cached data">STALE</span>`);
  else if (item.data_status === 'closed') badges.push(`<span class="badge badge-stale" data-tip="Market is currently closed — showing latest available close">CLOSED</span>`);
  else if (item.first_visit)               badges.push(`<span class="badge badge-new" data-tip="First snapshot recorded. Return later to see changes.">NEW</span>`);

  if (item.volatility_class) {
    const tip = {
      LOW:    'This stock typically moves <1% per day — very stable',
      MEDIUM: 'This stock typically moves 1-3% per day — moderate volatility',
      HIGH:   'This stock typically moves >3% per day — highly volatile',
    }[item.volatility_class] || '';
    const cls = { LOW: 'badge-low', MEDIUM: 'badge-medium', HIGH: 'badge-high' }[item.volatility_class];
    badges.push(`<span class="badge ${cls}" data-tip="${tip}">${item.volatility_class} VOL</span>`);
  }

  if (item.vol_trend === 'rising')  badges.push(`<span class="badge badge-medium" data-tip="Volatility is RISING — this stock is getting more erratic lately">VOL ↑</span>`);
  if (item.vol_trend === 'falling') badges.push(`<span class="badge badge-low"    data-tip="Volatility is FALLING — this stock is calming down lately">VOL ↓</span>`);

  if (item.crossed_52w_high) badges.push(`<span class="badge badge-52h" data-tip="Price just crossed its 52-week HIGH since your last visit">52W HIGH</span>`);
  if (item.crossed_52w_low)  badges.push(`<span class="badge badge-52l" data-tip="Price just crossed its 52-week LOW since your last visit">52W LOW</span>`);

  const pulse = item.is_meaningful ? `<span class="pulse-dot"></span>` : '';

  return `
    <div class="card-top">
      <div class="card-symbol-wrap">
        ${pulse}
        <span class="card-symbol">${esc(item.symbol)}</span>
      </div>
      <div class="card-top-right">
        <div class="card-badges">${badges.join('')}</div>
        <button class="btn-remove" title="Remove ${esc(item.symbol)}">✕</button>
      </div>
    </div>
  `;
}

// ── Market sparkline (20d daily closes) ──────────────────────
function buildSparklineSection(item) {
  const prices = item.sparkline || [];
  if (prices.length < 3) return '';
  return `<div class="card-sparkline">${buildSparklineSVG(prices, item.direction)}</div>`;
}

// ── Price row ─────────────────────────────────────────────────
function buildPriceRow(item) {
  if (item.price == null) return `<div class="card-price-row"><span class="card-price" style="color:var(--text-2)">N/A</span></div>`;
  const pStr = fmtPrice(item.price);
  let changeHtml = '';
  if (item.direction === 'up' && item.price_move_pct != null)
    changeHtml = `<span class="card-change up">▲ ${item.price_move_pct.toFixed(2)}%</span>`;
  else if (item.direction === 'down' && item.price_move_pct != null)
    changeHtml = `<span class="card-change down">▼ ${item.price_move_pct.toFixed(2)}%</span>`;
  else if (item.direction === 'flat')
    changeHtml = `<span class="card-change flat">→ Flat</span>`;
  return `<div class="card-price-row"><span class="card-price">${pStr}</span>${changeHtml}</div>`;
}

// ── Volatility meter: a horizontal bar showing EWMA ──────────
function buildVolatilityMeter(item) {
  if (!item.ewma_volatility && !item.volatility_class) return '';
  const pct = item.ewma_volatility; // already in % from backend
  if (pct == null) return '';
  // Scale: 0–5% range → 0–100% bar width. Clamp.
  const barW = Math.min(Math.round((pct / 5) * 100), 100);
  const trendArrow = item.vol_trend === 'rising' ? ' ↑' : item.vol_trend === 'falling' ? ' ↓' : '';
  const trendColor = item.vol_trend === 'rising' ? 'var(--neon-red)' : item.vol_trend === 'falling' ? 'var(--neon-green)' : 'var(--text-2)';
  return `
    <div class="vol-meter" data-tip="EWMA volatility: typical daily swing for this stock over last 20 days">
      <div class="vol-meter-top">
        <span class="vol-meter-label">Typical daily swing</span>
        <span class="vol-meter-val" style="color:${trendColor}">${pct.toFixed(2)}%${trendArrow}</span>
      </div>
      <div class="vol-bar-track">
        <div class="vol-bar-fill" style="width:${barW}%;background:${barColor(pct)}"></div>
      </div>
    </div>
  `;
}

function barColor(pct) {
  if (pct < 1)  return 'var(--neon-green)';
  if (pct < 3)  return 'linear-gradient(90deg, var(--neon-green), var(--neon-gold))';
  return 'linear-gradient(90deg, var(--neon-gold), var(--neon-red))';
}

// ── 52-week gauge ─────────────────────────────────────────────
function buildGauge(item) {
  if (item.pct_of_52w_range == null || item.week52_low == null) return '';
  const fillPct = Math.round(item.pct_of_52w_range * 100);
  return `
    <div class="gauge-wrap" data-tip="Where today's price sits within the 52-week range. Left = 52W low, right = 52W high.">
      <div class="gauge-row-labels">
        <span>↓ ${fmtPrice(item.week52_low)}</span>
        <span style="color:var(--text-2);font-size:9px">52-WEEK RANGE</span>
        <span>↑ ${fmtPrice(item.week52_high)}</span>
      </div>
      <div class="gauge-bar">
        <div class="gauge-filled" style="width:${Math.max(fillPct,2)}%"></div>
      </div>
    </div>
  `;
}

// ── Tracking history sparkline (user's own check-ins) ────────
function buildTrackingHistory(prices, dir) {
  // Always render the container; we'll fill it when history arrives
  const hasPrices = prices && prices.length >= 2;
  const svg = hasPrices ? buildSparklineSVG(prices, dir) : '';
  return `
    <div class="tracking-history-wrap ${hasPrices ? '' : 'hidden'}">
      <div class="tracking-label">Your tracking history</div>
      <div class="tracking-sparkline card-sparkline">${svg}</div>
    </div>
  `;
}

// ── Reason box ───────────────────────────────────────────────
function buildReasonBox(item) {
  const txt = item.reason || '—';
  const cls = item.is_meaningful ? 'card-reason card-reason--alert' : 'card-reason';
  return `<div class="${cls}">${esc(txt)}</div>`;
}

// ── Score explainer: human-friendly breakdown ────────────────
function buildScoreExplainer(item) {
  if (item.first_visit || item.change_score == null) return '';

  const volRatio = item.volatility_ratio;
  const volRat   = item.volume_ratio;
  const score    = item.change_score;

  if (volRatio == null) return '';

  // Describe the volatility ratio in plain English
  let volDesc;
  if (volRatio < 0.3)      volDesc = 'barely moved';
  else if (volRatio < 0.8) volDesc = 'moved a little';
  else if (volRatio < 1.5) volDesc = 'moved noticeably';
  else if (volRatio < 2.5) volDesc = 'moved significantly';
  else                     volDesc = 'moved unusually far';

  // Volume context
  let volRatDesc = '';
  if (volRat != null) {
    if (volRat < 0.5)      volRatDesc = 'very low volume';
    else if (volRat < 0.9) volRatDesc = 'below-normal volume';
    else if (volRat < 1.3) volRatDesc = 'normal volume';
    else if (volRat < 2.0) volRatDesc = 'elevated volume';
    else                   volRatDesc = 'very high volume';
  }

  const scoreBar = Math.min(Math.round((score / 4) * 100), 100);
  const scoreCol = score < 0.8 ? 'var(--text-2)' : score < 1.5 ? 'var(--neon-gold)' : 'var(--neon-red)';

  return `
    <div class="score-explainer" data-tip="Change Score = 70% price move (in units of this stock's normal volatility) + 30% volume anomaly. ≥ 1.5x normal = meaningful.">
      <div class="score-explainer-top">
        <span class="score-label">Change score</span>
        <span class="score-val" style="color:${scoreCol}">${score.toFixed(2)}</span>
      </div>
      <div class="score-bar-track">
        <div class="score-bar-fill" style="width:${scoreBar}%;background:${scoreCol === 'var(--text-2)' ? 'rgba(0,212,255,0.15)' : scoreCol}"></div>
        <div class="score-bar-marker" title="1.5x threshold — meaningful above this"></div>
      </div>
      <div class="score-breakdown">
        <span>${esc(volDesc)} (${volRatio.toFixed(1)}× normal swing)</span>
        ${volRatDesc ? `<span>·</span><span>${esc(volRatDesc)}</span>` : ''}
      </div>
    </div>
  `;
}

// ── Card footer ───────────────────────────────────────────────
function buildCardFooter(item) {
  const ts = item.last_updated ? fmtTs(item.last_updated) : '';
  const delayNote = `<span class="data-delay-note" data-tip="yfinance provides ~15-20 min delayed quotes (free tier). Not real-time tick data.">~15min delayed</span>`;
  return `
    <div class="card-footer">
      <span class="card-ts">${ts ? `as of ${ts}` : ''}</span>
      ${delayNote}
    </div>
  `;
}

// ── SVG Sparkline (pure, no library) ─────────────────────────
function buildSparklineSVG(prices, direction) {
  if (!prices || prices.length < 2) return '';

  const W = 400, H = 52, pad = 4;
  const min = Math.min(...prices), max = Math.max(...prices);
  const range = max - min || (min * 0.01) || 1;
  const w = W - pad*2, h = H - pad*2;

  const pts = prices.map((p, i) => [
    pad + (i / (prices.length - 1)) * w,
    pad + h - ((p - min) / range) * h,
  ]);

  // Smooth cubic bezier path
  const linePath = pts.reduce((acc, [x, y], i) => {
    if (i === 0) return `M${x},${y}`;
    const [px, py] = pts[i-1];
    const cx = (px + x) / 2;
    return acc + ` C${cx},${py} ${cx},${y} ${x},${y}`;
  }, '');

  const last = pts[pts.length-1], first = pts[0];
  const areaPath = linePath + ` L${last[0]},${H} L${first[0]},${H} Z`;

  const gid = 'g' + Math.random().toString(36).slice(2,8);
  const lineCol  = direction === 'up' ? '#00ff88' : direction === 'down' ? '#ff3366' : '#00d4ff';
  const fillStop = direction === 'up' ? 'rgba(0,255,136,0.25)' : direction === 'down' ? 'rgba(255,51,102,0.25)' : 'rgba(0,212,255,0.2)';

  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${fillStop}"/>
      <stop offset="100%" stop-color="rgba(0,0,0,0)"/>
    </linearGradient>
  </defs>
  <path d="${areaPath}" fill="url(#${gid})"/>
  <path d="${linePath}" fill="none" stroke="${lineCol}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
</svg>`;
}

// ── Tooltip system ────────────────────────────────────────────
function renderTooltip() {
  const tip = document.createElement('div');
  tip.id = 'global-tooltip';
  tip.className = 'g-tooltip';
  document.body.appendChild(tip);

  document.addEventListener('mouseover', e => {
    const el = e.target.closest('[data-tip]');
    if (!el) return;
    tip.textContent = el.dataset.tip;
    tip.classList.add('visible');
  });
  document.addEventListener('mousemove', e => {
    tip.style.left = (e.clientX + 14) + 'px';
    tip.style.top  = (e.clientY - 8)  + 'px';
  });
  document.addEventListener('mouseout', e => {
    if (!e.target.closest('[data-tip]')) tip.classList.remove('visible');
    const el = e.target.closest('[data-tip]');
    if (el && !el.contains(e.relatedTarget)) tip.classList.remove('visible');
  });
}

// ── Helpers ───────────────────────────────────────────────────
function fmtPrice(p) {
  if (p == null) return '—';
  if (p >= 10000) return p.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (p >= 1000)  return p.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (p >= 1)     return p.toFixed(2);
  return p.toFixed(4);
}

function fmtTs(iso) {
  try {
    const dt   = new Date(iso);
    const now  = new Date();
    const diff = now - dt;
    const mins = Math.floor(diff / 60000);
    if (mins < 1)   return 'just now';
    if (mins < 60)  return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24)   return `${hrs}h ago`;
    return dt.toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch (_) { return iso; }
}

function esc(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function setFeedback(msg, type) {
  addFeedback.textContent = msg;
  addFeedback.className   = `add-feedback ${type}`;
}
function clearFeedback() { addFeedback.textContent = ''; addFeedback.className = 'add-feedback'; }

function showLoading(show) { loadingState.classList.toggle('hidden', !show); }
function setRefreshSpin(on) {
  btnRefresh.disabled = on;
  btnRefresh.classList.toggle('spinning', on);
}

function toggleCalm() {
  calmExpanded = !calmExpanded;
  cardsCalm.classList.toggle('collapsed', !calmExpanded);
  cardsCalm.classList.toggle('expanded',  calmExpanded);
  btnToggleCalm.setAttribute('aria-expanded', String(calmExpanded));
}
