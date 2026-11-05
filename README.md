# Electoral Swing Contour Map — 2026 U.S. Midterms

A meteorological-style **contour (isoline) map of electoral swing**, built as an
alternative to The Economist's district-level "swing arrow" map. Instead of
thousands of overlapping arrows, a continuous scalar field of swing is
interpolated from county observations and drawn with filled contours and labelled
isolines, so regional structure reads at a glance — like isobars on a weather
chart.

> **Status: exploratory prototype on PROVISIONAL data.** The 2026 returns are
> unofficial, compiled two days after the election, and still changing. See
> [Data & provenance](#data--provenance) and [Limitations](#limitations).

**Interactive map:** `https://patrickmschneider.github.io/political-weather/`. Pick any
**base** and **comparison** year (House 2014–2026, President 2008–2024), switch
the view between **swing**, **deviation from national**, and a single-year
**margin** (raw Dem–Rep lean), zoom/pan (finer detail revealed on zoom), hover
any county, and show state capitals / major cities. Rebuilt and redeployed on a
schedule as results update.

## The maps

| File (`output/`) | What it shows |
|---|---|
| `swing_H24_H26_hero.png` | **Absolute swing**, 2024→2026 U.S. House, Dem two-party margin change (Gaussian) |
| `swing_H24_H26_deviation_hero.png` | **Deviation from national swing** — which counties moved more/less than the nationwide shift |
| `swing_H24_H26_methods.png` | Same data under **three interpolation methods** side by side |
| `validation_swing_P20_P24_hero.png` | **Fully-real validation** — 2020→2024 presidential swing through the identical pipeline |

## Quick start

```bash
pip install -r requirements.txt
bash scripts/fetch_data.sh             # download raw returns + Census geometry
cd src
python3 run_pipeline.py                # verify → prepare → cross-validate → render
python3 export_web.py                  # build web/data for the interactive map
```

Runs in a few seconds. Static figures land in `output/`; the interactive app's
data in `web/data/`; intermediate tables and the data-quality log in
`data/processed/`.

To preview the interactive app locally:

```bash
cd web && python3 -m http.server 8777   # then open http://localhost:8777
```

## Interactive web app (`web/`)

A dependency-light static site (D3 + `d3-contour`, no build step). One
Gaussian-smoothed **margin surface per year** is exported (projected EPSG:5070
metres) and the browser differences any two the viewer picks — swing =
margin(comparison) − margin(base) — so the **base/comparison year** and
**absolute ↔ deviation** controls are instant and no interpolation runs
client-side. The colour scale is set from the smoothed surface over land only;
per-county margins drive the tooltips. Pan/zoom and hover are built in.

(The app uses "difference of smoothed margins" to allow arbitrary year pairs; the
static maps use the equivalent "smoothed difference" of a single pair. The two
agree closely.)

**Level of detail by zoom:** each baseline ships at two kernel bandwidths — a
coarse 75 km surface shown when zoomed out and a finer 40 km surface that loads
on demand and is revealed as you zoom in (the status line shows which is active).
Static maps also default to the 75 km kernel on a 15 km grid.

**City labels:** state capitals (solid dots) and major cities (hollow dots) can
be toggled on/off; labels are placed greedily by population so crowded regions
keep the larger cities and more appear as you zoom. Alaska is shown as "result
pending" (see limitations); Hawaii appears on the static maps.

### Deploy / auto-update

`.github/workflows/pages.yml` deploys `web/` to GitHub Pages and, on a 6-hourly
cron (and manual dispatch), re-runs `scripts/fetch_data.sh` + `prepare_data.py` +
`export_web.py` so the live site tracks the source feed as returns update. After
first push, enable **Settings → Pages → Source: GitHub Actions** (and allow
Actions) once.

## Refreshing with newer / official results

The pipeline reads a **single** 2026 source file:
`data/raw/elections2026/county_shifts.json`. To update as official results
arrive, replace that file with a newer copy **in the same schema** and re-run
`run_pipeline.py`. Nothing else changes. The national-swing figure, deviations,
cross-validation and all maps regenerate from it, and every figure is stamped
with the source's `fetched_at` timestamp.

## Data & provenance

| Layer | Source | Notes |
|---|---|---|
| 2026 U.S. House (county) | [`mike10010100/elections-2026`](https://github.com/mike10010100/elections-2026) `site_data/county_shifts.json` (compiles NYT returns) | **PROVISIONAL / unofficial**, pre-certification |
| 2022 & 2024 U.S. House (county) | same repo (full 2004–2026 cycle history) | same-office baselines |
| 2020 & 2024 President (county) | [`tonmcg/US_County_Level_Election_Results_08-24`](https://github.com/tonmcg/US_County_Level_Election_Results_08-24) | cross-election baseline + validation |
| County & state geometry | US Census Cartographic Boundary **2021**, 1:20m | 2021 vintage keeps Connecticut's *traditional counties*, whose FIPS match the returns |

An alternative 2026 feed, [`pushbuild/us-2026-election-results`](https://github.com/pushbuild/us-2026-election-results),
can be wired in as an independent cross-check (not yet integrated).

## Method

**Swing** = Democratic **two-party** margin in 2026 − Democratic two-party margin
in the baseline, in percentage points. Two-party margin = `(D − R)/(D + R)·100`;
positive = movement toward Democrats. Four swings are computed:

- `swing_H24_H26` — 2024→2026 House (same office, consecutive) — **the headline**
- `swing_H22_H26` — 2022→2026 House (midterm-to-midterm; cleanest turnout match)
- `swing_P24_H26` — 2024 President→2026 House (**cross-election**; fullest baseline coverage)
- `swing_P20_P24` — 2020→2024 President (**fully real**, used to validate the pipeline)

Each swing also has a **deviation-from-national** companion (`*_dev`) = county
swing − the vote-weighted national swing, i.e. the uniform-swing residual.

**Surface construction** (`interpolate.py`), all in **EPSG:5070 CONUS Albers
Equal Area** (metres, honest distances/areas), all population-aware:

1. **Gaussian kernel smoothing** (Nadaraya–Watson), weighted by two-party votes.
2. **Inverse-distance weighting** (k-nearest, vote-weighted).
3. **Thin-plate-spline RBF**, with per-station regularisation that *downweights
   low-population counties* so sparse rural counties don't dominate.

Counties are represented by **interior representative points** (not naïve
centroids) and weighted by **two-party votes**, so the field is pulled toward
where voters actually are rather than treating every county as equal. The grid
(25 km) is **masked to the CONUS land polygon** — no isolines are drawn across
oceans.

**Method choice.** 10-fold spatial cross-validation (`cross_validate.py`) scores
all three. On the real presidential swing, RMSE ≈ 2.7–2.9 pts; IDW is marginally
most accurate point-by-point, but produces bullseye artifacts. **Gaussian
smoothing** is used for the headline maps: it sacrifices ~0.2 pt of pointwise
RMSE for a far more legible regional surface — the stated communication goal.
Accuracy and communication quality are not the same thing, and the comparison
figure shows the trade-off honestly.

## Data integrity (what is *not* faked)

- No election results are fabricated. The one earlier synthetic-demo layer was
  **removed** once real 2026 returns became available.
- **Nothing missing is treated as zero.** Counties missing a baseline or 2026
  value are dropped from that swing and counted in `data/processed/data_quality_log.json`.
- **Uncontested / same-party (top-two) races are excluded**, not mapped as a real
  ±100 margin. 2024 House had **294** such county-cycles (vs 13 in 2026) — a major
  reason the same-office baseline sheds counties.
- 2026 counties with **< 50% of expected vote counted** are excluded; completeness
  (`eevp`) is carried through and most counties are ≥ 99% counted.
- Verification (`verify_data.py`) confirms the source's margins reconstruct from
  the underlying `D/R/votes` and that `eevp` matches votes/expected.

## Limitations

- **Provisional data / unusually large swing.** These returns imply a national
  House swing of **~ +14.6 pts toward Democrats** (≈ D+12 popular vote) — a
  historic margin. It is consistent across every baseline here, so it is genuinely
  *in this dataset*, but it may reflect a real wave, incomplete/biased county
  coverage, or source-pipeline quirks. Internal consistency is verified; the
  underlying NYT numbers are **not** independently audited against official
  canvasses. Treat magnitudes as provisional; the **deviation-from-national** map
  is the more robust product (it removes the uniform national level).
- **House swing is noisy.** Cross-validated RMSE for county House swing is ~8 pts
  (vs ~2.8 for president) — candidate effects, counties split across districts,
  and turnout composition. The surface shows *regional tendency*, not reliable
  local values.
- **Cross-election framing.** `swing_P24_H26` compares a presidential baseline to
  a House result: different office, different turnout. Labelled as such.
- **County aggregation of House votes** sums across districts within split
  counties; it is an approximation of a fundamentally district-level contest.
- **Interpolation across water.** Output is clipped to land, but kernel/IDW
  *influence* can still cross narrow water (e.g. the Gulf, Great Lakes). A true
  geodesic barrier is out of scope; bandwidth is kept moderate to limit bleed.
- **CONUS only.** Alaska, Hawaii and territories are excluded from the continuous
  surface (they would force ocean-spanning interpolation).

## Repo layout

```
src/
  config.py         paths, CRS, grid/kernel params, data-quality thresholds, source file
  verify_data.py    checks provisional returns against underlying D/R/votes
  prepare_data.py   margins, swings, deviations, geometry join, missing/uncontested handling
  interpolate.py    Gaussian / IDW / TPS surfaces on a land-masked Albers grid
  insets.py         Hawaii swing surface + Alaska "pending" geometry
  cross_validate.py 10-fold spatial CV comparing the three methods
  render.py         meteorological-style contour figures (with AK/HI insets)
  export_web.py     exports web/data for the interactive app
  run_pipeline.py   runs verify → prepare → cross-validate → render
web/                interactive D3 site (index.html, app.js, data/)
scripts/fetch_data.sh   downloads all raw inputs
.github/workflows/      Pages deploy + scheduled data refresh
data/raw/           downloaded returns + Census geometry (untrusted; git-ignored)
data/processed/     stations.csv, land/state gpkg, data_quality_log.json, CV tables (git-ignored)
output/             static figures
```
