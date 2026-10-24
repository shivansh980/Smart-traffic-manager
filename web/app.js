'use strict';

// ================================================================ config
const STRAT = {
  fixed: { color: '#f5a524', label: 'Fixed-time', tag: 'Fixed', sub: "today's timers",
           how: 'Runs a fixed 90 s cycle with an even split. It never looks at the cars.' },
  actuated: { color: '#c084fc', label: 'Actuated', tag: 'Actuated', sub: 'detectors extend green',
              how: 'Same phases, but each green stretches (6–55 s) while its detectors keep seeing cars.' },
  greenwave: { color: '#60a5fa', label: 'Green wave', tag: 'Wave', sub: 'timed progression',
               how: 'Fixed timing favouring the avenues, offset light to light so platoons hit consecutive greens.' },
  adaptive: { color: '#2dd4bf', label: 'CivicSignal', tag: 'Civic', sub: 'adaptive, city-steered', how: '' },
};
const COLOR = {
  bg: '#0b1018', building: '#121a26', buildingEdge: '#1a2434', road: '#263043', junction: '#2a3446',
  label: '#66758f', landmark: '#a3b3cc',
  car: '#c7d2e3', carHalted: '#f87171', bus: '#60a5fa', busHalted: '#f472b6', amb: '#ef4444', crash: '#fb923c',
  G: '#22c55e', y: '#facc15', r: '#ef4444',
};
const VEH = { c: [5, 1.9], b: [12, 2.6], e: [6.5, 2.3], x: [5, 2.0] };
const TERM_COLORS = { flow: '#2dd4bf', climate: '#34d399', transit: '#60a5fa', fairness: '#f5a524' };
const PRESETS = {
  Balanced: { flow: 1, climate: 1, transit: 0.5, fairness: 0 },
  Commute: { flow: 1, climate: 0, transit: 0, fairness: 0 },
  Climate: { flow: 1, climate: 2.5, transit: 0, fairness: 0 },
  Transit: { flow: 1, climate: 1, transit: 2.5, fairness: 0 },
  Fairness: { flow: 1, climate: 1, transit: 0, fairness: 2.5 },
};
const SLIDERS = [
  { key: 'flow', label: 'Flow', sub: 'move the most cars' },
  { key: 'climate', label: 'Climate', sub: 'fewer stops, less CO₂' },
  { key: 'transit', label: 'Transit', sub: 'buses go first' },
  { key: 'fairness', label: 'Fairness', sub: 'cap the longest wait' },
];
const USD_PER_GAL = 3.5, L_PER_GAL = 3.785, RUSH_HOURS_PER_YEAR = 2 * 250;
const CHART_EVERY = 5, QUEUE_SMOOTH = 90, WINDOW_KEEP = 130;

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const REPLAY = params.get('replay');
const VIEW = params.get('view');
const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
const short = (n) => (n || '').replace('Avenue', 'Ave').replace('Street', 'St').replace('West ', 'W ').replace('East ', 'E ');

const S = {
  state: null, scenario: null, panes: [], net: null, nets: {}, views: {},
  frame: null, dirty: false, playing: false, sps: 10,
  weights: { flow: 1, climate: 1, transit: 0.5, fairness: 0, preempt: true },
  heat: false, heatMax: 10, heatData: {}, win: 'all', snaps: [],
  follow: null, followTrip: null, inspect: null, race: null, log: [],
  ws: null, lastT: -1,
};

// ================================================================ map view
class MapView {
  constructor(sid, wrap) {
    this.sid = sid;
    this.wrap = wrap;
    this.canvas = document.createElement('canvas');
    wrap.appendChild(this.canvas);
    this.ctx = this.canvas.getContext('2d');
    this.bg = document.createElement('canvas');
    this.canvas.addEventListener('click', (e) => this.click(e));
    new ResizeObserver(() => this.resize()).observe(wrap);
  }

  setNet(net) {
    this.net = net;
    this.orientation = null;
    this.resize();
  }

  // Frame the signalized area (plus a block of approach), turned so it fills the pane best:
  // avenues vertical (the usual Manhattan view) or horizontal, whichever gives the larger scale.
  viewFor(rotDeg) {
    const rd = (rotDeg * Math.PI) / 180, c = Math.cos(rd), s = Math.sin(rd);
    const [x0, y0, x1, y1] = this.net.bounds, cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    const pts = this.net.tls.length >= 4 ? this.net.tls.map((t) => [t.x, t.y]) : this.net.lanes.flatMap((l) => l.shape);
    let mnx = Infinity, mny = Infinity, mxx = -Infinity, mxy = -Infinity;
    for (const [x, y] of pts) {
      const dx = x - cx, dy = y - cy, rx = dx * c - dy * s, ry = dx * s + dy * c;
      mnx = Math.min(mnx, rx); mny = Math.min(mny, ry); mxx = Math.max(mxx, rx); mxy = Math.max(mxy, ry);
    }
    const pad = this.net.tls.length >= 4 ? 95 : 14;
    return [mnx - pad, mny - pad, mxx + pad, mxy + pad];
  }

  orient(rotDeg) {
    const net = this.net;
    this.rotDeg = rotDeg;
    const rd = (this.rotDeg * Math.PI) / 180;
    this.cos = Math.cos(rd); this.sin = Math.sin(rd);
    const [x0, y0, x1, y1] = net.bounds;
    this.cx = (x0 + x1) / 2; this.cy = (y0 + y1) / 2;
    this.lanes = net.lanes.map((l) => ({ id: l.id, edge: l.id.replace(/_\d+$/, ''), w: l.w, pts: l.shape.map((p) => this.R(p[0], p[1])) }));
    this.view = this.viewFor(rotDeg);
    this.stops = {};
    for (const l of this.lanes) {
      const n = l.pts.length;
      const [ax, ay] = l.pts[n - 2], [bx, by] = l.pts[n - 1];
      const len = Math.hypot(bx - ax, by - ay) || 1;
      this.stops[l.id] = { x: bx, y: by, nx: -(by - ay) / len, ny: (bx - ax) / len, w: l.w };
    }
    this.junctions = (net.junctions || []).map((j) => j.shape.map((p) => this.R(p[0], p[1])));
    this.buildings = (net.buildings || []).map((b) => b.map((p) => this.R(p[0], p[1])));
    this.labels = (net.labels || []).map((l) => ({ ...l, p: this.R(l.x, l.y), a: l.angle + this.rotDeg }));
    this.landmarks = (net.meta.landmarks || []).map((l) => ({ ...l, p: this.R(l.x, l.y) }));
    this.tls = net.tls.map((t) => ({ id: t.id, p: this.R(t.x, t.y) }));
  }

