/* Political Weather — interactive 2026 House swing contour map.
   Geometry is in projected METRES (EPSG:5070). One linear metres->screen
   transform + d3.zoom; d3-contour builds the bands. Each baseline ships at two
   levels of detail (coarse 75 km / fine 40 km kernel); the finer surface loads
   and is revealed as the viewer zooms in. */
'use strict';

const DATA = 'data/';
const state = { meta:null, grids:{}, states:null, land:null, counties:null, capitals:null, majors:null,
                baseline:null, mode:'abs', lod:null, quad:null, loading:{}, showCaps:true, showMajors:true };

const svg = d3.select('#map');
const gZoom = svg.append('g');
const gContour = gZoom.append('g');
const gStates = gZoom.append('g');
const gCaps = svg.append('g').style('pointer-events', 'none');   // overlay, constant screen size
const tip = d3.select('#tip');

let MINX=0, MINY=0, MAXX=0, MAXY=0, S=1, OFFX=0, OFFY=0;

const sx = X => OFFX + (X - MINX) * S;
const sy = Y => OFFY + (MAXY - Y) * S;
function colorScale(vmax){ return d3.scaleDiverging(t => d3.interpolateRdBu(t)).domain([-vmax, 0, vmax]); }

// path for GeoJSON already in metres
function metrePath(){ return d3.geoPath(d3.geoTransform({ point(X,Y){ this.stream.point(sx(X), sy(Y)); } })); }
// path for a contour whose coords are grid indices of LOD `l`
function gridPath(l){
  return d3.geoPath(d3.geoTransform({ point(i,j){ this.stream.point(sx(l.x0 + i*l.dx), sy(l.y0 + j*l.dy)); } }));
}
let MPATH = null;

function pickLOD(k){ let L = state.meta.lods[0]; for (const l of state.meta.lods) if (k >= l.zmin) L = l; return L; }

async function ensureGrid(col, lodName){
  state.grids[col] = state.grids[col] || {};
  if (state.grids[col][lodName]) return state.grids[col][lodName];
  const key = `${col}_${lodName}`;
  if (!state.loading[key]) state.loading[key] = d3.json(`${DATA}grid_${key}.json`).then(d => { state.grids[col][lodName] = d.z; return d.z; });
  return state.loading[key];
}

async function load(){
  const meta = await d3.json(DATA + 'meta.json');
  state.meta = meta;
  [MINX, MINY, MAXX, MAXY] = meta.bounds;
  const [states, land, counties, capitals, majors] = await Promise.all([
    d3.json(DATA + 'states.json'), d3.json(DATA + 'land.json'), d3.json(DATA + 'counties.json'),
    d3.json(DATA + 'capitals.json'), d3.json(DATA + 'majors.json')]);
  state.states = states; state.land = land; state.counties = counties;
  state.capitals = capitals; state.majors = majors;
  const cols = Object.keys(meta.baselines);
  state.baseline = cols[0];
  state.lod = meta.lods[0];
  await Promise.all(cols.map(c => ensureGrid(c, state.lod.name)));   // coarse upfront

  const sel = d3.select('#baseline');
  sel.selectAll('option').data(cols).join('option').attr('value', d => d).text(d => meta.baselines[d].label);
  sel.on('change', async e => { state.baseline = e.target.value; await ensureGrid(state.baseline, state.lod.name); render(); });

  d3.selectAll('#mode button').on('click', function(){
    d3.selectAll('#mode button').classed('active', false);
    d3.select(this).classed('active', true); state.mode = this.dataset.mode; render();
  });

  svg.append('clipPath').attr('id', 'landclip').append('path');
  gContour.attr('clip-path', 'url(#landclip)');
  state.quad = d3.quadtree().x(d => d.x).y(d => d.y).addAll(counties);

  d3.select('#reset').on('click', () => svg.transition().duration(400).call(zoom.transform, d3.zoomIdentity));
  d3.select('#capToggle').on('change', function(){ state.showCaps = this.checked; positionPlaces(); });
  d3.select('#majToggle').on('change', function(){ state.showMajors = this.checked; positionPlaces(); });
  d3.select('#footer').html(
    `Source: <a href="https://github.com/mike10010100/elections-2026" target="_blank" rel="noopener">mike10010100/elections-2026</a>
     (compiles NYT returns) · <b>PROVISIONAL, pre-certification</b> · fetched ${meta.fetched_at.slice(0,16)} ·
     CONUS Albers Equal Area · Gaussian-smoothed, counties weighted by two-party votes · uncontested seats excluded.
     County-level House swing is noisy (cross-validated RMSE ≈ 8 pts): read regional tendency, not local values.`);

  resize();
  window.addEventListener('resize', resize);
}

