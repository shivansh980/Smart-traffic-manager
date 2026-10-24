'use strict';

// ---------------------------------------------------------------- config
const COLOR = {
  fixed: '#f5a524', adaptive: '#2dd4bf',
  bg: '#0c121b', road: '#273041', junction: '#2c3648', seam: '#0c121b',
  car: '#c7d2e3', carHalted: '#f87171', bus: '#60a5fa', busHalted: '#f472b6', amb: '#ef4444',
  G: '#22c55e', y: '#facc15', r: '#ef4444',
};
const RUSH = [600, 1800];
const VIEW_INSET = 70;            // metres trimmed off each side: the outer arm ends are empty road
const VEH = { c: [5, 1.9], b: [12, 2.6], e: [6.5, 2.3] };   // length, width in metres
const CHART_EVERY = 5;            // sim seconds between chart points
const QUEUE_SMOOTH = 90;          // rolling mean (s) over one 90 s signal cycle; raw queues swing with it
const PRESETS = {
  commute: { flow: 1, climate: 0, transit: 0, fairness: 0 },
  climate: { flow: 1, climate: 2.5, transit: 0, fairness: 0 },
  transit: { flow: 1, climate: 0, transit: 2.5, fairness: 0 },
  fair:    { flow: 1, climate: 0, transit: 0, fairness: 2.5 },
};
const SLIDERS = [
  { key: 'flow', label: 'Flow', sub: 'move the most cars' },
  { key: 'climate', label: 'Climate', sub: 'fewer stops, less CO₂' },
  { key: 'transit', label: 'Transit', sub: 'buses go first' },
  { key: 'fairness', label: 'Fairness', sub: 'cap the longest wait' },
];
const CARDS = [
  { key: 'avg_delay_s', label: 'Avg delay per vehicle', unit: 's', dec: 1, lower: true },
  { key: 'idle_co2_kg', label: 'Idling CO₂ (wasted)', unit: 'kg', dec: 1, lower: true, hero: true },
  { key: 'co2_kg', label: 'Total CO₂', unit: 'kg', dec: 0, lower: true },
  { key: 'arrived', label: 'Trips completed', unit: '', dec: 0, lower: false },
  { key: 'max_wait_s', label: 'Longest wait right now', unit: 's', dec: 0, lower: true },
  { key: 'amb', label: 'Ambulance trip', unit: 's', dec: 0, lower: true },
];

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const REPLAY = params.get('replay');

const app = {
  net: null, frame: null, dirty: false,
  playing: false, sps: 10, ws: null, connected: false,
  weights: { flow: 1, climate: 0, transit: 0, fairness: 0, preempt: true },
  lastT: -1, lastChartT: -Infinity,
};

