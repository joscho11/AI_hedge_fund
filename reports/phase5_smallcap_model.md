# Phase 5 — small-cap final verdict (single 2022+ hold-out)

> 2022+ touched **exactly once**, after freezing. Frozen (D19): **lgbm × fwd_ret_excess_sector**, HP {'num_leaves': 15, 'min_child_samples': 300} (modal dev folds), fit on all dev (≤2021-12). Metrics in pre-registered roles: **IC = is it real OOS**; **costed long-only backtest = is it cheaply monetizable (≥50 bps bar)**. Best of 4 combos in arena #2 (multiple-comparisons).

## Development-CV vs hold-out — the overfitting check

| Metric | Dev-CV (selected) | Hold-out (2022+) |
|---|---|---|
| Mean OOS IC | 0.0150 | 0.0003 |
| IC t-stat | 3.28 | 0.03 |
| % positive periods | +83.3% (folds) | +44.4% (dates) |

*Hold-out 2022-01-31→2024-12-31, 36 rebalances.*

## Hold-out detail

- **OOS IC 0.0003** (t 0.03, +44.4% dates +).

- Decile top−bottom 0.0390, monotonicity ρ 0.95 — but this is a SECONDARY metric and, with the primary IC ≈ 0 (t 0.03) and the long-only backtest losing money below, it carries no weight (D9): averaged decile means can look ordered while per-date rank IC is noise.

- Regime: 2022: IC -0.0023 (t -0.12), 2023: IC 0.0113 (t 0.64), 2024: IC -0.0083 (t -0.93).

- Value corr -0.320, size-tilt corr -0.033 (both small ⇒ still genuine selection, not a factor proxy).

## Cost-sweep backtest on hold-out (long top-decile, net) vs baselines

| One-way cost | Model CAGR | Model Sharpe | IWM CAGR | Equal-weight CAGR |
|---|---|---|---|---|
| 25.0 bps | +1.7% | 0.21 | +8.0% | +3.0% |
| 30.0 bps | +1.3% | 0.19 | +8.0% | +2.9% |
| 50.0 bps | -0.5% | 0.13 | +8.0% | +2.4% |
| 100.0 bps | -4.9% | -0.01 | +7.8% | +1.0% |

## Verdict (plain English)

- **The signal did NOT survive out-of-sample.** Dev IC 0.0150 (t 3.28) → hold-out 0.0003 (t 0.03). Despite a consistent, non-artifact dev signal, it did not generalize to 2022+ — consistent with an arena-#2 selection effect (best of 4 combos) rather than durable edge.

- **But it is NOT cheaply monetizable long-only:** at 50 bps the model returns -0.5% (Sharpe 0.13) vs IWM +8.0% (Sharpe 0.44) — fails the ≥50 bps bar; small-cap turnover costs erode the long-only top decile. A **long-short** could in principle exploit the IC better, but small-cap short borrow/impact is unmodeled — **unproven pending borrow-cost modeling**, not claimed here.

- **What it means:** no exploitable edge survives here either; both arenas return the honest null. Across both arenas, with survivorship removed, costs charged honestly, and a sealed hold-out, the program's verdict on free/affordable-data cross-sectional equity selection stands as a rigorous, bias-controlled result.


*The small-cap 2022+ hold-out is now spent.*
