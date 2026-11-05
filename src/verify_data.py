"""
Verification of the mike10010100/elections-2026 county returns BEFORE we trust
them for mapping. Checks the repo's own margins against the underlying d/r/votes,
quantifies 2026 completeness, and reports the national House swing implied by the
raw vote totals (so the contour surface can be sanity-checked against one number).

Run:  python3 verify_data.py
"""
from __future__ import annotations
import config as C
import json
import numpy as np

SRC = C.DATA_RAW / "elections2026" / "county_shifts.json"


def two_party_margin(d, r):
    tp = d + r
    return (d - r) / tp * 100 if tp > 0 else np.nan


def main():
    cs = json.load(open(SRC))
    co = cs["counties"]
    print(f"source: {SRC.name}  |  counties tracked: {cs['count']}")

    # --- Check 1: repo margin m == d - r (its stated convention) -----------
    disc = []
    for c in co.values():
        for cyc in ("h24", "h26"):
            h = c.get(cyc)
            if h and None not in (h.get("d"), h.get("r"), h.get("m")):
                disc.append(abs((h["d"] - h["r"]) - h["m"]))
    disc = np.array(disc)
    print(f"[1] margin m vs (d-r): n={len(disc)}  max|diff|={disc.max():.3f}  "
          f"mean|diff|={disc.mean():.4f}  -> m is (d - r) in total-vote points")

    # --- Check 2: vote completeness fields (eevp ~ v/ev*100) ---------------
    ee, rel = [], []
    for c in co.values():
        h = c.get("h26")
        if h and h.get("ev") and h.get("v") is not None and h.get("eevp"):
            ee.append(h["eevp"])
            rel.append(abs(h["eevp"] - 100 * h["v"] / h["ev"]))
    ee = np.array(ee); rel = np.array(rel)
    print(f"[2] h26 completeness: n={len(ee)}  median eevp={np.median(ee):.0f}%  "
          f"eevp<50:{int((ee<50).sum())}  <80:{int((ee<80).sum())}  "
          f"| eevp vs v/ev check mean|diff|={rel.mean():.2f}pp")

    # --- Check 3: uncontested / same-party (top-two) detection -------------
    for cyc in ("h24", "h26"):
        samep = sum(1 for c in co.values()
                    if (h := c.get(cyc)) and h.get("r") is not None
                    and h.get("d") is not None and min(h["d"], h["r"]) < 2.0)
        print(f"[3] {cyc}: counties with a major party <2% (uncontested / same-party): {samep}")

    # --- Check 4: national House two-party swing from RAW vote totals -------
    def national(cyc):
        D = R = 0.0
        for c in co.values():
            h = c.get(cyc)
            if h and h.get("v") and h.get("d") is not None and h.get("r") is not None:
                D += h["v"] * h["d"] / 100.0
                R += h["v"] * h["r"] / 100.0
        return D, R
    D24, R24 = national("h24"); D26, R26 = national("h26")
    m24 = (D24 - R24) / (D24 + R24) * 100
    m26 = (D26 - R26) / (D26 + R26) * 100
    print(f"[4] National House two-party margin (from summed county votes):")
    print(f"    2024 = {m24:+.2f}   (D {D24/1e6:.1f}M / R {R24/1e6:.1f}M)")
    print(f"    2026 = {m26:+.2f}   (D {D26/1e6:.1f}M / R {R26/1e6:.1f}M)")
    print(f"    National swing 2024->2026 = {m26 - m24:+.2f} pts (+ = toward Democrats)")
    print(f"    fetched_at: {cs.get('ap_abbr','')}  "
          f"(provisional, pre-certification)")


if __name__ == "__main__":
    main()