// ---------------------------------------------------------------- map view
class MapView {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.bg = document.createElement('canvas');
    new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
  }

  setNet(net) {
    this.net = net;
    const [x0, y0, x1, y1] = net.bounds;
    this.view = [x0 + VIEW_INSET, y0 + VIEW_INSET, x1 - VIEW_INSET, y1 - VIEW_INSET];
    // signal bar geometry: lane end point + perpendicular, precomputed once
    this.stops = {};
    for (const lane of net.lanes) {
      const s = lane.shape, [ax, ay] = s[s.length - 2], [bx, by] = s[s.length - 1];
      const len = Math.hypot(bx - ax, by - ay) || 1;
      this.stops[lane.id] = { x: bx, y: by, nx: -(by - ay) / len, ny: (bx - ax) / len, w: lane.w };
    }
    // junction squares: half-size = nearest lane end to the node (Chebyshev distance)
    this.junctions = net.tls.map((t) => {
      let h = Infinity;
      for (const lane of net.lanes) {
        const [ex, ey] = lane.shape[lane.shape.length - 1];
        const d = Math.max(Math.abs(ex - t.x), Math.abs(ey - t.y));
        if (d > 1 && d < h) h = d;
      }
      return { ...t, h: Math.min(h, 25) };
    });
    this.resize();
  }

  resize() {
    if (!this.net) return;
    const wrap = this.canvas.parentElement.getBoundingClientRect();
    const side = Math.max(120, Math.floor(Math.min(wrap.width - 20, wrap.height - 10)));
    const dpr = window.devicePixelRatio || 1;
    this.dpr = dpr;
    this.side = side;
    for (const c of [this.canvas, this.bg]) { c.width = side * dpr; c.height = side * dpr; }
    this.canvas.style.width = this.canvas.style.height = side + 'px';
    const [x0, y0, x1, y1] = this.view;
    this.s = side / Math.max(x1 - x0, y1 - y0);
    this.drawBackground();
    app.dirty = true;
  }

  px(x, y) { return [(x - this.view[0]) * this.s, (this.view[3] - y) * this.s]; }

  drawBackground() {
    const ctx = this.bg.getContext('2d');
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.fillStyle = COLOR.bg;
    ctx.fillRect(0, 0, this.side, this.side);
    ctx.lineCap = 'butt';
    ctx.lineJoin = 'round';
    ctx.strokeStyle = COLOR.road;
    for (const lane of this.net.lanes) {
      ctx.lineWidth = Math.max(1.5, lane.w * this.s - 0.6);   // the gap reads as a lane line
      ctx.beginPath();
      lane.shape.forEach(([x, y], i) => { const [px, py] = this.px(x, y); i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); });
      ctx.stroke();
    }
    ctx.fillStyle = COLOR.junction;
    for (const j of this.junctions) {
      const [px, py] = this.px(j.x, j.y), h = j.h * this.s;
      ctx.fillRect(px - h, py - h, 2 * h, 2 * h);
    }
  }

  draw(sim, now) {
    const { ctx, s, dpr } = this;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.drawImage(this.bg, 0, 0);
    if (!sim) return;

    // signals: a bar across each lane's stop line
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.lineWidth = Math.max(3, 2.2 * s);
    ctx.lineCap = 'butt';
    for (const [lane, st] of Object.entries(sim.sig)) {
      const p = this.stops[lane];
      if (!p) continue;
      const [cx, cy] = this.px(p.x, p.y), hw = (p.w / 2) * s + 0.6;
      ctx.strokeStyle = COLOR[st] || COLOR.r;
      ctx.beginPath();
      ctx.moveTo(cx - p.nx * hw, cy + p.ny * hw);
      ctx.lineTo(cx + p.nx * hw, cy - p.ny * hw);
      ctx.stroke();
    }

    // vehicles: rotated rects, front bumper at (x, y), angle clockwise from north
    const kl = Math.max(0.9, 1.1 * s);                // px per metre along the vehicle
    const kw = (w) => Math.max(2.6, w * s * 1.6);     // width in px, boosted so it reads on a projector
    let amb = [];
    for (const v of sim.veh) {
      const [, x, y, ang, kind, halted] = v;
      const [px, py] = this.px(x, y);
      const [L, W] = VEH[kind] || VEH.c;
      const a = (ang * Math.PI) / 180, c = Math.cos(a), sn = Math.sin(a);
      ctx.setTransform(dpr * c, dpr * sn, -dpr * sn, dpr * c, dpr * px, dpr * py);
      if (kind === 'e') { amb.push([px, py]); continue; }
      ctx.fillStyle = kind === 'b' ? (halted ? COLOR.busHalted : COLOR.bus) : (halted ? COLOR.carHalted : COLOR.car);
      ctx.fillRect(-kw(W) / 2, 0, kw(W), L * kl);
    }
    // ambulances last, on top, with a pulsing halo and flashing outline
    const flash = Math.floor(now / 250) % 2 === 0;
    for (const [px, py] of amb) {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const r = 9 + 5 * (0.5 + 0.5 * Math.sin(now / 160));
      ctx.fillStyle = flash ? 'rgba(239,68,68,0.28)' : 'rgba(96,165,250,0.28)';
      ctx.beginPath(); ctx.arc(px, py, r, 0, Math.PI * 2); ctx.fill();
    }
    for (const v of sim.veh) {
      if (v[4] !== 'e') continue;
      const [px, py] = this.px(v[1], v[2]);
      const [L, W] = VEH.e, a = (v[3] * Math.PI) / 180, c = Math.cos(a), sn = Math.sin(a);
      ctx.setTransform(dpr * c, dpr * sn, -dpr * sn, dpr * c, dpr * px, dpr * py);
      ctx.fillStyle = COLOR.amb;
      ctx.fillRect(-kw(W) / 2, 0, kw(W), L * kl);
      ctx.lineWidth = 1.2;
      ctx.strokeStyle = flash ? '#ffffff' : '#60a5fa';
      ctx.strokeRect(-kw(W) / 2, 0, kw(W), L * kl);
    }
    ctx.setTransform(1, 0, 0, 1, 0, 0);
  }
}

