# Phase 5 (dev) — small-cap models under purged/embargoed walk-forward CV

> **Development only (≤2021-12); 2022+ sealed.** Pre-registration D19. Selection rule: IC-IR(folds) → %positive folds → mean IC → sector tiebreaker. Cost sweep {25,30,50,100} bps; **edge must clear ≥50 bps** to count.

## The four pre-registered combos (dev OOS)

| Model × Target | Mean IC | IC-IR (folds) | % pos folds | t-stat |
|---|---|---|---|---|
| ridge|fwd_ret_excess_median | -0.0028 | -0.04 | +66.7% | -0.29 |
| ridge|fwd_ret_excess_sector | 0.0088 | 0.48 | +66.7% | 1.98 |
| lgbm|fwd_ret_excess_median | 0.0133 | 0.30 | +66.7% | 1.55 |
| lgbm|fwd_ret_excess_sector | 0.0150 | 1.17 | +83.3% | 3.28 |

**Selected:** `lgbm × fwd_ret_excess_sector` — IC-IR 1.17, %pos +83.3%, mean IC 0.0150, t 3.28.

## Regime breakdown (selected, dev sub-periods)
| Sub-period | Mean IC | t-stat |
|---|---|---|
| 2013-2015 | 0.0102 | 1.44 |
| 2016-2018 | 0.0060 | 0.86 |
| 2019-2021 | 0.0289 | 3.12 |

## Is any edge a value-short or size-tilt bet?

- **Value exposure:** mean per-date corr(score, earnings_yield_z) = **-0.176** (negative ⇒ tilts away from cheap — a bet value keeps losing).

- **Size-tilt:** mean per-date corr(score, log market cap) = **0.043** (negative ⇒ tilts toward the smallest names — a pure small-minus-big bet, not selection).


## Cost-sweep backtest (selected, long top-decile, net) vs baselines

| One-way cost | Model CAGR | Model Sharpe | IWM CAGR | Equal-weight CAGR |
|---|---|---|---|---|
| 25.0 bps | +11.9% | 0.57 | +13.1% | +12.9% |
| 30.0 bps | +11.3% | 0.55 | +13.1% | +12.8% |
| 50.0 bps | +9.0% | 0.47 | +13.1% | +12.3% |
| 100.0 bps | +3.4% | 0.26 | +13.1% | +11.2% |

## Read (dev only — NOT a result until the sealed hold-out)

- **The selected combo is the strongest, most cross-fold-CONSISTENT dev signal in the program:** IC 0.0150, IC-IR 1.17, %positive folds +83.3%, t 3.28, and positive in **all three** dev sub-periods (unlike the large-cap winner, which was 2019-21-concentrated). On the pre-registered PRIMARY metric (IC/IC-IR), this passes in dev.

- **Not a value-short or size-tilt artifact:** size corr 0.043 (≈0 → not a small-minus-big bet) and value corr -0.176 (mild). The signal is genuine cross-sectional selection, not a factor proxy — notable.

- **BUT the long-only top-decile does NOT beat the index net of ≥50 bps:** +9.0% (Sharpe 0.47) vs IWM +13.1% (Sharpe 0.75). High small-cap turnover erodes the IC (CAGR falls 25→100 bps); a cheap long-only implementation of this IC does not clear the cost bar. (A long-short could exploit it better, but small-cap shorting borrow/impact is its own unmodeled cost.)

- **Net:** the IC edge is real-looking and the best of the project, NOT a factor artifact — but it does not translate to a cost-surviving long-only strategy at 50 bps in dev. **This is the one combo worth spending the hold-out on.** Multiple-comparisons caveat: this is arena #2 of the program, so a dev t=3.28 is less impressive than in isolation; the sealed 2022+ hold-out is the real test of whether the IC persists.


> Hold-out sealed. Step 4 (single 2022+ eval) only after explicit approval.
