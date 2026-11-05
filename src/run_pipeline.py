"""
One-command pipeline: data -> validation -> cross-validation -> figures.

To refresh with newer/official 2026 returns, replace the single source file
  data/raw/elections2026/county_shifts.json
(same schema) and re-run this script. Everything downstream regenerates.

    python3 run_pipeline.py
"""
from __future__ import annotations
import config as C  # caps BLAS threads before numpy/scipy load
import time

import verify_data
import prepare_data
import cross_validate
import render


def banner(t):
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72, flush=True)


def main():
    t0 = time.time()
    banner("STEP 1/4  Verify provisional 2026 returns against underlying data")
    verify_data.main()
    banner("STEP 2/4  Build projected stations, margins, swings, deviations")
    prepare_data.main()
    banner("STEP 3/4  Cross-validate interpolation methods")
    cross_validate.main()
    banner("STEP 4/4  Render contour maps")
    render.main()
    print(f"\nPipeline complete in {time.time()-t0:.1f}s. Figures in {C.OUTPUT}")


if __name__ == "__main__":
    main()