const views = { fixed: new MapView($('cv-fixed')), adaptive: new MapView($('cv-adaptive')) };

// ---------------------------------------------------------------- cards
function buildCards() {
  $('cards').innerHTML = CARDS.map((c) => `
    <div class="card${c.hero ? ' hero' : ''}" id="card-${c.key}">
      <div class="card-label"><span>${c.label}</span></div>
      <div class="delta" data-role="delta">—</div>
      <div class="pair">
        <div class="f"><span>Fixed</span><b data-role="f">—</b></div>
        <div class="a"><span>CivicSignal</span><b data-role="a">—</b></div>
      </div>
    </div>`).join('');
}

const fmt = (v, dec, unit) => (v == null ? '—' : `${Number(v).toFixed(dec)}${unit ? `<small>${unit}</small>` : ''}`);
const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

function ambValue(m) {
  if (m.amb_active) return { text: `${mmss(m.amb_elapsed_s)}<small class="nowrap"> en route</small>`, val: null };
  if (m.amb_last_trip_s != null) return { text: fmt(m.amb_last_trip_s, 0, 's'), val: m.amb_last_trip_s };
  return { text: '—', val: null };
}

function updateCards(f, a) {
  for (const c of CARDS) {
    const el = $(`card-${c.key}`);
    const d = el.querySelector('[data-role="delta"]');
    let fv, av, ftext, atext;
    if (c.key === 'amb') {
      const fa = ambValue(f), aa = ambValue(a);
      fv = fa.val; av = aa.val; ftext = fa.text; atext = aa.text;
    } else {
      fv = f[c.key]; av = a[c.key]; ftext = fmt(fv, c.dec, c.unit); atext = fmt(av, c.dec, c.unit);
    }
    el.querySelector('[data-role="f"]').innerHTML = ftext;
    el.querySelector('[data-role="a"]').innerHTML = atext;

    d.className = 'delta';
    if (fv == null || av == null || (c.key !== 'amb' && f.t < 60)) { d.innerHTML = '—'; continue; }
    if (c.key === 'amb') {
      const diff = av - fv;
      d.innerHTML = `${diff > 0 ? '+' : '−'}${Math.abs(diff).toFixed(0)}<small>s</small>`;
      d.classList.add(diff < 0 ? 'good' : diff > 0 ? 'bad' : 'x');
      continue;
    }
    if (fv === 0) { d.innerHTML = av === 0 ? '0%' : '—'; continue; }
    let pct = ((av - fv) / Math.abs(fv)) * 100;
    if (Math.abs(pct) < 0.5) pct = 0;
    const better = c.lower ? pct < -0.5 : pct > 0.5, worse = c.lower ? pct > 0.5 : pct < -0.5;
    d.innerHTML = `${pct > 0 ? '+' : pct < 0 ? '−' : ''}${Math.abs(pct).toFixed(0)}%`;
    if (better) d.classList.add('good'); else if (worse) d.classList.add('bad');
  }
}

function updateMapStats(name, m) {
  let s = `queued <b>${m.queue}</b> · moving <b>${Math.max(0, m.running - m.queue)}</b>`;
  if (m.amb_active) s += ` · <span class="amb">🚑 ${mmss(m.amb_elapsed_s)}</span>`;
  else if (m.amb_last_trip_s != null) s += ` · 🚑 ${m.amb_last_trip_s.toFixed(0)}s`;
  $(`stat-${name}`).innerHTML = s;
}

