# Phase 3 — fundamental_momentum feature family (honest universe)

> **Backtested, in-sample, honest universe (survivorship-addressed).** Diagnostic ICs are exploratory — they count only if they survive Phase-4 purged/embargoed OOS (D9).

*Family:* `fundamental_momentum` · *features:* 8 · *rows:* 90,055 · *source panel:* `data_cache/panel/panel_honest.parquet`

**Headliner family.** Best prior for real signal ('improving fundamentals before price reprices'). NOTE: analyst estimate revisions are absent — SF1 is reported fundamentals, not estimates; no proxy is fabricated. Any in-sample IC below is a hypothesis for Phase-4 OOS, not a result.

## Features — coverage & as-of timing

| Feature | Coverage | Missing | As-of timing | Missing rule |
|---|---|---|---|---|
| `rev_yoy` | 98.9% | 1.1% | revenue_asof(t)/revenue_asof(t-252td)-1 | NaN if year-ago revenue<=0 |
| `eps_yoy` | 90.9% | 9.1% | epsusd_asof(t)/epsusd_asof(t-252td)-1 | NaN if year-ago EPS<=0 |
| `gp_yoy` | 98.7% | 1.3% | gp_asof(t)/gp_asof(t-252td)-1 | NaN if year-ago GP<=0 |
| `fcf_yoy` | 87.1% | 12.9% | fcf_asof(t)/fcf_asof(t-252td)-1 | NaN if year-ago FCF<=0 |
| `rev_accel` | 98.8% | 1.2% | rev_yoy(t) - rev_yoy(t-63td) | NaN if either YoY undefined |
| `eps_accel` | 89.1% | 10.9% | eps_yoy(t) - eps_yoy(t-63td) | NaN if either YoY undefined |
| `net_margin_trend` | 98.9% | 1.1% | netmargin_asof(t) - netmargin_asof(t-252td) | NaN if either endpoint missing |
| `gross_margin_trend` | 98.9% | 1.1% | grossmargin_asof(t) - grossmargin_asof(t-252td) | NaN if either endpoint missing |

## Diagnostic per-feature IC (descriptive — NOT a model)

| Feature | `fwd_ret_raw` | `fwd_ret_excess_median` | `fwd_ret_excess_sector` |
|---|---|---|---|
| `rev_yoy` | -0.0090 (t -0.91) | -0.0090 (t -0.91) | -0.0063 (t -0.80) |
| `eps_yoy` | -0.0182 (t -2.15) | -0.0182 (t -2.15) | -0.0132 (t -1.97) |
| `gp_yoy` | -0.0143 (t -1.35) | -0.0143 (t -1.35) | -0.0056 (t -0.69) |
| `fcf_yoy` | 0.0159 (t 2.61) | 0.0159 (t 2.61) | 0.0143 (t 2.69) |
| `rev_accel` | 0.0023 (t 0.29) | 0.0023 (t 0.29) | -0.0001 (t -0.02) |
| `eps_accel` | 0.0029 (t 0.47) | 0.0029 (t 0.47) | -0.0019 (t -0.37) |
| `net_margin_trend` | -0.0202 (t -2.74) | -0.0202 (t -2.74) | -0.0175 (t -3.23) |
| `gross_margin_trend` | -0.0071 (t -1.00) | -0.0071 (t -1.00) | 0.0008 (t 0.14) |

**Notable in-sample (NOT yet trusted):** `fcf_yoy` (t 2.69), `net_margin_trend` (t -3.23) clear |t|≥2 vs `fwd_ret_excess_sector`. With 24 comparisons in this family alone, treat as hypotheses for Phase-4 OOS, not results (D9).
