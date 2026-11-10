/* Political Weather — interactive U.S. election contour maps.
   Surfaces are computed in the browser from county results: each county's
   votes are placed at its census tracts' population centres (cells_*.json),
   small counties are shrunk toward their regional mean, and the grid is
   Gaussian-smoothed (vote-weighted Nadaraya-Watson) on a projected EPSG:5070
   grid. Swing uses only counties contested in BOTH years. d3-contour builds
   the bands; two levels of detail (75 km / 40 km) are revealed as you zoom. */
'use strict';

const DATA = 'data/';
const state = { meta:null, cells:{}, states:null, land:null, counties:null, capitals:null, majors:null, towns:[], stateLabels:[], showStates:true,
                landmask:null, base:null, cmp:null, mode:'abs', lod:null, loading:{},
                showCaps:true, showMajors:true, vmaxAbs:10, vmaxDev:10, natl:0 };

const svg = d3.select('#map');
const gZoom = svg.append('g');
const gContour = gZoom.append('g');
const gStates = gZoom.append('g');
const gCaps = svg.append('g').style('pointer-events', 'none');
const tip = d3.select('#tip');

let S = 1, OFFX = 0, OFFY = 0, MINX = 0, MINY = 0, MAXX = 0, MAXY = 0, MPATH = null;
const sx = X => OFFX + (X - MINX) * S;
const sy = Y => OFFY + (MAXY - Y) * S;
function colorScale(vmax){ return d3.scaleDiverging(t => d3.interpolateRdBu(t)).domain([-vmax, 0, vmax]); }
function metrePath(){ return d3.geoPath(d3.geoTransform({ point(X,Y){ this.stream.point(sx(X), sy(Y)); } })); }
function gridPath(l){ return d3.geoPath(d3.geoTransform({ point(i,j){ this.stream.point(sx(l.x0 + i*l.dx), sy(l.y0 + j*l.dy)); } })); }
function pickLOD(k){ let L = state.meta.lods[0]; for (const l of state.meta.lods) if (k >= l.zmin) L = l; return L; }

// County -> grid-cell population placement for one LOD (loaded on demand).
function ensureCells(lod){
  if (state.cells[lod.name]) return Promise.resolve(state.cells[lod.name]);
  const id = 'cells_' + lod.name;
  if (!state.loading[id]) state.loading[id] = d3.json(`${DATA}${id}.json`).then(d => {
    state.cells[lod.name] = { off: Int32Array.from(d.off), i: Int32Array.from(d.i), f: Float64Array.from(d.f) };
    return state.cells[lod.name];
  });
  return state.loading[id];
}

