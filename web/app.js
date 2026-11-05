/* Swingcast — interactive 2026 House swing contour map.
   All geometry is in GRID-INDEX space of the exported CONUS Albers grid. One
   path generator maps grid units -> screen (with a centring offset baked in);
   d3-contour builds the bands from the grid; d3.zoom pans/zooms one group. */
'use strict';

const DATA = 'data/';
const state = { meta:null, grids:{}, states:null, land:null, counties:null,
                baseline:null, mode:'abs', quad:null };

const svg = d3.select('#map');
const gZoom = svg.append('g');
const gContour = gZoom.append('g');
const gStates = gZoom.append('g');
const tip = d3.select('#tip');

let NX = 0, NY = 0, S = 1, OFFX = 0, OFFY = 0, PATH = null;

function colorScale(vmax){ return d3.scaleDiverging(t => d3.interpolateRdBu(t)).domain([-vmax, 0, vmax]); }

function pathGen(){
  const t = d3.geoTransform({ point(x, y){ this.stream.point(OFFX + x*S, OFFY + (NY - y)*S); } });
  return d3.geoPath(t);
}

async function load(){
  const meta = await d3.json(DATA + 'meta.json');
  state.meta = meta; NX = meta.nx; NY = meta.ny;
  const [states, land, counties] = await Promise.all([
    d3.json(DATA + 'states.json'), d3.json(DATA + 'land.json'), d3.json(DATA + 'counties.json')]);
  state.states = states; state.land = land; state.counties = counties;
  const cols = Object.keys(meta.baselines);
  await Promise.all(cols.map(async c => { state.grids[c] = (await d3.json(DATA + `grid_${c}.json`)).z; }));
  state.baseline = cols[0];

  const sel = d3.select('#baseline');
  sel.selectAll('option').data(cols).join('option').attr('value', d => d).text(d => meta.baselines[d].label);
  sel.on('change', e => { state.baseline = e.target.value; render(); });

  d3.selectAll('#mode button').on('click', function(){
    d3.selectAll('#mode button').classed('active', false);
    d3.select(this).classed('active', true);
    state.mode = this.dataset.mode; render();
  });

  svg.append('clipPath').attr('id', 'landclip').append('path');
  gContour.attr('clip-path', 'url(#landclip)');
  state.quad = d3.quadtree().x(d => d.x).y(d => d.y).addAll(counties);

  d3.select('#reset').on('click', () => svg.transition().duration(400).call(zoom.transform, d3.zoomIdentity));
  d3.select('#footer').html(
    `Source: <a href="https://github.com/mike10010100/elections-2026" target="_blank" rel="noopener">mike10010100/elections-2026</a>
     (compiles NYT returns) · <b>PROVISIONAL, pre-certification</b> · fetched ${meta.fetched_at.slice(0,16)} ·
     CONUS Albers Equal Area · Gaussian-smoothed, counties weighted by two-party votes · uncontested seats excluded.
     County-level House swing is noisy (cross-validated RMSE ≈ 8 pts): read regional tendency, not local values.`);
  d3.select('#note').html('Alaska: at-large RCV result pending. Hawaiʻi: see the static maps in the repo.');

  resize();
  window.addEventListener('resize', resize);
}

function fieldAndDomain(){
  const b = state.meta.baselines[state.baseline];
  const z = state.grids[state.baseline];
  if (state.mode === 'abs')
    return { F: z, vmax: b.abs_vmax, title: `Swing (pts) · ${b.label}`, tipVal: v => v };
  return { F: z.map(v => v - b.national), vmax: b.dev_vmax,
           title: `Deviation from national ${b.national>0?'+':''}${b.national.toFixed(1)} pts`,
           tipVal: v => v - b.national };
}

function render(){
  if (!state.baseline || !PATH) return;
  const { F, vmax, title } = fieldAndDomain();
  const color = colorScale(vmax);
  const step = vmax > 20 ? 3 : 2;
  const thr = d3.range(-Math.ceil(vmax/step)*step, Math.ceil(vmax/step)*step + step, step);
  const contours = d3.contours().size([NX, NY]).thresholds(thr)(F);

  gContour.selectAll('path').data(contours).join('path')
      .attr('d', PATH).attr('fill', d => color(d.value + step/2))
      .attr('stroke', '#00000022').attr('stroke-width', 0.3).attr('vector-effect', 'non-scaling-stroke');
  gStates.selectAll('path').data(state.states.features).join('path').attr('class', 'state').attr('d', PATH);
  drawLegend(vmax, color, title);
}

function drawLegend(vmax, color, title){
  d3.select('#legend-title').text(title);
  const w = 320, h = 14, n = 60, lsvg = d3.select('#legend-svg');
  lsvg.selectAll('*').remove();
  const x = d3.scaleLinear().domain([0, n-1]).range([-vmax, vmax]);
  lsvg.append('g').selectAll('rect').data(d3.range(n)).join('rect')
      .attr('x', i => i*(w/n)).attr('width', w/n+1).attr('height', h).attr('fill', i => color(x(i)));
  const sc = d3.scaleLinear().domain([-vmax, vmax]).range([0, w]);
  const ticks = d3.range(-vmax, vmax+1, vmax > 15 ? 10 : 5);
  lsvg.append('g').attr('transform', `translate(0,${h})`)
      .call(d3.axisBottom(sc).tickValues(ticks).tickSize(4).tickFormat(d => (d>0?'+':'')+d))
      .call(g => g.select('.domain').remove()).selectAll('text').attr('font-size', 9);
}

const zoom = d3.zoom().scaleExtent([1, 40]).on('zoom', e => {
  gZoom.attr('transform', e.transform);
  gContour.selectAll('path').attr('stroke-width', 0.3 / e.transform.k);
  gStates.selectAll('path').attr('stroke-width', 0.6 / e.transform.k);
});
svg.call(zoom)
   .on('mousemove', onMove).on('mouseleave', () => tip.style('opacity', 0))
   .on('mousedown', () => svg.classed('grabbing', true))
   .on('mouseup', () => svg.classed('grabbing', false));

function onMove(e){
  const t = d3.zoomTransform(svg.node());
  const [px, py] = d3.pointer(e, svg.node());
  const sx = (px - t.x)/t.k, sy = (py - t.y)/t.k;        // undo zoom
  const gi = (sx - OFFX)/S, gj = NY - (sy - OFFY)/S;      // undo path -> grid coords
  const c = state.quad.find(gi, gj, 30);
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
  S = Math.min(W/NX, H/NY) * 0.98;
  OFFX = (W - NX*S)/2; OFFY = (H - NY*S)/2;
  PATH = pathGen();
  svg.select('#landclip path').attr('d', PATH(state.land));
  svg.call(zoom.transform, d3.zoomIdentity);
  render();
}

load().catch(err => { console.error(err); document.getElementById('footer').textContent = 'Failed to load data: ' + err; });