  R(x, y) {
    const dx = x - this.cx, dy = y - this.cy;
    return [dx * this.cos - dy * this.sin, dx * this.sin + dy * this.cos];
  }

  resize() {
    if (!this.net) return;
    const r = this.wrap.getBoundingClientRect();
    const w = Math.max(100, Math.floor(r.width)), h = Math.max(100, Math.floor(r.height));
    const dpr = window.devicePixelRatio || 1;
    this.w = w; this.h = h; this.dpr = dpr;
    for (const c of [this.canvas, this.bg]) { c.width = w * dpr; c.height = h * dpr; }
    const base = this.net.meta.rotate_deg || 0;
    const fit = (v) => Math.min(w / (v[2] - v[0]), h / (v[3] - v[1]));
    const want = fit(this.viewFor(base - 90)) > fit(this.viewFor(base)) * 1.08 ? 'h' : 'v';
    if (want !== this.orientation) { this.orientation = want; this.orient(want === 'h' ? base - 90 : base); }
    const [x0, y0, x1, y1] = this.view;
    this.s = Math.min(w / (x1 - x0), h / (y1 - y0));
    this.ox = (w - (x1 - x0) * this.s) / 2;
    this.oy = (h - (y1 - y0) * this.s) / 2;
    this.drawBackground();
    S.dirty = true;
  }

  px(x, y) { return [this.ox + (x - this.view[0]) * this.s, this.oy + (this.view[3] - y) * this.s]; }
  world(px, py) { return [this.view[0] + (px - this.ox) / this.s, this.view[3] - (py - this.oy) / this.s]; }

  path(ctx, pts, close) {
    ctx.beginPath();
    pts.forEach(([x, y], i) => { const [a, b] = this.px(x, y); i ? ctx.lineTo(a, b) : ctx.moveTo(a, b); });
    if (close) ctx.closePath();
  }

  drawBackground() {
    const ctx = this.bg.getContext('2d');
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.fillStyle = COLOR.bg;
    ctx.fillRect(0, 0, this.w, this.h);
    ctx.fillStyle = COLOR.building; ctx.strokeStyle = COLOR.buildingEdge; ctx.lineWidth = 0.6;
    for (const b of this.buildings) { this.path(ctx, b, true); ctx.fill(); ctx.stroke(); }
    ctx.lineCap = 'butt'; ctx.lineJoin = 'round'; ctx.strokeStyle = COLOR.road;
    for (const l of this.lanes) {
      ctx.lineWidth = Math.max(1.2, l.w * this.s - 0.5);
      this.path(ctx, l.pts, false); ctx.stroke();
    }
    ctx.fillStyle = COLOR.junction;
    for (const j of this.junctions) { this.path(ctx, j, true); ctx.fill(); }
    // street names: avenues everywhere, cross streets on the west side only (less clutter)
    ctx.font = `600 ${Math.max(9, Math.min(12, 13 * this.s))}px ui-sans-serif, system-ui, sans-serif`;
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    for (const l of this.labels) {
      if (!l.major && !/^W |^\d/.test(l.text)) continue;
      const [x, y] = this.px(l.p[0], l.p[1]);
      let a = ((l.a % 360) + 360) % 360;
      if (a > 90 && a < 270) a -= 180;
      ctx.save(); ctx.translate(x, y); ctx.rotate((-a * Math.PI) / 180);
      ctx.fillStyle = 'rgba(11,16,24,.75)';
      const tw = ctx.measureText(l.text).width;
      ctx.fillRect(-tw / 2 - 3, -7, tw + 6, 14);
      ctx.fillStyle = l.major ? '#8c9ab3' : COLOR.label;
      ctx.fillText(l.text, 0, 0.5);
      ctx.restore();
    }
    ctx.font = '600 11px ui-sans-serif, system-ui, sans-serif'; ctx.textAlign = 'left';
    for (const m of this.landmarks) {
      const [x, y] = this.px(m.p[0], m.p[1]);
      ctx.fillStyle = COLOR.landmark;
      ctx.beginPath(); ctx.arc(x + 14, y - 14, 2.5, 0, Math.PI * 2); ctx.fill();
      ctx.fillText(m.text, x + 20, y - 14);
    }
  }