async function load(){
  const meta = await d3.json(DATA + 'meta.json');
  state.meta = meta;
  [MINX, MINY, MAXX, MAXY] = meta.bounds;
  const [states, land, counties, capitals, majors, landmask] = await Promise.all([
    d3.json(DATA + 'states.json'), d3.json(DATA + 'land.json'), d3.json(DATA + 'counties.json'),
    d3.json(DATA + 'capitals.json'), d3.json(DATA + 'majors.json'), d3.json(DATA + 'landmask_coarse.json')]);
  // Smaller towns only matter once zoomed in, so load them in the background.
  d3.json(DATA + 'state_labels.json').then(t => { state.stateLabels = t; positionPlaces(); }).catch(() => {});
  d3.json(DATA + 'towns.json').then(t => { state.towns = t; positionPlaces(); }).catch(() => {});
  state.states = states; state.land = land; state.counties = counties;
  state.capitals = capitals; state.majors = majors; state.landmask = landmask;
  state.base = meta.default.base; state.cmp = meta.default.comparison; state.lod = meta.lods[0];

  const keys = Object.keys(meta.years);
  const fill = sel => d3.select(sel).selectAll('option').data(keys).join('option')
      .attr('value', d => d).text(d => meta.years[d].label);
  fill('#baseSel'); fill('#cmpSel');
  d3.select('#baseSel').property('value', state.base);
  d3.select('#cmpSel').property('value', state.cmp);
  d3.select('#baseSel').on('change', e => changePair('base', e.target.value));
  d3.select('#cmpSel').on('change', e => changePair('cmp', e.target.value));
  d3.selectAll('#mode button').on('click', function(){
    d3.selectAll('#mode button').classed('active', false);
    d3.select(this).classed('active', true); state.mode = this.dataset.mode;
    const m = state.mode === 'margin';
    d3.select('#baseSel').property('disabled', m).style('opacity', m ? 0.4 : 1);
    d3.select('#baseLabel').text(m ? 'Baseline (n/a)' : 'Baseline');
    render();
  });
  d3.select('#reset').on('click', () => svg.transition().duration(400).call(zoom.transform, d3.zoomIdentity));
  d3.select('#capToggle').on('change', function(){ state.showCaps = this.checked; positionPlaces(); });
  d3.select('#stToggle').on('change', function(){ state.showStates = this.checked; positionPlaces(); });
  d3.select('#majToggle').on('change', function(){ state.showMajors = this.checked; positionPlaces(); });

  svg.append('clipPath').attr('id', 'landclip').append('path');
  gContour.attr('clip-path', 'url(#landclip)');

  d3.select('#footer').html(
    `Source: <a href="https://github.com/mike10010100/elections-2026" target="_blank" rel="noopener">mike10010100/elections-2026</a>
     (compiles NYT returns${srcCommit(meta)}) · <b>PROVISIONAL, pre-certification</b> · fetched ${meta.fetched_at.slice(0,16)} ·
     CONUS Albers Equal Area · each county's votes placed at its census tracts' population centres (Census 2020), small counties shrunk toward
     their regional mean, then Gaussian-smoothed and weighted by two-party votes · swing uses only counties with a genuine two-party
     House race in <b>both</b> years (uncontested and same-party top-two districts excluded). County-level House swing is noisy: read regional tendency, not local values.
     Place names: <a href="https://www.geonames.org/" target="_blank" rel="noopener">GeoNames</a> (CC BY 4.0).
     Alaska: at-large RCV result pending. Hawai&#699;i: see the static maps in the repo.`);

  await ensureCells(state.meta.lods[0]);
  computePairStats();
  computeVmax();
  resize();
  // Re-fit whenever the map box changes size: window resizes, rotation, and the
  // shared site header arriving after first paint (it shrinks the map area).
  new ResizeObserver(resize).observe(document.getElementById('wrap'));
}

// Which upstream snapshot was used; flags a fallback when the latest was degraded.
function srcCommit(meta){
  const c = meta.source_commit;
  if (!c) return '';
  const link = `<a href="https://github.com/${c.repo}/commit/${c.sha}" target="_blank" rel="noopener">${c.sha.slice(0,7)}</a>`;
  return c.fell_back ? `, snapshot ${link} — <b>latest upstream snapshot failed coverage checks; using last good one</b>`
                     : `, snapshot ${link}`;
}

async function changePair(which, value){
  state[which] = value;
  computePairStats();
  computeVmax();
  render();
}

// Per-county inputs for a surface: value + weight, or null where unusable.
//  margin: the focus year's contested counties, weighted by its two-party votes
//  swing:  counties contested in BOTH years, value = margin change, weighted by
//          focus-year two-party votes (as in the static pipeline)
function countyInputs(kind){
  const b = state.base, c = state.cmp, n = state.counties.length;
  const v = new Float64Array(n), w = new Float64Array(n);
  for (let k = 0; k < n; k++){
    const K = state.counties[k], mc = K.m[c], wc = K.w[c];
    if (mc == null || !(wc > 0)) continue;
    if (kind === 'margin'){ v[k] = mc; w[k] = wc; continue; }
    const mb = K.m[b];
    if (mb == null) continue;
    v[k] = mc - mb; w[k] = wc;
  }
  return { v, w };
}

// National swing = vote-weighted mean county swing over the matched set, so
// "Deviation" is measured against the same counties the surface uses.
function computePairStats(){
  const { v, w } = countyInputs('swing');
  let sw = 0, sv = 0, n = 0;
  for (let k = 0; k < v.length; k++) if (w[k] > 0){ sw += w[k]; sv += w[k] * v[k]; n++; }
  state.natl = sw > 0 ? +(sv / sw).toFixed(2) : 0;
  state.nPair = n;
}

