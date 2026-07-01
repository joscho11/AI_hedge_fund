# Phase 5 (dev) — small/mid-cap panel, features & baselines

> **Development only (≤ 2021-12); 2022+ sealed.** Costs per D18 sweep {25,30,50,100} bps; **verdict bar = survive ≥ 50 bps.** Delisting-aware labels + holding returns (mid-window bankruptcies earn their real loss, never NaN-dropped).

*Panel:* 285,185 rows, 4939 names · *dev window* 2010-01-29→2021-12-31 (144 rebalances). *Feature families:* momentum(8), valuation(12), quality(22), fundamental_momentum(8), context(5).

## Baselines — net CAGR by cost (dev), with Sharpe @50 bps

| Strategy | 25 bps | 30 bps | **50 bps** | 100 bps | Sharpe @50 | MaxDD @50 |
|---|---|---|---|---|---|---|
| IWM (small-cap proxy) | +13.1% | +13.1% | **+13.1%** | +13.1% | 0.75 | -32.3% |
| Equal-weight universe | +12.9% | +12.8% | **+12.3%** | +11.2% | 0.69 | -35.8% |
| 12-1 Momentum (top decile) | +14.1% | +13.7% | **+11.8%** | +7.4% | 0.62 | -37.8% |
| Value (cheapest decile) | +9.0% | +8.7% | **+7.6%** | +4.9% | 0.44 | -54.5% |

*Equal-weight & IWM are low-turnover (cost-insensitive); momentum & value are the cost-sensitive active baselines — watch whether they survive the 50 bps bar.*

## Diagnostic ICs (dev, secondary) — active baselines

| Signal × target | Mean IC | IC-IR | t-stat | % pos |
|---|---|---|---|---|
| momentum|fwd_ret_excess_median | 0.0036 | 0.03 | 0.38 | +50.4% |
| value_earnings_yield|fwd_ret_excess_median | -0.0089 | -0.09 | -1.13 | +41.7% |
| momentum|fwd_ret_excess_sector | 0.0046 | 0.06 | 0.64 | +53.3% |
| value_earnings_yield|fwd_ret_excess_sector | -0.0151 | -0.22 | -2.70 | +38.2% |

> Diagnostic only (D9). The pre-registered model run (Step 3, dev-only) is next; the 2022+ hold-out stays sealed until the Step-4 gate.
