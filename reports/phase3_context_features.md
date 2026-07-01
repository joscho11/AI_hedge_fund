# Phase 3 — context (sector/macro) family (honest universe)

> Conditioning inputs for the model, **not** standalone ranking signals.

*Family:* `context` · *features:* 5 · *source panel:* `data_cache/panel/panel_honest.parquet`

**No cross-sectional IC is reported here, by design:** the macro features (`term_spread`, `credit_spread`, `vix`, `mkt_ret_63d`) are **date-level** — constant across names on a given date — so their cross-sectional IC is ~0 by construction; they are regime-conditioning inputs for model interactions. `sector_id` is categorical. Sector-relative ranking content already lives in the valuation/quality families.

## Features — coverage & as-of timing

| Feature | Coverage | Kind | As-of timing |
|---|---|---|---|
| `sector_id` | 100.0% | cross-sectional (categorical) | integer code of the name's sector at t |
| `term_spread` | 100.0% | date-level | FRED value as-of t (real-time series) |
| `credit_spread` | 10.6% | date-level | FRED value as-of t (real-time series) |
| `vix` | 100.0% | date-level | FRED value as-of t (real-time series) |
| `mkt_ret_63d` | 98.4% | date-level | SPY closeadj(t)/closeadj(t-63td)-1 |