// Separable Gaussian blur of a grid (sigma in cells, truncated at 5 sigma).
function blur(src, nx, ny, sig){
  const r = Math.ceil(5 * sig), k = new Float64Array(2 * r + 1);
  for (let t = -r; t <= r; t++) k[t + r] = Math.exp(-t * t / (2 * sig * sig));
  const tmp = new Float64Array(nx * ny), out = new Float64Array(nx * ny);
  for (let j = 0; j < ny; j++){
    const row = j * nx;
    for (let i = 0; i < nx; i++){
      const a = src[row + i]; if (a === 0) continue;
      const i0 = Math.max(0, i - r), i1 = Math.min(nx - 1, i + r);
      for (let q = i0; q <= i1; q++) tmp[row + q] += a * k[q - i + r];
    }
  }
  for (let j = 0; j < ny; j++){
    const j0 = Math.max(0, j - r), j1 = Math.min(ny - 1, j + r);
    for (let i = 0; i < nx; i++){
      const a = tmp[j * nx + i]; if (a === 0) continue;
      for (let q = j0; q <= j1; q++) out[q * nx + i] += a * k[q - j + r];
    }
  }
  return out;
}

// Deposit county values at their population cells and smooth:
// Z = blur(sum w*f*v) / blur(sum w*f). Returns { Z, den }.
function smooth(v, w, lod, sigM){
  const C = state.cells[lod.name], n = lod.nx * lod.ny;
  const num = new Float64Array(n), den = new Float64Array(n);
  for (let k = 0; k < v.length; k++){
    if (!(w[k] > 0)) continue;
    for (let e = C.off[k]; e < C.off[k + 1]; e++){
      const a = w[k] * C.f[e]; num[C.i[e]] += a * v[k]; den[C.i[e]] += a;
    }
  }
  const N = blur(num, lod.nx, lod.ny, sigM / lod.dx), D = blur(den, lod.nx, lod.ny, sigM / lod.dx);
  const Z = new Float64Array(n);
  for (let i = 0; i < n; i++) Z[i] = D[i] > 1e-9 ? N[i] / D[i] : NaN;
  return Z;
}

// Small-county shrinkage toward the regional (wide-bandwidth) mean, so a lone
// low-vote county can't paint a whole region: v' = (w v + K r) / (w + K).
function shrink(v, w){
  const sm = state.meta.smoothing, K = sm.shrink_k_votes, lod0 = state.meta.lods[0];
  const R = smooth(v, w, lod0, sm.shrink_bw_km * 1000), C = state.cells[lod0.name];
  const out = Float64Array.from(v);
  for (let k = 0; k < v.length; k++){
    if (!(w[k] > 0)) continue;
    let r = 0, fs = 0;
    for (let e = C.off[k]; e < C.off[k + 1]; e++){ const z = R[C.i[e]]; if (z === z){ r += C.f[e] * z; fs += C.f[e]; } }
    if (fs > 0) out[k] = (w[k] * v[k] + K * (r / fs)) / (w[k] + K);
  }
  return out;
}

const fieldCache = {};
function surface(kind, lod){
  const key = `${kind}|${kind === 'margin' ? '' : state.base}|${state.cmp}|${lod.name}`;
  if (fieldCache[key]) return fieldCache[key];
  const { v, w } = countyInputs(kind);
  const Z = smooth(shrink(v, w), w, lod, lod.bw_km * 1000);
  // Cells beyond reach of every county (offshore; clipped anyway) get a
  // neutral value: national margin, or national swing.
  const fill = kind === 'margin' ? state.meta.years[state.cmp].national : state.natl;
  const out = new Array(Z.length);
  for (let i = 0; i < Z.length; i++) out[i] = Z[i] === Z[i] ? Z[i] : fill;
  return (fieldCache[key] = out);
}

