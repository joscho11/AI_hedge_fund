# Experiments Log (multiple-comparisons ledger)

Every feature set / model / hyperparameter variant we evaluate goes here — one row each — so we can
honestly count how many things we tried when judging significance. Append-only.

| # | Date | Phase | What was tried | Target | Validation | Mean IC | IC IR | Notes |
|---|------|-------|----------------|--------|------------|---------|-------|-------|
| — | —    | 0     | (no models yet — data layer only) | — | — | — | — | scaffolding |
| 1 | 2026-06-27 | 2 | 12-1 momentum (top-decile EW, monthly) | fwd_ret_raw | full-sample (110-name panel, 165 mo) | 0.021 | 0.096 | t=1.23, NOT significant; Sharpe 1.09 ≈ equal-weight 1.10; edge concentrated in D9, non-monotonic. Headline CAGR +23.6% is survivorship-flattered + noisy, not real risk-adjusted edge. |
| 1b| 2026-06-27 | 2 | 12-1 momentum | fwd_ret_excess_sector | full-sample | 0.012 | 0.080 | t=1.02; within-sector even weaker. (raw==excess_median IC by rank-invariance.) |
| 2 | 2026-06-27 | 2 | 12-1 momentum (top-decile EW), **FULL universe (500)** | fwd_ret_raw | full-sample (80,676 rows, 165 mo) | 0.004 | 0.022 | t=0.28, 50.3% months +, decile monotonicity **−0.103** (U-shape). Signal ≈ 0 with more breadth. Top-decile Sharpe rose to 1.17 (>EW 1.09) but NOT IC-supported → fragile/period-specific. Conclusion "momentum not robust" STRENGTHENED. |
| 2b| 2026-06-27 | 2 | 12-1 momentum, FULL universe | fwd_ret_excess_sector | full-sample | 0.007 | 0.050 | t=0.64; still insignificant. |