  draw(sim, now) {
    const { ctx, s, dpr } = this;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.drawImage(this.bg, 0, 0);
    if (!sim || !this.net) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    if (S.heat && S.heatData[this.sid]) {
      if (!this.heatLayer || now - this.heatAt > 500) this.drawHeat(S.heatData[this.sid]);
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.drawImage(this.heatLayer, 0, 0);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    ctx.lineWidth = Math.max(2.5, 2 * s); ctx.lineCap = 'butt';
    for (const lane in sim.sig) {
      const p = this.stops[lane];
      if (!p) continue;
      const [cx, cy] = this.px(p.x, p.y), hw = (p.w / 2) * s + 0.5;
      ctx.strokeStyle = COLOR[sim.sig[lane]] || COLOR.r;
      ctx.beginPath(); ctx.moveTo(cx - p.nx * hw, cy + p.ny * hw); ctx.lineTo(cx + p.nx * hw, cy - p.ny * hw); ctx.stroke();
    }

    const kl = Math.max(0.9, 1.1 * s), kw = (w) => Math.max(2.4, w * s * 1.6);
    const special = [];
    for (const v of sim.veh) {
      const kind = v[4];
      const [wx, wy] = this.R(v[1], v[2]);
      const [px, py] = this.px(wx, wy);
      if (px < -20 || py < -20 || px > this.w + 20 || py > this.h + 20) continue;
      const [L, W] = VEH[kind] || VEH.c;
      const a = ((v[3] - this.rotDeg) * Math.PI) / 180, c = Math.cos(a), sn = Math.sin(a);
      ctx.setTransform(dpr * c, dpr * sn, -dpr * sn, dpr * c, dpr * px, dpr * py);
      if (kind === 'e' || kind === 'x' || v[0] === S.follow) special.push([v, px, py]);
      ctx.fillStyle = kind === 'e' ? COLOR.amb : kind === 'x' ? COLOR.crash : kind === 'b'
        ? (v[5] ? COLOR.busHalted : COLOR.bus) : (v[5] ? COLOR.carHalted : COLOR.car);
      ctx.fillRect(-kw(W) / 2, 0, kw(W), L * kl);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const flash = Math.floor(now / 250) % 2 === 0;
    for (const [v, px, py] of special) {
      if (v[4] === 'e') {
        const r = 10 + 5 * (0.5 + 0.5 * Math.sin(now / 160));
        ctx.fillStyle = flash ? 'rgba(239,68,68,.32)' : 'rgba(96,165,250,.32)';
        ctx.beginPath(); ctx.arc(px, py, r, 0, Math.PI * 2); ctx.fill();
        ctx.strokeStyle = flash ? '#fff' : '#60a5fa'; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.arc(px, py, 5, 0, Math.PI * 2); ctx.stroke();
      } else if (v[4] === 'x') {
        ctx.strokeStyle = `rgba(251,146,60,${0.5 + 0.4 * Math.sin(now / 200)})`; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(px, py, 9, 0, Math.PI * 2); ctx.stroke();
      }
      if (v[0] === S.follow) {
        ctx.strokeStyle = '#ffffff'; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(px, py, 11, 0, Math.PI * 2); ctx.stroke();
        ctx.fillStyle = '#fff'; ctx.font = '700 11px ui-sans-serif, system-ui'; ctx.textAlign = 'left';
        ctx.fillText('you', px + 13, py - 9);
      }
    }
    if (S.inspect) {
      const t = this.tls.find((x) => x.id === S.inspect);
      if (t) {
        const [px, py] = this.px(t.p[0], t.p[1]);
        ctx.setLineDash([4, 3]); ctx.strokeStyle = '#e2e8f0'; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.arc(px, py, Math.max(14, 16 * s), 0, Math.PI * 2); ctx.stroke(); ctx.setLineDash([]);
      }
    }
  }

  // the emissions glow is expensive to stroke, so it is re-rendered twice a second into its own layer
  drawHeat(heat) {
    this.heatAt = performance.now();
    if (!this.heatLayer) this.heatLayer = document.createElement('canvas');
    const c = this.heatLayer;
    if (c.width !== this.canvas.width || c.height !== this.canvas.height) { c.width = this.canvas.width; c.height = this.canvas.height; }
    const ctx = c.getContext('2d');
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, c.width, c.height);
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.lineCap = 'round';
    for (const l of this.lanes) {
      const v = heat[l.edge];
      if (!v) continue;
      const f = Math.min(1, v / S.heatMax) ** 1.4;   // one scale shared by every pane
      if (f < 0.04) continue;
      ctx.strokeStyle = `rgba(255, ${Math.round(190 - 160 * f)}, ${Math.round(70 - 60 * f)}, ${0.08 + 0.55 * f})`;
      ctx.lineWidth = Math.max(3, l.w * this.s * (1.2 + 2.2 * f));
      this.path(ctx, l.pts, false); ctx.stroke();
    }
  }

  click(e) {
    const rect = this.canvas.getBoundingClientRect();
    const [wx, wy] = this.world(e.clientX - rect.left, e.clientY - rect.top);
    const sim = S.frame && S.frame.sims[this.sid];
    let best = null, bd = 9 / Math.min(1, this.s);
    if (sim) for (const v of sim.veh) {
      if (v[4] === 'x') continue;
      const [x, y] = this.R(v[1], v[2]);
      const d = Math.hypot(x - wx, y - wy);
      if (d < bd) { bd = d; best = v[0]; }
    }
    if (best) { setFollow(best); return; }
    let tb = null, td = 30;
    for (const t of this.tls) {
      const d = Math.hypot(t.p[0] - wx, t.p[1] - wy);
      if (d < td) { td = d; tb = t.id; }
    }
    if (tb) setInspect(tb);
  }
}

// ================================================================ panes
async function loadNet(id) {
  if (!S.nets[id]) S.nets[id] = await (await fetch(`scenarios/${id}.json`)).json();
  return S.nets[id];
}

async function buildPanes(scenario, panes) {
  S.scenario = scenario; S.panes = panes;
  S.net = await loadNet(scenario);
  $('attribution').textContent = S.net.meta.attribution || '';
  const box = $('panes');
  box.innerHTML = '';
  box.classList.toggle('four', panes.length > 2);
  S.views = {};
  for (const sid of panes) {
    const st = STRAT[sid];
    const el = document.createElement('section');
    el.className = 'pane';
    el.style.setProperty('--accent', st.color);
    el.innerHTML = `<div class="pane-head"><h2><span class="swatch"></span>${st.label} <em>${st.sub}</em></h2>
      <span class="pane-stat" id="stat-${sid}"></span></div><div class="pane-wrap"></div>`;
    box.appendChild(el);
    const v = new MapView(sid, el.querySelector('.pane-wrap'));
    v.setNet(S.net);
    S.views[sid] = v;
  }
  S.snaps = []; S.race = null; S.heatData = {}; if (!params.get("follow")) { S.follow = null; $("follow").hidden = true; }
  buildChart();
  eventLabels();
  renderInspect(null);
}

// ================================================================ impact panel
const METRICS = [
  { group: 'Traffic' },
  { key: 'delay', label: 'Avg delay / vehicle', unit: 's', wlabel: 'Stopped, s per min driven', lower: true, dec: 1,
    all: (m) => m.avg_delay_s, win: (a, b) => ((b.halt_vs - a.halt_vs) / Math.max(1, b.veh_s - a.veh_s)) * 60 },
  { key: 'stops', label: 'Stops / vehicle', unit: '', wlabel: 'Stops per veh-min', lower: true, dec: 2,
    all: (m) => m.stops / Math.max(1, m.arrived + m.running), win: (a, b) => ((b.stops - a.stops) / Math.max(1, b.veh_s - a.veh_s)) * 60 },
  { key: 'trips', label: 'Trips completed', unit: '', wlabel: 'Trips per min', lower: false, dec: 0, wdec: 1,
    all: (m) => m.arrived, win: (a, b, dt) => ((b.arrived - a.arrived) / dt) * 60 },
  { key: 'wait', label: 'Longest wait now', unit: 's', lower: true, dec: 0, all: (m) => m.max_wait_s, win: (a, b) => b.max_wait_s },
  { group: 'Climate & health' },
  { key: 'idle', label: 'Idling CO₂ (wasted)', unit: 'kg', wlabel: 'Idling CO₂, kg/min', lower: true, dec: 1, wdec: 2,
    all: (m) => m.idle_co2_kg, win: (a, b, dt) => ((b.idle_co2_kg - a.idle_co2_kg) / dt) * 60 },
  { key: 'co2', label: 'Total CO₂', unit: 'kg', wlabel: 'CO₂, kg/min', lower: true, dec: 0, wdec: 1,
    all: (m) => m.co2_kg, win: (a, b, dt) => ((b.co2_kg - a.co2_kg) / dt) * 60 },
  { key: 'fuel', label: 'Fuel burned', unit: '$', pre: true, wlabel: 'Fuel, $/min', lower: true, dec: 0, wdec: 2,
    all: (m) => (m.fuel_l / L_PER_GAL) * USD_PER_GAL, win: (a, b, dt) => (((b.fuel_l - a.fuel_l) / L_PER_GAL) * USD_PER_GAL / dt) * 60 },
  { key: 'nox', label: 'NOx (smog, asthma)', unit: 'g', wlabel: 'NOx, g/min', lower: true, dec: 0, wdec: 1,
    all: (m) => m.nox_g, win: (a, b, dt) => ((b.nox_g - a.nox_g) / dt) * 60 },
  { key: 'pm', label: 'Particulates (PM)', unit: 'g', wlabel: 'PM, g/min', lower: true, dec: 1, wdec: 2,
    all: (m) => m.pm_g, win: (a, b, dt) => ((b.pm_g - a.pm_g) / dt) * 60 },
  { group: 'Civic' },
  { key: 'bus', label: 'Bus trip (avg)', unit: 's', lower: true, dec: 0, all: (m) => m.bus_avg_trip_s, win: (a, b) => b.bus_avg_trip_s },
  { key: 'amb', label: 'Ambulance trip', unit: 's', lower: true, dec: 0, all: (m) => m.amb_last_trip_s, win: (a, b) => b.amb_last_trip_s },
];

function windowPair(sid) {
  if (!S.snaps.length) return null;
  const b = S.snaps[S.snaps.length - 1];
  const target = b.t - Number(S.win);
  let a = S.snaps[0];
  for (const s of S.snaps) { if (s.t <= target) a = s; else break; }
  if (b.t - a.t < 20) return null;
  return [a.m[sid], b.m[sid], b.t - a.t];
}

function metricValue(def, sid) {
  const m = S.frame.sims[sid].m;
  if (S.win === 'all') return def.all(m);
  const p = windowPair(sid);
  return p ? def.win(p[0], p[1], p[2]) : null;
}

function fmtVal(def, v) {
  if (v == null || Number.isNaN(v)) return '—';
  const dec = S.win !== 'all' && def.wdec != null ? def.wdec : def.dec;
  const n = Number(v).toLocaleString(undefined, { minimumFractionDigits: dec, maximumFractionDigits: dec });
  const unit = S.win === 'all' && def.unit && S.panes.length <= 2 ? ` ${def.unit}` : '';
  return def.pre ? `${def.unit}${n}` : `${n}${unit}`;
}

function baseline() { return S.panes.find((p) => p !== 'adaptive'); }

function renderImpact() {
  if (!S.frame) return;
  const panes = S.panes;
  const compact = panes.length > 2;
  $('score').classList.toggle('compact', compact);
  let html = `<tr><th></th>${panes.map((p) => `<th><span class="dot" style="background:${STRAT[p].color}"></span>${compact ? STRAT[p].tag : STRAT[p].label}</th>`).join('')}</tr>`;
  for (const def of METRICS) {
    if (def.group) { html += `<tr class="group"><td colspan="${panes.length + 1}">${def.group}</td></tr>`; continue; }
    const vals = panes.map((p) => metricValue(def, p));
    const ok = vals.filter((v) => v != null && !Number.isNaN(v));
    const best = ok.length > 1 && S.frame.t > 60 ? (def.lower ? Math.min(...ok) : Math.max(...ok)) : null;
    const label = S.win === 'all' ? def.label : (def.wlabel || def.label);
    html += `<tr><td>${label}</td>${vals.map((v) => `<td class="${best != null && v === best && new Set(ok).size > 1 ? 'best' : ''}">${fmtVal(def, v)}</td>`).join('')}</tr>`;
  }
  $('score').innerHTML = html;

  // hero: CivicSignal vs the other pane
  const base = baseline();
  if (!base || !panes.includes('adaptive') || S.frame.t < 60) {
    $('hero').innerHTML = `<div class="vs">The scoreboard fills in once the simulation is running.</div>`;
    $('annual').hidden = true;
    return;
  }
  const pct = (key) => {
    const d = METRICS.find((x) => x.key === key);
    const b = metricValue(d, base), a = metricValue(d, 'adaptive');
    if (b == null || a == null || b === 0) return null;
    return ((a - b) / Math.abs(b)) * 100;
  };
  const cell = (label, v, unit = '%') => {
    if (v == null) return `<div class="stat"><span>${label}</span><b>—</b></div>`;
    const cls = v < -0.5 ? 'good' : v > 0.5 ? 'bad' : '';
    return `<div class="stat"><span>${label}</span><b class="${cls}">${v > 0 ? '+' : '−'}${Math.abs(v).toFixed(0)}${unit}</b></div>`;
  };
  const fb = S.frame.sims[base].m, fa = S.frame.sims.adaptive.m;
  const amb = fb.amb_last_trip_s != null && fa.amb_last_trip_s != null ? fa.amb_last_trip_s - fb.amb_last_trip_s : null;
  $('hero').innerHTML = cell('Delay', pct('delay')) + cell('CO₂', pct('co2')) +
    (amb != null ? cell('Ambulance', amb, ' s') : cell('Stops', pct('stops'))) +
    `<div class="vs">CivicSignal vs <b style="color:${STRAT[base].color}">${STRAT[base].label}</b> · ${S.win === 'all' ? 'since start' : 'last 2 min'} · same cars, same seed</div>`;

  // back-of-envelope yearly impact, from this run's rate
  const t = S.frame.t;
  if (t < 300) { $('annual').hidden = true; return; }
  const k = (RUSH_HOURS_PER_YEAR * 3600) / t;
  const hours = ((fb.halt_vs - fa.halt_vs) / 3600) * k;
  const tons = ((fb.co2_kg - fa.co2_kg) / 1000) * k;
  const gal = ((fb.fuel_l - fa.fuel_l) / L_PER_GAL) * k;
  const n = S.net.meta.expected_tls;
  const f = (x) => Math.round(x).toLocaleString();
  $('annual').hidden = false;
  $('annual').innerHTML = `<h4>If these ${n} signals ran CivicSignal every weekday rush (2 h × 250 days)</h4>
    <div class="grid">
      <div><b>${f(hours)}</b><small>hours of waiting saved / yr</small></div>
      <div><b>${f(tons)} t</b><small>CO₂ avoided / yr</small></div>
      <div><b>${f(gal)}</b><small>gallons of fuel / yr</small></div>
      <div><b>$${f(gal * USD_PER_GAL)}</b><small>fuel cost saved / yr</small></div>
    </div><small>vs ${STRAT[base].label}, scaled from this run's rate. Back-of-envelope, not a forecast.</small>`;
}

// ================================================================ policy panel
function buildPolicy() {
  $('presets').innerHTML = Object.keys(PRESETS).map((k) => `<button data-preset="${k}">${k}</button>`).join('');
  $('sliders').innerHTML = SLIDERS.map((s) => `
    <div class="slider">
      <label for="w-${s.key}">${s.label}<small>${s.sub}</small></label>
      <input type="range" id="w-${s.key}" min="0" max="3" step="0.25">
      <output id="o-${s.key}"></output>
    </div>`).join('');
  for (const s of SLIDERS) {
    $(`w-${s.key}`).addEventListener('input', (e) => { S.weights[s.key] = Number(e.target.value); syncPolicy(); sendWeights(); });
  }
  for (const b of document.querySelectorAll('[data-preset]')) {
    b.addEventListener('click', () => { Object.assign(S.weights, PRESETS[b.dataset.preset]); syncPolicy(); sendWeights(); });
  }
  $('preempt').addEventListener('change', (e) => { S.weights.preempt = e.target.checked; sendWeights(); });
  $('copilot-ask').addEventListener('click', askCopilot);
  $('copilot-text').addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) askCopilot(); });
}