// Colour-scale domains from the coarse surface, over LAND cells only
// (offshore extrapolation would otherwise inflate the scale); stable across zoom.
function computeVmax(){
  const lod0 = state.meta.lods[0], mask = state.landmask.mask;
  const gm = surface('margin', lod0), gs = surface('swing', lod0);
  const abs = [], dev = [], mar = [];
  for (let i = 0; i < gs.length; i++){
    if (mask[i] !== '1') continue;
    abs.push(Math.abs(gs[i])); dev.push(Math.abs(gs[i] - state.natl)); mar.push(Math.abs(gm[i]));
  }
  const pct = (a, q) => { a.sort((x, y) => x - y); return a.length ? a[Math.floor(q * (a.length - 1))] : 10; };
  state.vmaxAbs = Math.max(2, Math.ceil(pct(abs, 0.98)));
  state.vmaxDev = Math.max(2, Math.ceil(pct(dev, 0.98)));
  state.vmaxMargin = Math.max(2, Math.ceil(pct(mar, 0.98)));
}

function field(){
  const cl = state.meta.years[state.cmp].label;
  if (state.mode === 'margin')
    return { F: surface('margin', state.lod), vmax: state.vmaxMargin, title: `Margin (pts) · ${cl}` };
  const bl = state.meta.years[state.base].label;
  const swing = surface('swing', state.lod);
  if (state.mode === 'abs')
    return { F: swing, vmax: state.vmaxAbs, title: `Swing (pts) · ${bl} → ${cl}` };
  return { F: swing.map(v => v - state.natl), vmax: state.vmaxDev,
           title: `Deviation from national ${state.natl>0?'+':''}${state.natl.toFixed(1)} pts · ${bl} → ${cl}` };
}

function render(){
  if (!MPATH || !state.cells[state.lod.name]) return;
  const { F, vmax, title } = field();
  const color = colorScale(vmax);
  const step = vmax > 20 ? 3 : (vmax > 8 ? 2 : 1);
  const thr = d3.range(-Math.ceil(vmax/step)*step, Math.ceil(vmax/step)*step + step, step);
  // Clamp to the scale so values beyond +/-vmax stay filled (d3-contour only
  // fills from the lowest threshold up; unclamped extremes leave white "eyes").
  const Fc = F.map(v => v < -vmax ? -vmax : (v > vmax ? vmax : v));
  const contours = d3.contours().size([state.lod.nx, state.lod.ny]).thresholds(thr)(Fc);
  const gpath = gridPath(state.lod), k = d3.zoomTransform(svg.node()).k;
  gContour.selectAll('path').data(contours).join('path')
      .attr('d', gpath).attr('fill', d => color(d.value + step/2))
      .attr('stroke', '#00000022').attr('stroke-width', 0.3/k).attr('vector-effect', 'non-scaling-stroke');
  gStates.selectAll('path').data(state.states.features).join('path').attr('class', 'state').attr('d', MPATH);
  drawLegend(vmax, color, title);
  d3.select('#status').text(`Smoothing: ${state.lod.bw_km} km${state.lod === state.meta.lods[0] ? ' · zoom in for finer detail' : ' (fine)'}`);
  positionPlaces();
}

function drawLegend(vmax, color, title){
  d3.select('#legend-title').text(title);
  const w = 320, h = 14, n = 60, lsvg = d3.select('#legend-svg');
  lsvg.selectAll('*').remove();
  const x = d3.scaleLinear().domain([0, n-1]).range([-vmax, vmax]);
  lsvg.append('g').selectAll('rect').data(d3.range(n)).join('rect')
      .attr('x', i => i*(w/n)).attr('width', w/n+1).attr('height', h).attr('fill', i => color(x(i)));
  const sc = d3.scaleLinear().domain([-vmax, vmax]).range([0, w]);
  lsvg.append('g').attr('transform', `translate(0,${h})`)
      .call(d3.axisBottom(sc).tickValues((st => d3.range(-Math.floor(vmax/st)*st, vmax+0.001, st))(vmax > 25 ? 10 : 5)).tickSize(4).tickFormat(d => (d>0?'+':'')+d))
      .call(g => g.select('.domain').remove()).selectAll('text').attr('font-size', 9);
  lsvg.append('text').attr('x', 0).attr('y', 47).attr('font-size', 10).attr('font-weight', 600)
      .attr('fill', '#b2182b').text('← more Republican');
  lsvg.append('text').attr('x', w).attr('y', 47).attr('text-anchor', 'end').attr('font-size', 10)
      .attr('font-weight', 600).attr('fill', '#2166ac').text('more Democratic →');
}

