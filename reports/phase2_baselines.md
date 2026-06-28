# Phase 2 — Baseline Performance Report

> **Survivorship caveat:** universe = CURRENT S&P 500 membership on the free stack. Every number below is **survivorship-flattered**. Reference market/universe drift: raw forward return averages +4.3%/63d (~18%/yr). Treat absolute returns as upward-biased; the honest signal is whether an edge survives *after* removing that common drift (excess-vs-median). Point-in-time (Sharadar) re-run pending.

*Universe:* 500 current S&P 500 names · *Common window:* 2011-01-31 → 2024-09-30 (165 monthly rebalances) · *One-way cost:* 6 bps

## Performance (common window, net of costs unless noted)

| Strategy | CAGR (net) | CAGR (gross) | Ann.Vol | Sharpe (net) | Sortino (net) | MaxDD | Hit | Turn/reb | Cost drag (cum) |
|---|---|---|---|---|---|---|---|---|---|
| SPY (buy & hold) | +13.48% | +13.48% | +14.28% | 0.961 | 1.403 | -23.93% | +69.09% | +0.00% | +0.00% |
| Equal-weight universe | +16.94% | +16.98% | +15.50% | 1.093 | 1.523 | -23.94% | +67.88% | +2.71% | +4.57% |
| 12-1 Momentum (top decile) | +21.35% | +21.87% | +17.99% | 1.173 | 1.876 | -21.36% | +68.48% | +30.41% | +87.51% |

*Equal-weight vs SPY shows the survivorship drift directly; momentum must beat the best of these **after costs** to be real.*

## Honest read

- **Survivorship drift is visible and material:** equal-weight universe CAGR +16.94% vs SPY +13.48% — a ~3pp/yr gap from holding *today's* survivors, consistent with the +4.3%/63d (~18%/yr) fingerprint. This is a measured bias, not alpha.
- **Momentum's headline CAGR (+21.35%) overstates its edge.** Mean IC 0.004 (t = 0.283) is **not** statistically significant (|t| < 2) and below the 0.03–0.05 genuine-signal band; risk-adjusted, momentum's Sharpe (1.173) is above equal-weight (1.093), with deeper drawdown (-21.36%) and far higher turnover (+30.41%/reb). The decile spread is concentrated in the top decile rather than monotonic.
- **Momentum is cost-robust** (net CAGR barely moves 5→20 bps): even ~30% monthly turnover × 20 bps is a small drag. So costs are *not* what holds momentum back here — weak, insignificant signal is.

## Sample vs full universe — do the conclusions hold?

| Metric | 110-name sample (110) | Full universe (500) |
|---|---|---|
| Survivorship drift (EW − SPY CAGR) | +3.03% | +3.46% |
| SPY CAGR (net) | +13.48% | +13.48% |
| Equal-weight CAGR (net) | +16.51% | +16.94% |
| Momentum CAGR (net) | +23.61% | +21.35% |
| Momentum Sharpe (net) | 1.091 | 1.173 |
| Equal-weight Sharpe (net) | 1.097 | 1.093 |
| Momentum mean IC (raw) | 0.021 | 0.004 |
| Momentum IC t-stat | 1.234 | 0.283 |
| Momentum IC % positive | +55.76% | +50.30% |
| Decile monotonicity ρ (raw) | 0.236 | -0.103 |
| Decile top−bottom (raw) | 0.018 | 0.008 |

**Verdict — conclusions held / changed:**

- Survivorship drift: +3.03% → +3.46%. **HELD** — equal-weight still beats SPY, the universe is still survivors.
- Momentum signal strength: mean IC 0.021 (t 1.234) → 0.004 (t 0.283). **HELD** (threshold |t| ≥ 2).
- Top-decile momentum Sharpe vs equal-weight: 1.091 vs 1.097 → 1.173 vs 1.093. The portfolio Sharpe edges ahead — but see the synthesis: this is **not** IC-supported.

**Synthesis — does momentum work? No, and breadth made that clearer.** Adding cross-sectional breadth drove the momentum IC *toward zero* (mean IC 0.004, t 0.283, +50.30% of months positive — a coin flip) and decile monotonicity went negative (-0.103): the deciles are a U-shape, not a ranking. The top-decile portfolio's higher Sharpe is therefore an *extreme-decile, period-specific* effect with **no significant cross-sectional signal beneath it** — precisely the flashy-number-without-edge pattern this project distrusts. Net: the Step-1 conclusion (12-1 momentum is not a robust signal on this universe) is **strengthened**, not overturned, by the full-scale run. Treat the portfolio Sharpe as fragile until an out-of-sample / IC-backed result confirms it.

## 12-1 Momentum — Information Coefficient

| Target | N dates | Mean IC | IC IR | t-stat | % positive |
|---|---|---|---|---|---|
| `fwd_ret_raw` | 165 | 0.004 | 0.022 | 0.283 | +50.30% |
| `fwd_ret_excess_median` | 165 | 0.004 | 0.022 | 0.283 | +50.30% |
| `fwd_ret_excess_sector` | 165 | 0.007 | 0.050 | 0.636 | +52.12% |

*A stable mean IC of ~0.03–0.05 is a genuine signal. The `excess_median` / `excess_sector` columns reveal how much is sector tilt vs within-sector selection.*

> **Note (expected, not a bug):** IC for `fwd_ret_raw` and `fwd_ret_excess_median` is identical because subtracting a per-date constant (the universe median) does not change the cross-sectional *ranking* of names, and Spearman IC is rank-based. The decile-mean *levels* differ (shifted down by the median); only `excess_sector`, which re-ranks within sector, changes the IC.

## 12-1 Momentum — Decile spread (mean forward target by signal decile)

- **`fwd_ret_raw`** — top−bottom = +0.0081, monotonicity ρ = -0.103
  - D0:+0.047 D1:+0.045 D2:+0.040 D3:+0.040 D4:+0.043 D5:+0.042 D6:+0.039 D7:+0.039 D8:+0.043 D9:+0.055
- **`fwd_ret_excess_median`** — top−bottom = +0.0081, monotonicity ρ = -0.103
  - D0:+0.009 D1:+0.006 D2:+0.002 D3:+0.001 D4:+0.005 D5:+0.004 D6:+0.001 D7:+0.000 D8:+0.005 D9:+0.017
- **`fwd_ret_excess_sector`** — top−bottom = +0.0068, monotonicity ρ = -0.018
  - D0:+0.007 D1:+0.005 D2:+0.001 D3:+0.001 D4:+0.003 D5:+0.003 D6:+0.001 D7:+0.000 D8:+0.005 D9:+0.014

## Cost sensitivity (momentum net CAGR)

| One-way cost (bps) | Net CAGR |
|---|---|
| 5 | +21.43% |
| 10 | +21.00% |
| 20 | +20.13% |

## Decisions in this phase

- **Value baseline deferred to Phase 3** (DECISIONS D7): a clean as-of-t valuation ratio needs TTM + shares-outstanding alignment from EDGAR — feature-layer work.