function syncPolicy() {
  for (const s of SLIDERS) {
    const v = S.weights[s.key];
    $(`w-${s.key}`).value = v;
    $(`w-${s.key}`).style.setProperty('--fill', `${(v / 3) * 100}%`);
    $(`o-${s.key}`).textContent = Number(v).toFixed(2);
  }
  $('preempt').checked = S.weights.preempt;
  for (const b of document.querySelectorAll('[data-preset]')) {
    const p = PRESETS[b.dataset.preset];
    b.classList.toggle('active', Object.keys(p).every((k) => p[k] === S.weights[k]));
  }
}

let weightTimer = null;
function sendWeights() {
  clearTimeout(weightTimer);
  weightTimer = setTimeout(() => send({ type: 'weights', ...S.weights }), 60);
}

async function askCopilot() {
  const text = $('copilot-text').value.trim();
  if (!text) return;
  $('copilot-status').textContent = 'Thinking…';
  $('copilot-ask').disabled = true;
  try {
    const res = await fetch('/api/copilot', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) });
    const plan = await res.json();
    if (!res.ok) throw new Error(plan.error || res.status);
    $('copilot-status').textContent = `via ${plan.model}`;
    const ev = plan.event && plan.event !== 'none' ? plan.event : null;
    const evLabel = { ambulance: '🚑 ambulance', surge: '🎭 crowd surge', crash: '💥 crash' }[ev];
    const out = $('copilot-out');
    out.hidden = false;
    out.innerHTML = `<h5>${escapeHtml(plan.title)}</h5><div>${escapeHtml(plan.explanation)}</div>
      <div class="chips">${SLIDERS.map((s) => `<span class="chip">${s.label} ${Number(plan[s.key]).toFixed(2)}</span>`).join('')}
      <span class="chip">Preemption ${plan.preempt ? 'on' : 'off'}</span></div>
      <div class="copilot-row"><button class="btn btn-primary" id="cp-apply">Apply policy</button>
      ${ev ? `<button class="btn" id="cp-apply-ev">Apply + simulate ${evLabel}</button>` : ''}</div>`;
    const apply = () => {
      for (const s of SLIDERS) S.weights[s.key] = Number(plan[s.key]);
      S.weights.preempt = !!plan.preempt;
      syncPolicy(); sendWeights();
      addLog(`Policy applied: <b>${escapeHtml(plan.title)}</b>`);
      toast(`✨ Policy applied: <b>${escapeHtml(plan.title)}</b>`);
    };
    $('cp-apply').onclick = apply;
    if (ev) $('cp-apply-ev').onclick = () => { apply(); fireEvent(ev); };
  } catch (err) {
    $('copilot-status').textContent = `Copilot unavailable: ${err.message}`;
  } finally {
    $('copilot-ask').disabled = false;
  }
}

