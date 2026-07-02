# PEAD (small-cap) — development diagnostic (market-adjusted, cost-swept)

> **Exploratory, in-sample, DEV ≤2024; 2025+ hold-out SEALED (D22).** SUE = seasonal-random-walk (no estimates); entry = SF1 datekey (PIT-clean; misses the initial post-8-K reaction, so a HARD test); 63-day drift; market-adjusted (−SPY); costs charged ROUND-TRIP; **≥50 bps bar.** Arena #4 — multiple-comparisons caution.

- **Event count:** 83,602 small-cap SUE firm-quarters in dev; **83,575** with a realized 63d return. PEAD holds ~63d per event → ~1 round-trip per position (near-full turnover); round-trip cost = 2× one-way is charged.

## IC — does SUE rank predict forward market-adjusted return?

- Mean IC **0.0291**, IC-IR (monthly) 0.301, t 4.03, **% positive months +67.78%** (n=180 cohorts). (D17: weight %-positive, don't be fooled by IC-IR.)

- IC by year positive in **12/15** years. By year: 2010:0.011, 2011:0.064, 2012:0.036, 2013:0.016, 2014:0.030, 2015:0.097, 2016:0.018, 2017:0.044, 2018:-0.011, 2019:-0.002, 2020:-0.006, 2021:0.062, 2022:0.035, 2023:0.018, 2024:0.063.

## Decile spread — market-adjusted 63d return by SUE decile (gross)

  D0:-0.81% D1:-0.90% D2:-0.73% D3:-0.53% D4:+0.50% D5:-0.52% D6:+0.09% D7:+0.00% D8:+0.40% D9:+0.29%

- Top−bottom (gross, market-adj): **+1.09%**; top decile +0.29%, bottom -0.81%.

## Cost sweep (round-trip) — does the edge survive ≥50 bps?

| One-way cost | Top-decile net (market-adj 63d) | Long-short net |
|---|---|---|
| 25.0 bps | +0.17% | +0.59% |
| 30.0 bps | +0.07% | +0.49% |
| 50.0 bps | -0.33% | +0.09% |
| 100.0 bps | -1.33% | -0.91% |

*The **50 bps** row is the bar. Round-trip cost at 50 bps one-way = 100 bps ≈ 1.0% subtracted per event.*

## By year — top-decile net @50 bps (regime check)

| Year | top-decile gross (adj) | net @50bps | n |
|---|---|---|---|
| 2010 | +1.51% | +0.51% | 555 |
| 2011 | +2.19% | +1.19% | 557 |
| 2012 | -0.05% | -1.05% | 524 |
| 2013 | +1.66% | +0.66% | 549 |
| 2014 | -1.59% | -2.59% | 574 |
| 2015 | -0.03% | -1.03% | 573 |
| 2016 | +4.09% | +3.09% | 567 |
| 2017 | +0.01% | -0.99% | 590 |
| 2018 | -0.29% | -1.29% | 583 |
| 2019 | -3.95% | -4.95% | 559 |
| 2020 | +7.56% | +6.56% | 549 |
| 2021 | -1.59% | -2.59% | 583 |
| 2022 | +3.37% | +2.37% | 558 |
| 2023 | -3.15% | -4.15% | 562 |
| 2024 | +0.57% | -0.43% | 568 |

## Verdict

- **PEAD does NOT clear the ≥50 bps bar in dev.** SUE IC is 0.0291 (t 4.03, +67.78% months positive); after round-trip costs the top decile is **-0.33% net @50bps** (long-short +0.09%). Even where a gross drift exists, high earnings-season turnover + honest small-cap costs eat it — the same force that killed momentum (Phase 5). Also, datekey entry misses the early post-8-K reaction, so the residual drift is small by construction. **No case for spending the sealed hold-out.**

- **Caveats:** entry at 10-Q datekey is conservative (misses initial reaction); SUE is one frozen definition; arena #4 with IC/decile/by-year slices — heavy multiple-comparisons.


> **STOP for review. 2025+ hold-out untouched.**