function fieldAndDomain(){
  const b = state.meta.baselines[state.baseline];
  const z = state.grids[state.baseline][state.lod.name];
  if (state.mode === 'abs')
    return { F: z, vmax: b.abs_vmax, title: `Swing (pts) · ${b.label}`, tipVal: v => v };
  return { F: z.map(v => v - b.national), vmax: b.dev_vmax,
           title: `Deviation from national ${b.national>0?'+':''}${b.national.toFixed(1)} pts`, tipVal: v => v - b.national };
}

function render(){
  if (!state.baseline || !MPATH) return;
  const z = state.grids[state.baseline] && state.grids[state.baseline][state.lod.name];
  if (!z) return;
  const { F, vmax, title } = fieldAndDomain();
  const color = colorScale(vmax);
  const step = vmax > 20 ? 3 : 2;
  const thr = d3.range(-Math.ceil(vmax/step)*step, Math.ceil(vmax/step)*step + step, step);
  const contours = d3.contours().size([state.lod.nx, state.lod.ny]).thresholds(thr)(F);
  const gpath = gridPath(state.lod);
  const k = d3.zoomTransform(svg.node()).k;

  gContour.selectAll('path').data(contours).join('path')
      .attr('d', gpath).attr('fill', d => color(d.value + step/2))
      .attr('stroke', '#00000022').attr('stroke-width', 0.3/k).attr('vector-effect', 'non-scaling-stroke');
  gStates.selectAll('path').data(state.states.features).join('path').attr('class', 'state').attr('d', MPATH);
  drawLegend(vmax, color, title);
  d3.select('#status').text(`Smoothing: ${state.lod.bw_km} km${state.lod === state.meta.lods[0] ? ' · zoom in for finer detail' : ' (fine)'}`);
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
  // party direction (red = Republican, blue = Democratic)
  lsvg.append('text').attr('x', 0).attr('y', 47).attr('font-size', 10)
      .attr('font-weight', 600).attr('fill', '#b2182b').text('← more Republican');
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
  // Cap how many places show, by population; ~20 at the national view, growing
  // with zoom so smaller cities fill in as you zoom in.
  const maxPlaces = Math.round(20 * Math.pow(t.k, 0.6));
  const pts = src.map(c => ({ ...c, X: t.applyX(sx(c.x)), Y: t.applyY(sy(c.y)) }))
      .filter(c => c.X > -20 && c.X < W+20 && c.Y > -10 && c.Y < H+10)
      .sort((a, b) => b.p - a.p)
      .slice(0, maxPlaces);
  gCaps.selectAll('circle').data(pts, d => d.t + d.n).join('circle')
      .attr('class', d => d.t === 'cap' ? 'cap-dot' : 'maj-dot')
      .attr('cx', d => d.X).attr('cy', d => d.Y).attr('r', d => d.t === 'cap' ? 2.6 : 2.4);
  // greedy label placement by population across both sets
  const placed = [], show = [];
  for (const c of [...pts].sort((a, b) => b.p - a.p)){
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
    await ensureGrid(state.baseline, want.name);
    render();
  }
});
svg.call(zoom)
   .on('mousemove', onMove).on('mouseleave', () => tip.style('opacity', 0))
   .on('mousedown', () => svg.classed('grabbing', true)).on('mouseup', () => svg.classed('grabbing', false));

function onMove(e){
  const t = d3.zoomTransform(svg.node());
  const [px, py] = d3.pointer(e, svg.node());
  const ux = (px - t.x)/t.k, uy = (py - t.y)/t.k;        // undo zoom
  const X = MINX + (ux - OFFX)/S, Y = MAXY - (uy - OFFY)/S; // -> metres
  const c = state.quad.find(X, Y, 60000);
  const raw = c ? c.v[state.baseline] : null;
  if (raw == null){ tip.style('opacity', 0); return; }
  const val = fieldAndDomain().tipVal(raw);
  tip.style('opacity', 1).style('left', (px+14)+'px').style('top', (py+10)+'px')
     .html(`<b>${c.n}</b>, ${c.s}<br><span class="v" style="color:${val>=0?'#2166ac':'#b2182b'}">`
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
  positionPlaces();
}

load().catch(err => { console.error(err); document.getElementById('footer').textContent = 'Failed to load data: ' + err; });