function escapeHtml(s) { return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }

// ================================================================ events panel
function eventLabels() {
  const m = S.net.meta;
  $('ev-amb-label').textContent = m.ambulance ? m.ambulance.label : '';
  $('ev-surge-label').textContent = m.surge ? `${m.surge.label} · ${m.surge.n} cars over ${Math.round(m.surge.over_s / 60)} min` : '';
  $('ev-crash-label').textContent = m.crash ? `${m.crash.label} · ${m.crash.lanes.length} lanes for ${Math.round(m.crash.duration / 60)} min` : '';
}

function fireEvent(name) {
  if (REPLAY) return;
  send({ type: 'event', name });
  const btn = document.querySelector(`[data-event="${name}"]`);
  if (btn) { btn.disabled = true; setTimeout(() => (btn.disabled = false), 1500); }
}

function addLog(html) {
  const t = S.frame ? mmss(S.frame.t) : '0:00';   // onFrame sets S.frame before events are handled
  S.log.unshift(`<li><time>${t}</time>${html}</li>`);
  S.log = S.log.slice(0, 30);
  $('log').innerHTML = S.log.join('');
}

function handleEvents(frame, quiet = false) {
  const say = quiet ? () => {} : toast;
  for (const ev of frame.events || []) {
    if (ev === 'ambulance_spawned') {
      S.race = { t0: frame.t, done: {} };
      say(`🚑 <b>Ambulance dispatched</b> in every city, same route: ${escapeHtml(S.net.meta.ambulance.label)}`, 'amb');
      addLog('🚑 Ambulance dispatched');
    } else if (ev.startsWith('ambulance_arrived_')) {
      const sid = ev.replace('ambulance_arrived_', '');
      const trip = frame.sims[sid].m.amb_last_trip_s;
      if (S.race) S.race.done[sid] = trip;
      say(`<b style="color:${STRAT[sid].color}">${STRAT[sid].label}</b> ambulance arrived in <b>${mmss(trip)}</b>`, sid === 'adaptive' ? '' : 'warn');
      addLog(`🏥 <b style="color:${STRAT[sid].color}">${STRAT[sid].label}</b> ambulance arrived: ${mmss(trip)}`);
    } else if (ev === 'surge_started') {
      say(`🎭 <b>${escapeHtml(S.net.meta.surge.label)}</b>: ${S.net.meta.surge.n} cars pour out`, 'warn');
      addLog(`🎭 ${escapeHtml(S.net.meta.surge.label)}`);
    } else if (ev === 'crash_started') {
      say(`💥 <b>${escapeHtml(S.net.meta.crash.label)}</b>: lanes blocked for ${Math.round(S.net.meta.crash.duration / 60)} min`, 'warn');
      addLog(`💥 ${escapeHtml(S.net.meta.crash.label)}`);
    } else if (ev === 'sim_end') {
      say('Simulation finished. Press ↺ to run again.');
    }
  }
}

