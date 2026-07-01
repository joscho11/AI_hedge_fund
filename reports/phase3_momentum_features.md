# Phase 3 — Momentum feature family: data-quality & leakage report

> **Survivorship caveat still applies:** features are built on the current-membership S&P 500 panel; diagnostic ICs are descriptive, not a tradeable result. No model yet.

*Family:* `momentum` · *rows:* 80,676 · *source panel:* `data_cache/panel/panel_500tickers.parquet` (80,676 rows, 500 names)

## Leakage discipline

- **Every window is strictly trailing** (ending at `t`), computed with `min_periods == window` so a partial window is NaN, never a look-ahead value.
- **Normalization is per rebalance date** (winsorize 1/99 → z-score + percentile rank), **never pooled across dates**.
- **Missing values are never forward-filled**; a NaN raw value is excluded from that date's cross-section (see per-feature missing rule below).
- Automated check (`tests/test_phase3_features.py`): a 10× price spike at any date **after** `t` leaves every feature value at `t` byte-identical — verified passing.

## Features — coverage & as-of timing

| Feature | Coverage | Missing | As-of timing | Missing rule |
|---|---|---|---|---|
| `ret_1m` | 100.0% | 0.0% | adj(t)/adj(t-21td) - 1 | NaN until 21 trailing sessions; never filled |
| `ret_3m` | 98.9% | 1.1% | adj(t)/adj(t-63td) - 1 | NaN until 63 trailing sessions; never filled |
| `ret_6m` | 97.2% | 2.8% | adj(t)/adj(t-126td) - 1 | NaN until 126 trailing sessions; never filled |
| `ret_12_1` | 93.8% | 6.2% | adj(t-21td)/adj(t-252td) - 1 | NaN until 252 trailing sessions; never filled |
| `vol_6m` | 97.2% | 2.8% | std of daily adj returns over (t-126td, t] | NaN until 126 sessions; never filled |
| `vol_12m` | 93.8% | 6.2% | std of daily adj returns over (t-252td, t] | NaN until 252 sessions; never filled |
| `dist_52w_high` | 94.2% | 5.8% | adj(t)/max(adj over (t-252td, t]) - 1 | NaN until 252 sessions; never filled |
| `dvol_trend` | 94.2% | 5.8% | log( mean$vol(t-21td,t] / mean$vol(t-252td,t] ), raw close x volume | NaN until 252 sessions; never filled |

## Diagnostic per-feature IC (descriptive — NOT a model)

Mean per-date Spearman IC (t-stat) of each raw feature vs each target. `fwd_ret_raw` and `fwd_ret_excess_median` share an IC by rank-invariance.

| Feature | `fwd_ret_raw` | `fwd_ret_excess_median` | `fwd_ret_excess_sector` |
|---|---|---|---|
| `ret_1m` | -0.0119 (t -1.05) | -0.0119 (t -1.05) | -0.0095 (t -1.18) |
| `ret_3m` | -0.0084 (t -0.72) | -0.0084 (t -0.72) | -0.0075 (t -0.86) |
| `ret_6m` | -0.0087 (t -0.73) | -0.0087 (t -0.73) | -0.0066 (t -0.70) |
| `ret_12_1` | 0.0039 (t 0.28) | 0.0039 (t 0.28) | 0.0066 (t 0.64) |
| `vol_6m` | 0.0627 (t 3.38) | 0.0627 (t 3.38) | 0.0447 (t 3.49) |
| `vol_12m` | 0.0575 (t 3.02) | 0.0575 (t 3.02) | 0.0374 (t 2.84) |
| `dist_52w_high` | -0.0180 (t -1.24) | -0.0180 (t -1.24) | -0.0147 (t -1.32) |
| `dvol_trend` | -0.0021 (t -0.32) | -0.0021 (t -0.32) | 0.0070 (t 1.35) |

**Read (diagnostic only — feeds Phase-4 selection, not a tradeable claim):**

- The pure return-momentum features (`ret_1m/3m/6m/12_1`) have ~zero IC, consistent with the Phase-2 finding that momentum has no ranking power on this universe.

- **Notable but NOT yet trusted:** `vol_6m` (t 3.49), `vol_12m` (t 2.84) show |t| ≥ 2 vs `fwd_ret_excess_sector`. Treat with strong suspicion, per DECISIONS **D9**: (a) these are **in-sample, full-period** ICs on a **survivorship-flattered** universe; (b) **24 feature×target comparisons** were run, so a t≈3 is far less impressive after multiple-comparisons adjustment; (c) the volatility features most likely capture a **risk/beta premium** (high-vol names earned more in this bull sample), not cross-sectional alpha. None of this counts until it survives **purged, embargoed out-of-sample** validation in Phase 4.

- Bottom line: these ICs **rank features for the model to consider**, nothing more. A high in-sample IC here is a hypothesis to be falsified out-of-sample, not a signal.