function positionPlaces(){
  if (!MPATH){ gCaps.selectAll('*').remove(); return; }
  const t = d3.zoomTransform(svg.node());
  const W = svg.node().clientWidth, H = svg.node().clientHeight;
  const narrow = W < 600;
  const onScreen = c => { c.X = t.applyX(sx(c.x)); c.Y = t.applyY(sy(c.y));
                          return c.X > -20 && c.X < W+20 && c.Y > -10 && c.Y < H+10; };
  const hits = box => placed.some(p => !(box[2]<p[0] || box[0]>p[2] || box[3]<p[1] || box[1]>p[3]));

  // Placement order (each claims space the next must avoid):
  //   1. capitals + major cities, by population
  //   2. two-letter state codes, biggest states first
  //   3. smaller towns, by population — only once zoomed in (k >= 2)
  // The label budget grows with zoom; collision checks keep it legible.
  const maxPlaces = Math.round((20 * Math.min(1, W / 900) + 4) * Math.pow(t.k, 1.1));
  const placed = [], show = [], stShow = [];
  const placeCity = c => {
    const w = c.n.length * (c.t === 'town' ? 5.4 : 6) + 8;
    c.left = c.X + 5 + w > W;   // flip the label left of the dot at the right edge
    const box = c.left ? [c.X-5-w, c.Y-6, c.X-5, c.Y+6] : [c.X+5, c.Y-6, c.X+5+w, c.Y+6];
    if (hits(box)) return;
    placed.push(box, [c.X-3, c.Y-3, c.X+3, c.Y+3]); show.push(c);
  };

  const curated = [];
  if (state.showCaps && state.capitals) curated.push(...state.capitals.map(c => ({ ...c, t: 'cap' })));
  if (state.showMajors && state.majors) curated.push(...state.majors.map(c => ({ ...c, t: 'maj' })));
  for (const c of curated.filter(onScreen).sort((a, b) => b.p - a.p)){
    if (show.length >= maxPlaces) break;
    placeCity(c);
  }

  if (state.showStates){
    const half = narrow ? 9 : 12;
    for (const c of state.stateLabels.map(c => ({ ...c })).filter(onScreen).sort((a, b) => b.a - a.a)){
      if (c.X < 0 || c.X > W || c.Y < 0 || c.Y > H) continue;
      const box = [c.X-half, c.Y-7, c.X+half, c.Y+7];
      if (hits(box)) continue;
      placed.push(box); stShow.push(c);
    }
  }

  if (state.showMajors && t.k >= 2){
    for (const c of state.towns){
      if (show.length >= maxPlaces) break;   // towns are pre-sorted by population
      const d = { ...c, t: 'town' };
      if (onScreen(d)) placeCity(d);
    }
  }

  gCaps.selectAll('text.st-label').data(stShow, d => d.n).join('text')
      .attr('class', narrow ? 'st-label st-narrow' : 'st-label')
      .attr('x', d => d.X).attr('y', d => d.Y + (narrow ? 4 : 5)).attr('text-anchor', 'middle').text(d => d.n);
  // Dots only for places that got a label, so unlabeled towns don't clutter.
  gCaps.selectAll('circle').data(show, d => d.t + d.n + d.s).join('circle')
      .attr('class', d => d.t === 'cap' ? 'cap-dot' : (d.t === 'town' ? 'town-dot' : 'maj-dot'))
      .attr('cx', d => d.X).attr('cy', d => d.Y).attr('r', d => d.t === 'cap' ? 2.6 : (d.t === 'town' ? 1.8 : 2.4));
  gCaps.selectAll('text.cap-label').data(show, d => d.t + d.n + d.s).join('text')
      .attr('class', d => d.t === 'cap' ? 'cap-label' : (d.t === 'town' ? 'cap-label town-label' : 'cap-label maj-label'))
      .attr('x', d => d.left ? d.X-5 : d.X+5).attr('text-anchor', d => d.left ? 'end' : 'start')
      .attr('y', d => d.Y+3).text(d => d.n);
}