function renderRace() {
  const r = S.race;
  if (!r) { $('race').hidden = true; return; }
  const times = S.panes.map((sid) => {
    const m = S.frame.sims[sid].m;
    if (r.done[sid] != null) return [sid, r.done[sid], true];
    return [sid, m.amb_active ? m.amb_elapsed_s : S.frame.t - r.t0, false];
  });
  const max = Math.max(60, ...times.map((x) => x[1]));
  $('race').hidden = false;
  $('race').innerHTML = `<h4>🚑 Ambulance race · same route, same second</h4>` + times.map(([sid, t, done]) => `
    <div class="lane" style="--accent:${STRAT[sid].color}"><span>${STRAT[sid].label}</span>
    <div class="bar"><i style="width:${(t / max) * 100}%"></i></div><span class="t">${done ? '🏥 ' : ''}${mmss(t)}</span></div>`).join('');
}

// ================================================================ inspector
function setInspect(tls) {
  S.inspect = tls;
  send({ type: 'inspect', tls });
  showTab('inspect');
  S.dirty = true;
}

function renderInspect(data) {
  if (!S.inspect || !data) {
    if (!S.inspect) $('inspect-title').textContent = 'Click any intersection';
    return;
  }
  const any = Object.values(data).find(Boolean);
  if (!any) { $('inspect').innerHTML = '<p class="note">That light is not one of the controlled intersections.</p>'; return; }
  const names = [...new Set(any.approaches.map((a) => short(a.name)))];
  $('inspect-title').textContent = names.join(' & ');
  let html = '';
  for (const sid of S.panes) {
    const d = data[sid];
    if (!d) continue;
    const st = STRAT[sid];
    html += `<div class="ins-pane" style="--accent:${st.color}"><h4>${st.label}<span>${d.program ? `program ${d.program}` : 'CivicSignal'}</span></h4>`;
    for (const a of d.approaches) {
      html += `<div class="appr"><span class="light ${a.signal}"></span><span>${short(a.name)}</span>
        <small>${a.queue} queued · ${a.moving} moving${a.buses ? ` · 🚌${a.buses}` : ''}${a.max_wait_s ? ` · ${a.max_wait_s}s wait` : ''}${a.ambulance_m != null ? ` · 🚑 ${Math.round(a.ambulance_m)} m` : ''}</small></div>`;
    }
    if (d.controller) {
      const c = d.controller;
      html += `<div class="why"><b>Why:</b> ${escapeHtml(c.reason)}</div>`;
      const maxTot = Math.max(1, ...c.options.map((o) => Object.values(o.terms).reduce((s, v) => s + Math.max(0, v), 0)));
      for (const o of c.options) {
        const serves = o.serves.map(short).join(' + ');
        html += `<div class="opt ${o.current ? 'cur' : ''}"><div class="row"><span>${o.current ? 'Green now: ' : o.target ? 'Switching to: ' : ''}${serves}</span><b>score ${o.total.toFixed(1)}</b></div>
          <div class="stack">${Object.entries(o.terms).map(([k, v]) => v > 0 ? `<i style="width:${(v / maxTot) * 100}%;background:${TERM_COLORS[k]}" title="${k} ${v}"></i>` : '').join('')}</div>
          <div class="terms">${Object.entries(o.terms).filter(([, v]) => v !== 0).map(([k, v]) => `<span style="color:${TERM_COLORS[k]}">${k} ${v > 0 ? '+' : '−'}${Math.abs(v).toFixed(1)}</span>`).join(' ') || '<span class="muted">nothing waiting</span>'}</div></div>`;
      }
      html += `<div class="legend">${Object.entries(TERM_COLORS).map(([k, c]) => `<span><i style="background:${c}"></i>${k}</span>`).join('')}</div>
        <small class="muted">Switches when another green beats the current one by ${c.hyst}, after ${c.min_green} s minimum green; ${c.max_green} s maximum.</small>`;
    } else {
      html += `<div class="note">${st.how}${d.next_switch_s != null ? ` Next switch in <b>${Math.max(0, d.next_switch_s)} s</b>, whoever is waiting.` : ''}</div>`;
    }
    html += '</div>';
  }
  $('inspect').innerHTML = html;
}

// ================================================================ follow a commuter
function setFollow(vid) {
  S.follow = vid;
  send({ type: 'follow', vid });
  S.dirty = true;
}

function renderFollow() {
  const box = $('follow');
  if (!S.follow || !S.frame) { box.hidden = true; return; }
  box.hidden = false;
  const ft = S.followTrip && S.followTrip.vid === S.follow ? S.followTrip : null;
  const parts = S.panes.map((sid) => {
    const trip = ft && ft[sid];
    let txt = '…';
    if (trip && trip.arrive != null) txt = `🏁 ${mmss(trip.arrive - trip.depart)}`;
    else if (trip && trip.depart != null) txt = `${mmss(S.frame.t - trip.depart)} <small class="muted">driving</small>`;
    else if (trip) txt = '<small class="muted">not yet left</small>';
    return `<span style="color:${STRAT[sid].color}">${STRAT[sid].label}</span> <b>${txt}</b>`;
  });
  box.innerHTML = `<span>🚗 Same driver, same departure</span>${parts.join(' · ')}<span class="fx" title="Stop following">✕</span>`;
  box.querySelector('.fx').onclick = () => { S.follow = null; send({ type: 'follow', vid: null }); box.hidden = true; };
}

// ================================================================ chart
let chart, chartDirty = false;
const qwin = {};
function buildChart() {
  if (chart) chart.destroy();
  if (VIEW) return;
  const rush = S.net.meta.rush || [600, 1800];
  const end = S.net.meta.end || 2400;
  const rushBand = {
    id: 'rush',
    beforeDatasetsDraw(c) {
      const { ctx, chartArea: a, scales: { x } } = c;
      const l = x.getPixelForValue(rush[0]), r = x.getPixelForValue(rush[1]);
      ctx.save(); ctx.fillStyle = 'rgba(245,165,36,0.06)'; ctx.fillRect(l, a.top, r - l, a.bottom - a.top);
      ctx.fillStyle = 'rgba(245,165,36,0.55)'; ctx.font = '600 10px system-ui, sans-serif'; ctx.fillText('RUSH HOUR', l + 6, a.top + 12);
      ctx.restore();
    },
  };
  const ds = [];
  for (const sid of S.panes) {
    ds.push({ label: STRAT[sid].label, data: [], borderColor: STRAT[sid].color, backgroundColor: STRAT[sid].color, yAxisID: 'co2', borderWidth: 2.4, pointRadius: 0, tension: 0.25 });
    qwin[sid] = [];
  }
  for (const sid of S.panes) {
    ds.push({ label: `${STRAT[sid].label} queue`, data: [], borderColor: STRAT[sid].color + 'aa', yAxisID: 'q', borderWidth: 1.3, borderDash: [5, 4], pointRadius: 0, tension: 0.25 });
  }
  Chart.defaults.color = '#8494ad';
  Chart.defaults.font.family = 'ui-sans-serif, system-ui, -apple-system, sans-serif';
  chart = new Chart($('chart'), {
    type: 'line', data: { datasets: ds },
    options: {
      animation: false, parsing: false, normalized: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: { legend: { position: 'right', labels: { boxWidth: 12, boxHeight: 3, padding: 8, filter: (i) => i.datasetIndex < S.panes.length } },
                 tooltip: { callbacks: { title: (it) => mmss(it[0].parsed.x) } } },
      scales: {
        x: { type: 'linear', min: 0, max: end, grid: { color: '#192130' }, ticks: { stepSize: 300, callback: (v) => `${v / 60} min` } },
        co2: { position: 'left', beginAtZero: true, grid: { color: '#192130' }, title: { display: true, text: 'kg CO₂ idling' } },
        q: { position: 'right', beginAtZero: true, grid: { drawOnChartArea: false }, title: { display: true, text: 'queued' } },
      },
    },
    plugins: [rushBand],
  });
  S.lastChartT = -Infinity;
}

