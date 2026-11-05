/* Political Weather — interactive 2026 House swing contour map.
   Per-YEAR Gaussian-smoothed margin surfaces (projected EPSG:5070 metres) are
   differenced in-browser: swing = margin(comparison) - margin(base), for any two
   years the viewer picks. d3-contour builds the bands; d3.zoom pans/zooms; two
   levels of detail (75 km / 40 km) are revealed as you zoom. */
'use strict';

const DATA = 'data/';
const state = { meta:null, grids:{}, states:null, land:null, counties:null, capitals:null, majors:null,
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

function ensureGrid(key, lodName){
  state.grids[key] = state.grids[key] || {};
  if (state.grids[key][lodName]) return Promise.resolve(state.grids[key][lodName]);
  const id = `${key}_${lodName}`;
  if (!state.loading[id]) state.loading[id] = d3.json(`${DATA}margin_${id}.json`)
      .then(d => { state.grids[key][lodName] = d.z; return d.z; });
  return state.loading[id];
}

async function load(){
  const meta = await d3.json(DATA + 'meta.json');
  state.meta = meta;
  [MINX, MINY, MAXX, MAXY] = meta.bounds;
  const [states, land, counties, capitals, majors, landmask] = await Promise.all([
    d3.json(DATA + 'states.json'), d3.json(DATA + 'land.json'), d3.json(DATA + 'counties.json'),
    d3.json(DATA + 'capitals.json'), d3.json(DATA + 'majors.json'), d3.json(DATA + 'landmask_coarse.json')]);
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
    d3.select('#baseLabel').text(m ? 'Base year (n/a)' : 'Base year');
    render();
  });
  d3.select('#reset').on('click', () => svg.transition().duration(400).call(zoom.transform, d3.zoomIdentity));
  d3.select('#capToggle').on('change', function(){ state.showCaps = this.checked; positionPlaces(); });
  d3.select('#majToggle').on('change', function(){ state.showMajors = this.checked; positionPlaces(); });

  svg.append('clipPath').attr('id', 'landclip').append('path');
  gContour.attr('clip-path', 'url(#landclip)');

  d3.select('#footer').html(
    `Source: <a href="https://github.com/mike10010100/elections-2026" target="_blank" rel="noopener">mike10010100/elections-2026</a>
     (compiles NYT returns) · <b>PROVISIONAL, pre-certification</b> · fetched ${meta.fetched_at.slice(0,16)} ·
     CONUS Albers Equal Area · difference of Gaussian-smoothed per-year margins, weighted by two-party votes ·
     uncontested seats excluded. County-level House swing is noisy: read regional tendency, not local values.`);

  computePairStats();
  await Promise.all([ensureGrid(state.base, state.lod.name), ensureGrid(state.cmp, state.lod.name)]);
  await computeVmax();
  resize();
  window.addEventListener('resize', resize);
}

async function changePair(which, value){
  state[which] = value;
  computePairStats();
  await Promise.all([ensureGrid(state.base, state.lod.name), ensureGrid(state.cmp, state.lod.name)]);
  await computeVmax();
  render();
}

function computePairStats(){
  state.natl = +(state.meta.years[state.cmp].national - state.meta.years[state.base].national).toFixed(2);
}

// Colour-scale domains from the coarse smoothed surface, over LAND cells only
// (offshore extrapolation would otherwise inflate the scale). Matches the static
// maps' saturation and stays stable as you zoom between LODs.
async function computeVmax(){
  const lod0 = state.meta.lods[0].name;
  const [gb, gc] = await Promise.all([ensureGrid(state.base, lod0), ensureGrid(state.cmp, lod0)]);
  const mask = state.landmask.mask;
  const abs = [], dev = [], mar = [];
  for (let i = 0; i < gc.length; i++){
    if (mask[i] !== '1') continue;
    const s = gc[i] - gb[i];
    abs.push(Math.abs(s)); dev.push(Math.abs(s - state.natl)); mar.push(Math.abs(gc[i]));
  }
  const pct = (a, q) => { a.sort((x, y) => x - y); return a.length ? a[Math.floor(q * (a.length - 1))] : 10; };
  state.vmaxAbs = Math.max(2, Math.ceil(pct(abs, 0.98)));
  state.vmaxDev = Math.max(2, Math.ceil(pct(dev, 0.98)));
  state.vmaxMargin = Math.max(2, Math.ceil(pct(mar, 0.98)));
}

