# Phase 4 — final model verdict (single hold-out evaluation)

> The 2022+ hold-out was touched **exactly once**, after freezing the model. Frozen pick (D16, honored): **lgbm × fwd_ret_excess_median**, HP {'num_leaves': 15, 'min_child_samples': 300} (modal across dev folds), fit on all development data (≤2021-12).

## Development-CV vs hold-out (the overfitting check)

| Metric | Dev-CV (selected) | Hold-out (2022+) |
|---|---|---|
| Mean OOS IC | 0.0330 | 0.0149 |
| IC t-stat | 2.51 | 0.59 |
| % positive periods | +50.0% (folds) | +50.0% (dates) |

*Hold-out window 2022-01-31→2024-12-31, 36 rebalances.*

## Hold-out detail

- **OOS IC = 0.0149** (t 0.59, +50.0% of dates positive).

- **Decile spread:** top−bottom = 0.0130, monotonicity ρ = 0.02.

- **Regime (by year):** 2022: IC 0.0490 (t 0.75), 2023: IC -0.0139 (t -0.60), 2024: IC 0.0096 (t 0.29).

- **Value-short corr (score vs earnings_yield_z): -0.338;** long leg 0.0092, short leg 0.0058, L−S Sharpe 0.25.

## Costed backtest on hold-out (long top-decile, net) vs baselines

*Common window 2022-01-31→2024-10-31, 34 rebalances, 6 bps.*

| Strategy | CAGR (net) | Sharpe | MaxDD |
|---|---|---|---|
| model_topdecile | +10.2% | 0.51 | -19.1% |
| SPY | +12.5% | 0.76 | -20.2% |
| equal_weight | +9.0% | 0.56 | -18.3% |

## Verdict (plain English)

- **No exploitable edge survives out-of-sample.** The dev-CV IC (0.0330, concentrated in 2019-2021) **collapsed to 0.0149 (t 0.59)** on 2022+ — a dev→hold-out gap of 0.0181, the classic signature of a regime-bound, overfit signal rather than durable selection. The model **does not beat SPY** (top-decile Sharpe 0.51 vs 0.76).

- **What this means for whether edge exists here:** with survivorship removed, costs charged, point-in-time fundamentals, 50 features, two model classes, and honest walk-forward + a sealed hold-out, **no combination produced a cross-sectional ranking signal that survives out-of-sample and beats buy-and-hold.** That is the expected, rigorous result for efficient US large-caps on free/affordable data — and a clean demonstration of where edge does *not* live. Value's negative tilt and the faded vol signal were correctly judged non-exploitable; the fundamental-momentum 'acceleration' thesis did not generalize. Reported as plainly as a positive result would have been.


*The hold-out has now been spent. Any further modeling would require a new, untouched test period; re-using 2022+ for selection would invalidate it.*