// ---------------------------------------------------------------- chart
let chart;
function buildChart() {
  const rushBand = {
    id: 'rush',
    beforeDatasetsDraw(c) {
      const { ctx, chartArea: a, scales: { x } } = c;
      const l = x.getPixelForValue(RUSH[0]), r = x.getPixelForValue(RUSH[1]);
      ctx.save();
      ctx.fillStyle = 'rgba(245,165,36,0.06)';
      ctx.fillRect(l, a.top, r - l, a.bottom - a.top);
      ctx.fillStyle = 'rgba(245,165,36,0.55)';
      ctx.font = '600 11px system-ui, sans-serif';
      ctx.fillText('RUSH HOUR', l + 6, a.top + 14);
      ctx.restore();
    },
  };
  const line = (label, color, axis, dashed) => ({
    label, data: [], borderColor: color, backgroundColor: color, yAxisID: axis,
    borderWidth: dashed ? 1.5 : 2.6, borderDash: dashed ? [5, 4] : [], pointRadius: 0, tension: 0.25,
  });
  Chart.defaults.color = '#8a9ab4';
  Chart.defaults.font.family = 'ui-sans-serif, system-ui, -apple-system, sans-serif';
  chart = new Chart($('chart'), {
    type: 'line',
    data: {
      datasets: [
        line('Idling CO₂ · fixed', COLOR.fixed, 'co2', false),
        line('Idling CO₂ · CivicSignal', COLOR.adaptive, 'co2', false),
        line('Queue · fixed', COLOR.fixed + 'aa', 'q', true),
        line('Queue · CivicSignal', COLOR.adaptive + 'aa', 'q', true),
      ],
    },
    options: {
      animation: false, parsing: false, normalized: true, maintainAspectRatio: false, spanGaps: true,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { position: 'top', align: 'start', labels: { boxWidth: 14, boxHeight: 3, padding: 12,
          filter: (item) => item.datasetIndex < 2 } },
        tooltip: { callbacks: { title: (items) => mmss(items[0].parsed.x) } },
      },
      scales: {
        x: { type: 'linear', min: 0, max: 2400, grid: { color: '#1b2333' },
             ticks: { stepSize: 300, callback: (v) => `${v / 60} min` } },
        co2: { position: 'left', beginAtZero: true, grid: { color: '#1b2333' },
               title: { display: true, text: 'kg CO₂ idling' } },
        q: { position: 'right', beginAtZero: true, grid: { drawOnChartArea: false },
             title: { display: true, text: 'vehicles queued' } },
      },
    },
    plugins: [rushBand],
  });
}

function resetChart() {
  for (const ds of chart.data.datasets) ds.data = [];
  qwin.f = []; qwin.a = [];
  app.lastChartT = -Infinity;
  chart.update('none');
}

let chartDirty = false;
const qwin = { f: [], a: [] };
const mean = (xs) => xs.reduce((s, x) => s + x, 0) / xs.length;
function pushChart(t, f, a) {
  qwin.f.push(f.queue); qwin.a.push(a.queue);
  if (qwin.f.length > QUEUE_SMOOTH) { qwin.f.shift(); qwin.a.shift(); }
  if (t - app.lastChartT < CHART_EVERY) return;
  app.lastChartT = t;
  const [d0, d1, d2, d3] = chart.data.datasets;
  d0.data.push({ x: t, y: f.idle_co2_kg }); d1.data.push({ x: t, y: a.idle_co2_kg });
  d2.data.push({ x: t, y: mean(qwin.f) });  d3.data.push({ x: t, y: mean(qwin.a) });
  chartDirty = true;
}
setInterval(() => { if (chartDirty) { chart.update('none'); chartDirty = false; } }, 250);

// ---------------------------------------------------------------- controls
function buildSliders() {
  $('sliders').innerHTML = SLIDERS.map((s) => `
    <div class="slider">
      <label for="w-${s.key}">${s.label}<small>${s.sub}</small></label>
      <input type="range" id="w-${s.key}" min="0" max="3" step="0.25" value="${app.weights[s.key]}">
      <output id="o-${s.key}">${app.weights[s.key].toFixed(2)}</output>
    </div>`).join('');
  for (const s of SLIDERS) {
    $(`w-${s.key}`).addEventListener('input', (e) => {
      app.weights[s.key] = Number(e.target.value);
      syncControls();
      sendWeights();
    });
  }
}