function field(){
  const gc = state.grids[state.cmp][state.lod.name];
  const cl = state.meta.years[state.cmp].label;
  if (state.mode === 'margin')
    return { F: gc, vmax: state.vmaxMargin, title: `Margin (pts) · ${cl}` };
  const gb = state.grids[state.base][state.lod.name];
  const bl = state.meta.years[state.base].label;
  const swing = gc.map((v, i) => v - gb[i]);
  if (state.mode === 'abs')
    return { F: swing, vmax: state.vmaxAbs, title: `Swing (pts) · ${bl} → ${cl}` };
  return { F: swing.map(v => v - state.natl), vmax: state.vmaxDev,
           title: `Deviation from national ${state.natl>0?'+':''}${state.natl.toFixed(1)} pts · ${bl} → ${cl}` };
}

function render(){
  if (!MPATH || !state.grids[state.cmp] || !state.grids[state.cmp][state.lod.name]) return;
  if (state.mode !== 'margin' && (!state.grids[state.base] || !state.grids[state.base][state.lod.name])) return;
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
      .call(d3.axisBottom(sc).tickValues(d3.range(-vmax, vmax+1, vmax > 15 ? 10 : 5)).tickSize(4).tickFormat(d => (d>0?'+':'')+d))
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
  const src = [];
  if (state.showCaps && state.capitals) src.push(...state.capitals.map(c => ({ ...c, t: 'cap' })));
  if (state.showMajors && state.majors) src.push(...state.majors.map(c => ({ ...c, t: 'maj' })));
  const maxPlaces = Math.round(20 * Math.pow(t.k, 0.6));
  const pts = src.map(c => ({ ...c, X: t.applyX(sx(c.x)), Y: t.applyY(sy(c.y)) }))
      .filter(c => c.X > -20 && c.X < W+20 && c.Y > -10 && c.Y < H+10)
      .sort((a, b) => b.p - a.p).slice(0, maxPlaces);
  gCaps.selectAll('circle').data(pts, d => d.t + d.n).join('circle')
      .attr('class', d => d.t === 'cap' ? 'cap-dot' : 'maj-dot')
      .attr('cx', d => d.X).attr('cy', d => d.Y).attr('r', d => d.t === 'cap' ? 2.6 : 2.4);
  const placed = [], show = [];
  for (const c of pts){
    const w = c.n.length*6 + 8, box = [c.X+5, c.Y-6, c.X+5+w, c.Y+6];
    if (placed.some(p => !(box[2]<p[0] || box[0]>p[2] || box[3]<p[1] || box[1]>p[3]))) continue;
    placed.push(box); show.push(c);
  }
  gCaps.selectAll('text').data(show, d => d.t + d.n).join('text')
      .attr('class', d => d.t === 'cap' ? 'cap-label' : 'cap-label maj-label')
      .attr('x', d => d.X+5).attr('y', d => d.Y+3).text(d => d.n);
}

const zoom = d3.zoom().scaleExtent([1, 60]).on('zoom', async e => {
  gZoom.attr('transform', e.transform);
  gContour.selectAll('path').attr('stroke-width', 0.3/e.transform.k);
  gStates.selectAll('path').attr('stroke-width', 0.6/e.transform.k);
  positionPlaces();
  const want = pickLOD(e.transform.k);
  if (want !== state.lod){
    state.lod = want;
    await Promise.all([ensureGrid(state.base, want.name), ensureGrid(state.cmp, want.name)]);
    render();
  }
});
svg.call(zoom)
   .on('mousemove', onMove).on('mouseleave', () => tip.style('opacity', 0))
   .on('mousedown', () => svg.classed('grabbing', true)).on('mouseup', () => svg.classed('grabbing', false));

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
  else { const mb = best.m[state.base]; if (mb == null || mc == null){ tip.style('opacity', 0); return; }
         val = state.mode === 'dev' ? (mc - mb - state.natl) : (mc - mb); }
  tip.style('opacity', 1).style('left', (px+14)+'px').style('top', (py+10)+'px')
     .html(`<b>${best.n}</b>, ${best.s}<br><span class="v" style="color:${val>=0?'#2166ac':'#b2182b'}">`
           + `${val>=0?'+':''}${val.toFixed(1)} pts ${val>=0?'D':'R'}</span>`);
}

function resize(){
  const wrap = document.getElementById('wrap');
  const W = wrap.clientWidth, H = wrap.clientHeight;
  S = Math.min(W/(MAXX-MINX), H/(MAXY-MINY)) * 0.98;
  OFFX = (W - (MAXX-MINX)*S)/2; OFFY = (H - (MAXY-MINY)*S)/2;
  MPATH = metrePath();
  svg.select('#landclip path').attr('d', MPATH(state.land));
  svg.call(zoom.transform, d3.zoomIdentity);
  render();
}

load().catch(err => { console.error(err); document.getElementById('footer').textContent = 'Failed to load data: ' + err; });
