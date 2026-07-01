# Phase 3 — quality feature family (honest universe)

> **Backtested, in-sample, honest universe (survivorship-addressed).** Diagnostic ICs are exploratory — they count only if they survive Phase-4 purged/embargoed OOS (D9).

*Family:* `quality` · *features:* 22 · *rows:* 90,055 · *source panel:* `data_cache/panel/panel_honest.parquet`

## Features — coverage & as-of timing

| Feature | Coverage | Missing | As-of timing | Missing rule |
|---|---|---|---|---|
| `roe` | 95.3% | 4.7% | Sharadar roe, datekey<=t | NaN if equity<=0 |
| `roe_sectrel` | 95.3% | 4.7% | Sharadar roe, datekey<=t; sector from TICKERS (current classification) | NaN if level or sector missing |
| `roic` | 99.1% | 0.9% | Sharadar roic, datekey<=t | NaN if undefined |
| `roic_sectrel` | 99.1% | 0.9% | Sharadar roic, datekey<=t; sector from TICKERS (current classification) | NaN if level or sector missing |
| `roa` | 99.1% | 0.9% | Sharadar roa, datekey<=t | NaN if undefined |
| `roa_sectrel` | 99.1% | 0.9% | Sharadar roa, datekey<=t; sector from TICKERS (current classification) | NaN if level or sector missing |
| `gross_margin` | 99.3% | 0.7% | Sharadar grossmargin, datekey<=t | NaN if undefined |
| `gross_margin_sectrel` | 99.3% | 0.7% | Sharadar grossmargin, datekey<=t; sector from TICKERS (current classification) | NaN if level or sector missing |
| `op_margin` | 99.3% | 0.7% | opinc/revenue, datekey<=t | NaN if revenue<=0 |
| `op_margin_sectrel` | 99.3% | 0.7% | opinc/revenue, datekey<=t; sector from TICKERS (current classification) | NaN if level or sector missing |
| `net_margin` | 99.3% | 0.7% | Sharadar netmargin, datekey<=t | NaN if undefined |
| `net_margin_sectrel` | 99.3% | 0.7% | Sharadar netmargin, datekey<=t; sector from TICKERS (current classification) | NaN if level or sector missing |
| `ebitda_margin` | 99.3% | 0.7% | Sharadar ebitdamargin, datekey<=t | NaN if undefined |
| `debt_to_equity` | 95.5% | 4.5% | Sharadar de, datekey<=t | NaN if equity<=0 |
| `debt_to_equity_sectrel` | 95.5% | 4.5% | Sharadar de, datekey<=t; sector from TICKERS (current classification) | NaN if level or sector missing |
| `current_ratio` | 83.8% | 16.2% | Sharadar currentratio, datekey<=t | NaN if undefined |
| `interest_coverage` | 85.1% | 14.9% | ebit/intexp, datekey<=t | NaN if intexp<=0 |
| `fcf_yield` | 99.3% | 0.7% | ART fcfps (datekey<=t) / close_raw(t) | sign kept; NaN if price missing |
| `fcf_yield_sectrel` | 99.3% | 0.7% | ART fcfps (datekey<=t) / close_raw(t); sector from TICKERS (current classification) | NaN if level or sector missing |
| `fcf_margin` | 99.3% | 0.7% | fcf/revenue, datekey<=t | NaN if revenue<=0 |
| `fcf_margin_sectrel` | 99.3% | 0.7% | fcf/revenue, datekey<=t; sector from TICKERS (current classification) | NaN if level or sector missing |
| `net_margin_stability` | 80.4% | 19.6% | std over trailing 60m (min 24m) of net_margin (each datekey<=t) | NaN until 24 prior monthly obs |

## Diagnostic per-feature IC (descriptive — NOT a model)

| Feature | `fwd_ret_raw` | `fwd_ret_excess_median` | `fwd_ret_excess_sector` |
|---|---|---|---|
| `roe` | 0.0184 (t 1.98) | 0.0184 (t 1.98) | 0.0141 (t 1.96) |
| `roe_sectrel` | 0.0140 (t 1.98) | 0.0140 (t 1.98) | 0.0144 (t 1.85) |
| `roic` | 0.0213 (t 1.81) | 0.0213 (t 1.81) | 0.0125 (t 1.42) |
| `roic_sectrel` | 0.0143 (t 1.73) | 0.0143 (t 1.73) | 0.0129 (t 1.31) |
| `roa` | 0.0112 (t 0.98) | 0.0112 (t 0.98) | 0.0089 (t 1.00) |
| `roa_sectrel` | 0.0094 (t 1.11) | 0.0094 (t 1.11) | 0.0090 (t 0.90) |
| `gross_margin` | 0.0062 (t 0.85) | 0.0062 (t 0.85) | -0.0068 (t -1.15) |
| `gross_margin_sectrel` | -0.0095 (t -1.30) | -0.0095 (t -1.30) | -0.0090 (t -1.43) |
| `op_margin` | 0.0019 (t 0.23) | 0.0019 (t 0.23) | -0.0050 (t -0.66) |
| `op_margin_sectrel` | -0.0023 (t -0.31) | -0.0023 (t -0.31) | -0.0032 (t -0.39) |
| `net_margin` | 0.0018 (t 0.22) | 0.0018 (t 0.22) | -0.0058 (t -0.73) |
| `net_margin_sectrel` | -0.0011 (t -0.14) | -0.0011 (t -0.14) | -0.0035 (t -0.41) |
| `ebitda_margin` | -0.0074 (t -0.84) | -0.0074 (t -0.84) | -0.0074 (t -1.09) |
| `debt_to_equity` | 0.0208 (t 2.56) | 0.0208 (t 2.56) | 0.0170 (t 3.00) |
| `debt_to_equity_sectrel` | 0.0099 (t 1.73) | 0.0099 (t 1.73) | 0.0130 (t 1.84) |
| `current_ratio` | 0.0018 (t 0.18) | 0.0018 (t 0.18) | -0.0110 (t -1.89) |
| `interest_coverage` | 0.0059 (t 0.63) | 0.0059 (t 0.63) | 0.0007 (t 0.09) |
| `fcf_yield` | 0.0050 (t 0.48) | 0.0050 (t 0.48) | -0.0137 (t -1.87) |
| `fcf_yield_sectrel` | -0.0132 (t -1.76) | -0.0132 (t -1.76) | -0.0130 (t -1.56) |
| `fcf_margin` | 0.0362 (t 4.89) | 0.0362 (t 4.89) | 0.0098 (t 1.88) |
| `fcf_margin_sectrel` | 0.0154 (t 2.84) | 0.0154 (t 2.84) | 0.0161 (t 2.77) |
| `net_margin_stability` | -0.0171 (t -2.08) | -0.0171 (t -2.08) | -0.0165 (t -2.55) |

**Notable in-sample (NOT yet trusted):** `debt_to_equity` (t 3.00), `fcf_margin_sectrel` (t 2.77), `net_margin_stability` (t -2.55) clear |t|≥2 vs `fwd_ret_excess_sector`. With 66 comparisons in this family alone, treat as hypotheses for Phase-4 OOS, not results (D9).
