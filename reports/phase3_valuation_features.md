# Phase 3 — Valuation feature family: data-quality & leakage report

> **Survivorship caveat still applies:** features are built on the current-membership S&P 500 panel; diagnostic ICs are descriptive, not a tradeable result.

*Family:* `valuation` (first fundamental family, Sharadar SF1, point-in-time) · *rows:* 80,676 · *source panel:* `data_cache/panel/panel_500tickers.parquet`

## Leakage discipline (fundamentals)

- **`datekey <= t` strictly**, **as-reported (AR*) dimensions only** — MR* (restatement-backfilled) are refused by the provider.
- **Price-at-`t` numerator, fundamental-as-of-`t` denominator** — never a future filing.
- Per-date cross-sectional normalization (base); sector from as-of TICKERS reference.
- Negative/zero earnings, sales, book, or EBITDA -> feature **undefined (NaN), not 0**.
- Tested (`tests/test_valuation_features.py`): a value restated at a later `datekey` does not change an earlier-`t` feature; negative earnings yield is NaN, never 0.

## Features — coverage & as-of timing

| Feature | Coverage | Missing | As-of timing | Missing rule |
|---|---|---|---|---|
| `earnings_yield` | 90.3% | 9.7% | ART eps (datekey<=t) / close_raw(t); neg/zero earnings -> NaN | NaN if undefined (see as-of); never filled |
| `earnings_yield_sectrel` | 90.3% | 9.7% | ART eps (datekey<=t) / close_raw(t); neg/zero earnings -> NaN; sector from TICKERS (current classification) | NaN if level or sector missing; never filled |
| `earnings_yield_hist` | 76.2% | 23.8% | ART eps (datekey<=t) / close_raw(t); neg/zero earnings -> NaN; z over trailing 60m (min 24m) of own metric | NaN until 24 prior monthly obs; never filled |
| `sales_yield` | 98.5% | 1.5% | ART sps (datekey<=t) / close_raw(t); neg/zero sales -> NaN | NaN if undefined (see as-of); never filled |
| `sales_yield_sectrel` | 98.5% | 1.5% | ART sps (datekey<=t) / close_raw(t); neg/zero sales -> NaN; sector from TICKERS (current classification) | NaN if level or sector missing; never filled |
| `sales_yield_hist` | 84.4% | 15.6% | ART sps (datekey<=t) / close_raw(t); neg/zero sales -> NaN; z over trailing 60m (min 24m) of own metric | NaN until 24 prior monthly obs; never filled |
| `ev_ebitda` | 95.5% | 4.5% | [close_raw(t)*ARQ sharesbas + ARQ debt - ARQ cashneq] / ART ebitda (all datekey<=t); EBITDA<=0 -> NaN (lower=cheaper) | NaN if undefined (see as-of); never filled |
| `ev_ebitda_sectrel` | 95.5% | 4.5% | [close_raw(t)*ARQ sharesbas + ARQ debt - ARQ cashneq] / ART ebitda (all datekey<=t); EBITDA<=0 -> NaN (lower=cheaper); sector from TICKERS (current classification) | NaN if level or sector missing; never filled |
| `ev_ebitda_hist` | 81.5% | 18.5% | [close_raw(t)*ARQ sharesbas + ARQ debt - ARQ cashneq] / ART ebitda (all datekey<=t); EBITDA<=0 -> NaN (lower=cheaper); z over trailing 60m (min 24m) of own metric | NaN until 24 prior monthly obs; never filled |
| `book_to_price` | 94.4% | 5.6% | ARQ bvps (datekey<=t) / close_raw(t); neg/zero book -> NaN | NaN if undefined (see as-of); never filled |
| `book_to_price_sectrel` | 94.4% | 5.6% | ARQ bvps (datekey<=t) / close_raw(t); neg/zero book -> NaN; sector from TICKERS (current classification) | NaN if level or sector missing; never filled |
| `book_to_price_hist` | 80.3% | 19.7% | ARQ bvps (datekey<=t) / close_raw(t); neg/zero book -> NaN; z over trailing 60m (min 24m) of own metric | NaN until 24 prior monthly obs; never filled |

## Diagnostic per-feature IC (descriptive — NOT a model)

Mean per-date Spearman IC (t-stat) vs each target. `fwd_ret_raw` == `excess_median` by rank-invariance.

| Feature | `fwd_ret_raw` | `fwd_ret_excess_median` | `fwd_ret_excess_sector` |
|---|---|---|---|
| `earnings_yield` | -0.0171 (t -1.47) | -0.0171 (t -1.47) | -0.0190 (t -1.93) |
| `earnings_yield_sectrel` | -0.0226 (t -2.33) | -0.0226 (t -2.33) | -0.0227 (t -2.15) |
| `earnings_yield_hist` | 0.0059 (t 0.64) | 0.0059 (t 0.64) | 0.0023 (t 0.29) |
| `sales_yield` | 0.0074 (t 0.61) | 0.0074 (t 0.61) | 0.0076 (t 0.74) |
| `sales_yield_sectrel` | 0.0036 (t 0.36) | 0.0036 (t 0.36) | 0.0072 (t 0.65) |
| `sales_yield_hist` | 0.0192 (t 1.47) | 0.0192 (t 1.47) | 0.0063 (t 0.59) |
| `ev_ebitda` | 0.0183 (t 1.51) | 0.0183 (t 1.51) | 0.0157 (t 1.53) |
| `ev_ebitda_sectrel` | 0.0178 (t 1.73) | 0.0178 (t 1.73) | 0.0191 (t 1.74) |
| `ev_ebitda_hist` | -0.0034 (t -0.34) | -0.0034 (t -0.34) | 0.0025 (t 0.31) |
| `book_to_price` | -0.0360 (t -2.89) | -0.0360 (t -2.89) | -0.0253 (t -2.47) |
| `book_to_price_sectrel` | -0.0247 (t -2.62) | -0.0247 (t -2.62) | -0.0251 (t -2.31) |
| `book_to_price_hist` | -0.0042 (t -0.37) | -0.0042 (t -0.37) | -0.0119 (t -1.32) |

**Read (diagnostic only — feeds Phase-4 selection, not a tradeable claim):**

- **The value premium is absent/inverted on this sample:** earnings_yield (IC -0.0190) and book-to-price (IC -0.0253) are **negatively** predictive — cheap stocks *underperformed*. This is the well-documented 2010s 'value drought', amplified by survivorship: the current-membership universe is dominated by growth winners that got richer. Expect the Step-3 value baseline to **trail** equal-weight here — an honest regime/sample result, not a coding error. On a point-in-time, delisting-inclusive universe the sign and magnitude may differ.

- **Notable but NOT yet trusted:** `earnings_yield_sectrel` (t -2.15), `book_to_price` (t -2.47), `book_to_price_sectrel` (t -2.31) clear |t| ≥ 2 vs `fwd_ret_excess_sector`. Per DECISIONS **D9** treat with suspicion: in-sample, full-period, **survivorship-flattered**, and **36 feature×target comparisons** were run (a t≈3 is unremarkable after multiple-comparisons adjustment). Counts only after purged, embargoed out-of-sample validation in Phase 4.

- These ICs **rank features for the model to consider**, nothing more. A high in-sample IC is a hypothesis to falsify out-of-sample, not a signal.