function syncControls() {
  for (const s of SLIDERS) {
    const el = $(`w-${s.key}`), v = app.weights[s.key];
    el.value = v;
    el.style.setProperty('--fill', `${(v / 3) * 100}%`);
    $(`o-${s.key}`).textContent = v.toFixed(2);
  }
  $('preempt').checked = app.weights.preempt;
  for (const b of document.querySelectorAll('[data-preset]')) {
    const p = PRESETS[b.dataset.preset];
    b.classList.toggle('active', Object.keys(p).every((k) => p[k] === app.weights[k]));
  }
  $('play').textContent = app.playing ? '❚❚ Pause' : '▶ Play';
  const sel = $('speed');
  if (![...sel.options].some((o) => Number(o.value) === app.sps)) {
    sel.add(new Option(`${app.sps / 10}×`, app.sps));
  }
  sel.value = String(app.sps);
}

let weightTimer = null;
function sendWeights() {
  clearTimeout(weightTimer);
  weightTimer = setTimeout(() => send({ type: 'weights', ...app.weights }), 60);
}

function send(msg) {
  if (app.ws && app.ws.readyState === WebSocket.OPEN) app.ws.send(JSON.stringify(msg));
}

function togglePlay() {
  app.playing = !app.playing;
  if (REPLAY) replay.setPlaying(app.playing);
  else send({ type: 'control', action: app.playing ? 'play' : 'pause' });
  syncControls();
}

function dispatchAmbulance() {
  if (REPLAY) return;
  send({ type: 'ambulance' });
  const btn = $('ambulance');
  btn.disabled = true;
  setTimeout(() => (btn.disabled = false), 1500);
}

function wireControls() {
  $('play').addEventListener('click', togglePlay);
  $('reset').addEventListener('click', () => {
    if (REPLAY) replay.restart(); else send({ type: 'control', action: 'reset' });
  });
  $('speed').addEventListener('change', (e) => {
    app.sps = Number(e.target.value);
    if (!REPLAY) send({ type: 'speed', sps: app.sps });
  });
  $('preempt').addEventListener('change', (e) => { app.weights.preempt = e.target.checked; sendWeights(); });
  $('ambulance').addEventListener('click', dispatchAmbulance);
  for (const b of document.querySelectorAll('[data-preset]')) {
    b.addEventListener('click', () => {
      Object.assign(app.weights, PRESETS[b.dataset.preset]);
      syncControls();
      sendWeights();
    });
  }
  document.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT' && e.target.type !== 'range') return;
    if (e.code === 'Space') { e.preventDefault(); togglePlay(); }
    if (e.key === 'a' || e.key === 'A') dispatchAmbulance();
  });
}

// ---------------------------------------------------------------- toasts
function toast(html, kind = '') {
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.innerHTML = html;
  $('toasts').appendChild(el);
  setTimeout(() => el.remove(), 5200);
}

function handleEvents(frame) {
  const { fixed: f, adaptive: a } = frame.sims;
  for (const ev of frame.events || []) {
    if (ev === 'ambulance_spawned') toast('🚑 <b>Ambulance dispatched</b> in both cities, same route', 'amb');
    if (ev === 'ambulance_arrived_adaptive')
      toast(`<b style="color:${COLOR.adaptive}">CivicSignal</b> ambulance arrived in <b>${a.m.amb_last_trip_s.toFixed(0)} s</b>`);
    if (ev === 'ambulance_arrived_fixed')
      toast(`<b style="color:${COLOR.fixed}">Fixed-time</b> ambulance arrived in <b>${f.m.amb_last_trip_s.toFixed(0)} s</b>`, 'fixed');
    if (ev === 'sim_end') toast('Simulation finished. Press Reset to run again.');
  }
}

// ---------------------------------------------------------------- frames
function onFrame(frame, quiet = false) {
  if (frame.t < app.lastT) resetChart();   // reset or replay restart
  app.lastT = frame.t;
  app.frame = frame;
  app.dirty = true;
  const { fixed: f, adaptive: a } = frame.sims;
  pushChart(frame.t, f.m, a.m);
  if (!quiet) handleEvents(frame);
}

function onHistory(points) {
  resetChart();
  for (const [t, fi, ai, fq, aq] of points) pushChart(t, { idle_co2_kg: fi, queue: fq }, { idle_co2_kg: ai, queue: aq });
  app.lastT = points.length ? points[points.length - 1][0] : -1;
}