const zoom = d3.zoom().scaleExtent([1, 60]).on('zoom', async e => {
  gZoom.attr('transform', e.transform);
  gContour.selectAll('path').attr('stroke-width', 0.3/e.transform.k);
  gStates.selectAll('path').attr('stroke-width', 0.6/e.transform.k);
  positionPlaces();
  const want = pickLOD(e.transform.k);
  if (want !== state.lod){
    state.lod = want;
    await ensureCells(want);
    render();
  }
});
svg.call(zoom)
   .on('mousemove', onMove).on('click', onMove).on('mouseleave', () => tip.style('opacity', 0))
   .on('mousedown', () => svg.classed('grabbing', true)).on('mouseup', () => svg.classed('grabbing', false));

// Keep the tooltip inside the map (matters on narrow screens).
function placeTip(px, py){
  const W = svg.node().clientWidth, H = svg.node().clientHeight, tn = tip.node();
  const tw = tn.offsetWidth, th = tn.offsetHeight;
  const left = px + 14 + tw > W ? Math.max(4, px - 14 - tw) : px + 14;
  const top = py + 10 + th > H ? Math.max(4, py - 10 - th) : py + 10;
  tip.style('left', left + 'px').style('top', top + 'px');
}

function onMove(e){
  const t = d3.zoomTransform(svg.node());
  const [px, py] = d3.pointer(e, svg.node());
  const X = MINX + ((px - t.x)/t.k - OFFX)/S, Y = MAXY - ((py - t.y)/t.k - OFFY)/S;
  let best = null, bd = 60000*60000;
  for (const c of state.counties){ const dx = c.x-X, dy = c.y-Y, d = dx*dx+dy*dy; if (d < bd){ bd = d; best = c; } }
  if (!best){ tip.style('opacity', 0); return; }
  const mc = best.m[state.cmp];
  let val;
  if (state.mode === 'margin'){ if (mc == null){ tip.style('opacity', 0); return; } val = mc; }
  else { const mb = best.m[state.base];
         if (mb == null || mc == null){
           // Say why there's no swing here instead of silently hiding it.
           const miss = [mb == null ? state.base : null, mc == null ? state.cmp : null].filter(Boolean)
               .map(k => state.meta.years[k].label).join(' or ');
           tip.style('opacity', 1).html(`<b>${best.n}</b>, ${best.s}<br><span style="color:#6b6b6b">No contested race in ${miss} — not used for swing</span>`);
           placeTip(px, py); return;
         }
         val = state.mode === 'dev' ? (mc - mb - state.natl) : (mc - mb); }
  tip.style('opacity', 1)
     .html(`<b>${best.n}</b>, ${best.s}<br><span class="v" style="color:${val>=0?'#2166ac':'#b2182b'}">`
           + `${val>=0?'+':''}${val.toFixed(1)} pts ${val>=0?'D':'R'}</span>`);
  placeTip(px, py);
}

let lastW = 0, lastH = 0;
function resize(){
  const wrap = document.getElementById('wrap');
  const W = wrap.clientWidth, H = wrap.clientHeight;
  if (W === lastW && H === lastH) return;
  lastW = W; lastH = H;
  S = Math.min(W/(MAXX-MINX), H/(MAXY-MINY)) * 0.98;
  OFFX = (W - (MAXX-MINX)*S)/2; OFFY = (H - (MAXY-MINY)*S)/2;
  MPATH = metrePath();
  svg.select('#landclip path').attr('d', MPATH(state.land));
  // Keep the viewer's zoom across re-fits (layout shifts, rotation); the first
  // fit starts at the identity transform anyway.
  svg.call(zoom.transform, d3.zoomTransform(svg.node()));
  render();
}

load().catch(err => { console.error(err); document.getElementById('footer').textContent = 'Failed to load data: ' + err; });