function pushChart(t, mBySid) {
  if (!chart) return;
  const n = S.panes.length;
  S.panes.forEach((sid, i) => {
    const m = mBySid[sid];
    if (!m) return;
    qwin[sid].push(m.queue);
    if (qwin[sid].length > QUEUE_SMOOTH) qwin[sid].shift();
  });
  if (t - S.lastChartT < CHART_EVERY) return;
  S.lastChartT = t;
  S.panes.forEach((sid, i) => {
    const m = mBySid[sid];
    if (!m) return;
    chart.data.datasets[i].data.push({ x: t, y: m.idle_co2_kg });
    const q = qwin[sid];
    chart.data.datasets[n + i].data.push({ x: t, y: q.reduce((s, x) => s + x, 0) / q.length });
  });
  chartDirty = true;
}
setInterval(() => { if (chart && chartDirty) { chart.update('none'); chartDirty = false; } }, 300);

// ================================================================ frames & state
function onFrame(frame, quiet = false) {
  if (frame.t < S.lastT) { buildChart(); S.snaps = []; S.race = null; }
  S.lastT = frame.t;
  S.frame = frame;
  S.dirty = true;
  const mBySid = {};
  for (const sid of S.panes) if (frame.sims[sid]) mBySid[sid] = frame.sims[sid].m;
  S.snaps.push({ t: frame.t, m: mBySid });
  while (S.snaps.length && frame.t - S.snaps[0].t > WINDOW_KEEP) S.snaps.shift();
  pushChart(frame.t, mBySid);
  let mx = 0;
  for (const sid of S.panes) {
    const h = frame.sims[sid] && frame.sims[sid].heat;   // sent every 5th frame; keep the latest
    if (h) { S.heatData[sid] = h; for (const k in h) mx = Math.max(mx, h[k]); }
  }
  if (mx) S.heatMax = 0.9 * S.heatMax + 0.1 * Math.max(4, mx);
  handleEvents(frame, quiet);   // a replay seek still fills the race and log, just without toasts
  if (frame.inspect) S.pendingInspect = frame.inspect;
  if (frame.follow) S.followTrip = frame.follow;
}

async function onState(st) {
  S.state = st;
  Object.assign(S.weights, st.weights);
  S.playing = st.playing;
  S.sps = st.sps;
  S.inspect = st.inspect || null;   // shared across windows: a pop-out inspector follows clicks anywhere
  const sel = $('scenario');
  if (sel.options.length !== Object.keys(st.scenarios).length) {
    sel.innerHTML = Object.entries(st.scenarios).map(([id, s]) => `<option value="${id}">${s.title}</option>`).join('');
  }
  sel.value = st.scenario;
  const lay = $('layout'), key = st.panes.join(',');
  if (![...lay.options].some((o) => o.value === key)) lay.add(new Option(st.panes.map((p) => STRAT[p].label).join(' vs '), key));
  lay.value = key;
  if (st.scenario !== S.scenario || key !== S.panes.join(',')) await buildPanes(st.scenario, st.panes);
  if (st.follow !== undefined && !params.get('follow')) S.follow = st.follow;   // after buildPanes, which resets it
  $('copilot-ask').disabled = !st.copilot;
  if (!st.copilot) $('copilot-status').textContent = 'Add GEMINI_API_KEY to .env and restart the server to enable.';
  else if ($('copilot-status').textContent.startsWith('Add')) $('copilot-status').textContent = '';
  syncControls();
  syncPolicy();
}

function onHistory(h) {
  if (h.scenario !== S.scenario) return;
  buildChart();
  for (const [t, panes] of h.points) {
    const m = {};
    for (const sid in panes) m[sid] = { idle_co2_kg: panes[sid][0], queue: panes[sid][1] };
    pushChart(t, m);
  }
  S.lastT = h.points.length ? h.points[h.points.length - 1][0] : -1;
}

function syncControls() {
  $('play').textContent = S.playing ? '❚❚ Pause' : '▶ Play';
  const sp = $('speed');
  if (![...sp.options].some((o) => Number(o.value) === S.sps)) sp.add(new Option(`${S.sps / 10}×`, S.sps));
  sp.value = String(S.sps);
  $('heat').classList.toggle('on', S.heat);
}

function render(now) {
  if (S.frame && S.net) {
    for (const sid of S.panes) if (S.views[sid]) S.views[sid].draw(S.frame.sims[sid], now);
    if (S.dirty) {
      const t = S.frame.t, rush = S.net.meta.rush || [600, 1800];
      $('clock').textContent = mmss(t);
      const inRush = t >= rush[0] && t < rush[1];
      $('phase').textContent = inRush ? 'Rush hour' : t < rush[0] ? 'Off-peak' : 'Evening';
      $('phase').classList.toggle('rush', inRush);
      for (const sid of S.panes) {
        const m = S.frame.sims[sid] && S.frame.sims[sid].m;
        if (!m) continue;
        let s = `queued <b>${m.queue}</b> · moving <b>${Math.max(0, m.running - m.queue)}</b> · delay <b>${m.avg_delay_s.toFixed(0)}s</b>`;
        if (m.amb_active) s += ` · <span class="amb">🚑 ${mmss(m.amb_elapsed_s)}</span>`;
        else if (m.amb_last_trip_s != null) s += ` · <span class="ok">🏥 ${mmss(m.amb_last_trip_s)}</span>`;
        const el = $(`stat-${sid}`);
        if (el) el.innerHTML = s;
      }
      renderImpactThrottled();
      renderRace();
      renderFollow();
      if (S.pendingInspect) { renderInspect(S.pendingInspect); S.pendingInspect = null; }
      S.dirty = false;
    }
  }
  requestAnimationFrame(render);
}