function onState(st) {
  Object.assign(app.weights, st.weights);
  app.playing = st.playing;
  app.sps = st.sps;
  syncControls();
}

function render(now) {
  if (app.frame) {
    const { fixed: f, adaptive: a } = app.frame.sims;
    views.fixed.draw(f, now);
    views.adaptive.draw(a, now);
    if (app.dirty) {
      updateCards(f.m, a.m);
      updateMapStats('fixed', f.m);
      updateMapStats('adaptive', a.m);
      const t = app.frame.t;
      $('clock').textContent = mmss(t);
      const rush = t >= RUSH[0] && t < RUSH[1];
      $('phase').textContent = rush ? 'Rush hour' : t < RUSH[0] ? 'Off-peak' : 'Evening off-peak';
      $('phase').classList.toggle('rush', rush);
      app.dirty = false;
    }
  } else {
    views.fixed.draw(null, now);
    views.adaptive.draw(null, now);
  }
  requestAnimationFrame(render);
}

// ---------------------------------------------------------------- live server
function connect() {
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
  app.ws = ws;
  ws.onopen = () => {
    app.connected = true;
    $('conn').className = 'conn on';
    $('banner').hidden = true;
    if (params.has('autoplay')) {
      if (params.has('sps')) send({ type: 'speed', sps: Number(params.get('sps')) });
      send({ type: 'control', action: 'play' });
    }
  };
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'frame') onFrame(msg);
    else if (msg.type === 'state') onState(msg);
    else if (msg.type === 'history') onHistory(msg.points);
  };
  ws.onclose = () => {
    app.connected = false;
    $('conn').className = 'conn off';
    const b = $('banner');
    b.innerHTML = 'Not connected to the sim server. Run <code>python server.py</code>, or open the backup: '
      + '<a href="?replay=/recordings/demo.jsonl" style="color:#fff">replay</a>. Retrying…';
    b.hidden = false;
    setTimeout(connect, 1500);
  };
}

// ---------------------------------------------------------------- replay mode
const replay = {
  lines: [], i: 0, timer: null,
  async load(url) {
    $('mode').hidden = false;
    $('conn').hidden = true;
    $('ambulance').disabled = true;
    $('ambulance').title = 'Replay mode: the ambulance in this recording is already scheduled';
    for (const s of SLIDERS) $(`w-${s.key}`).disabled = true;
    $('preempt').disabled = true;
    for (const b of document.querySelectorAll('[data-preset]')) b.disabled = true;
    const res = await fetch(url);
    if (!res.ok) { toast(`Could not load replay ${url} (${res.status})`, 'amb'); return; }
    this.lines = (await res.text()).split('\n').filter(Boolean);
    toast(`Replay loaded: ${this.lines.length} frames`);
    this.i = 0;
    this.seek(Number(params.get('t')) || 0);
    if (params.has('autoplay')) { app.playing = true; syncControls(); this.setPlaying(true); }
  },
  seek(t) {   // ?t=600 jumps to rush hour; the chart fills in silently on the way
    while (this.i < this.lines.length - 1) {
      const f = JSON.parse(this.lines[this.i]);
      if (f.t >= t) break;
      onFrame(f, true);
      this.i++;
    }
    this.stepOnce();
  },
  stepOnce() {
    if (this.i >= this.lines.length) { this.setPlaying(false); app.playing = false; syncControls(); return; }
    onFrame(JSON.parse(this.lines[this.i++]));
  },
  setPlaying(on) {
    clearTimeout(this.timer);
    if (!on) return;
    const tick = () => {
      const t0 = performance.now();
      this.stepOnce();
      if (app.playing) this.timer = setTimeout(tick, Math.max(0, 1000 / app.sps - (performance.now() - t0)));
    };
    tick();
  },
  restart() { this.i = 0; this.seek(Number(params.get('t')) || 0); },
};

// ---------------------------------------------------------------- boot
async function boot() {
  buildCards();
  buildSliders();
  buildChart();
  wireControls();
  syncControls();
  const net = await (await fetch('net.json')).json();
  app.net = net;
  views.fixed.setNet(net);
  views.adaptive.setNet(net);
  requestAnimationFrame(render);
  if (REPLAY) replay.load(REPLAY); else connect();
}
boot();