let impactAt = -Infinity, impactTimer = null;
function renderImpactThrottled() {   // at most every 400 ms, and the last update is never dropped
  const wait = 400 - (performance.now() - impactAt);
  if (wait <= 0) { impactAt = performance.now(); renderImpact(); return; }
  if (!impactTimer) impactTimer = setTimeout(() => { impactTimer = null; impactAt = performance.now(); renderImpact(); }, wait);
}

// ================================================================ ui plumbing
function send(msg) { if (S.ws && S.ws.readyState === WebSocket.OPEN) S.ws.send(JSON.stringify(msg)); }

function showTab(name) {
  for (const b of document.querySelectorAll('.tabs button')) b.classList.toggle('active', b.dataset.tab === name);
  for (const t of document.querySelectorAll('.tab')) t.hidden = t.id !== `tab-${name}`;
}

function toast(html, kind = '') {
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.innerHTML = html;
  $('toasts').appendChild(el);
  setTimeout(() => el.remove(), 5500);
}

function togglePlay() {
  S.playing = !S.playing;
  if (REPLAY) replay.setPlaying(S.playing); else send({ type: 'control', action: S.playing ? 'play' : 'pause' });
  syncControls();
}

function wire() {
  $('play').onclick = togglePlay;
  $('reset').onclick = () => (REPLAY ? replay.restart() : send({ type: 'control', action: 'reset' }));
  $('speed').onchange = (e) => { S.sps = Number(e.target.value); if (!REPLAY) send({ type: 'speed', sps: S.sps }); };
  $('heat').onclick = () => { S.heat = !S.heat; syncControls(); };
  $('scenario').onchange = (e) => send({ type: 'config', scenario: e.target.value, panes: S.panes });
  $('layout').onchange = (e) => send({ type: 'config', scenario: S.scenario, panes: e.target.value.split(',') });
  for (const b of document.querySelectorAll('.tabs button')) b.onclick = () => showTab(b.dataset.tab);
  for (const b of document.querySelectorAll('[data-event]')) b.onclick = () => fireEvent(b.dataset.event);
  for (const b of document.querySelectorAll('#window-seg button')) {
    b.onclick = () => {
      S.win = b.dataset.win;
      for (const x of document.querySelectorAll('#window-seg button')) x.classList.toggle('active', x === b);
      renderImpact();
    };
  }
  for (const b of document.querySelectorAll('[data-pop]')) {
    b.onclick = () => window.open(`/?view=${b.dataset.pop}`, `civicsignal-${b.dataset.pop}`, 'width=560,height=860');
  }
  document.addEventListener('keydown', (e) => {
    if (['TEXTAREA', 'SELECT'].includes(e.target.tagName) || (e.target.tagName === 'INPUT' && e.target.type !== 'range')) return;
    if (e.code === 'Space') { e.preventDefault(); togglePlay(); }
    else if (e.key === 'a' || e.key === 'A') fireEvent('ambulance');
    else if (e.key === 's' || e.key === 'S') fireEvent('surge');
    else if (e.key === 'c' || e.key === 'C') fireEvent('crash');
    else if (e.key === 'h' || e.key === 'H') { S.heat = !S.heat; syncControls(); }
    else if (e.key === 'Escape') { S.follow = null; S.inspect = null; send({ type: 'inspect', tls: null }); send({ type: 'follow', vid: null }); renderFollow(); }
  });
}

// ================================================================ live server
function connect() {
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
  S.ws = ws;
  ws.onopen = () => { $('conn').className = 'conn on'; $('banner').hidden = true; };
  // handle messages strictly in order: a state message may await the map file before frames can draw on it
  let chain = Promise.resolve();
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    chain = chain.then(async () => {
      if (msg.type === 'frame') { if (msg.scenario === S.scenario && S.net) onFrame(msg); }
      else if (msg.type === 'state') await onState(msg);
      else if (msg.type === 'history') { if (S.net) onHistory(msg); }
    }).catch((err) => console.error(err));
  };
  ws.onclose = () => {
    $('conn').className = 'conn off';
    $('banner').innerHTML = 'Not connected to the sim server. Run <code>python server.py</code>. Retrying…';
    $('banner').hidden = false;
    setTimeout(connect, 1500);
  };
}

// ================================================================ replay mode
const replay = {
  lines: [], i: 0, timer: null,
  async load(url) {
    $('mode').hidden = false; $('conn').hidden = true;
    for (const el of document.querySelectorAll('[data-event], #scenario, #layout, #copilot-ask')) el.disabled = true;
    const res = await fetch(url);
    if (!res.ok) { toast(`Could not load replay ${url} (${res.status})`, 'amb'); return; }
    this.lines = (await res.text()).split('\n').filter(Boolean);
    const first = JSON.parse(this.lines[0]);
    if (first.type === 'state') { await onState({ ...first, playing: false }); this.lines.shift(); }
    toast(`Replay loaded: ${this.lines.length} frames`);
    this.seek(Number(params.get('t')) || 0);
    if (params.has('autoplay')) { S.playing = true; syncControls(); this.setPlaying(true); }
  },
  seek(t) {
    this.i = 0; buildChart(); S.snaps = []; S.lastT = -1;
    while (this.i < this.lines.length - 1) {
      const f = JSON.parse(this.lines[this.i]);
      if (f.t >= t) break;
      onFrame(f, true); this.i++;
    }
    this.stepOnce();
  },
  stepOnce() {
    if (this.i >= this.lines.length) { S.playing = false; syncControls(); return; }
    onFrame(JSON.parse(this.lines[this.i++]));
  },
  setPlaying(on) {
    clearTimeout(this.timer);
    if (!on) return;
    const tick = () => {
      const t0 = performance.now();
      this.stepOnce();
      if (S.playing) this.timer = setTimeout(tick, Math.max(0, 1000 / S.sps - (performance.now() - t0)));
    };
    tick();
  },
  restart() { this.seek(Number(params.get('t')) || 0); },
};

// ================================================================ boot
function boot() {
  buildPolicy();
  wire();
  if (VIEW) { document.body.classList.add('solo'); showTab(VIEW); }
  else if (params.get('tab')) showTab(params.get('tab'));
  if (params.has('heat')) { S.heat = true; syncControls(); }
  if (params.get('ask')) {   // ?ask=... types a copilot prompt and submits it (clean takes for recordings)
    showTab('policy');
    $('copilot-text').value = params.get('ask');
    setTimeout(askCopilot, 1500);
  }
  if (params.get('follow')) { S.follow = params.get('follow'); setTimeout(() => send({ type: 'follow', vid: S.follow }), 800); }
  requestAnimationFrame(render);
  if (REPLAY) replay.load(REPLAY); else connect();
}
boot();
