# Phase 4 (dev) — pre-registered models under purged/embargoed walk-forward CV

> **Development period only (≤ 2021-12); the 2022+ hold-out is SEALED.** In-sample to the extent of dev-CV; the hold-out is the final OOS test. Selection rule (D16): IC-IR(folds) → %positive folds → mean IC → sector-neutral tiebreaker.

## The four pre-registered combos (dev OOS)

| Model × Target | Mean IC | IC-IR (folds) | % pos folds | t-stat |
|---|---|---|---|---|
| ridge|fwd_ret_excess_median | 0.0269 | 0.44 | +50.0% | 2.27 |
| ridge|fwd_ret_excess_sector | 0.0226 | 0.40 | +66.7% | 2.25 |
| lgbm|fwd_ret_excess_median | 0.0330 | 0.76 | +50.0% | 2.51 |
| lgbm|fwd_ret_excess_sector | 0.0111 | 0.45 | +50.0% | 1.73 |

**Selected:** `lgbm × fwd_ret_excess_median` — IC-IR(folds) 0.76, %pos folds +50.0%, mean IC 0.0330, t 2.51.

## Regime breakdown (selected combo, dev sub-periods)

| Sub-period | Mean IC | t-stat | N dates |
|---|---|---|---|
| 2013-2015 | -0.0075 | -0.34 | 36 |
| 2016-2018 | 0.0251 | 1.53 | 36 |
| 2019-2021 | 0.0814 | 3.07 | 36 |

## Is any edge a value-short / 2010s-regime bet?

- **Score vs earnings-yield (value):** mean per-date Spearman corr = **-0.103**. A strongly negative value here would mean the model is mostly tilting *away from cheap* (a bet that value keeps losing) — fragile and regime-bound.

- **Long vs short leg (top/bottom decile, delisting-aware):** long 0.0144, short 0.0072, L−S spread 0.0072 (Sharpe 0.52). If the spread is driven by the short leg, the 'edge' is largely a short-the-losers bet.

## Costed backtest (selected, long top-decile, net) vs baselines — SECONDARY (D9)

*Common window 2013-01-31→2021-12-31, 108 rebalances, 6 bps.*

| Strategy | CAGR (net) | Sharpe | MaxDD |
|---|---|---|---|
| model_topdecile | +14.9% | 0.71 | -39.3% |
| SPY | +15.2% | 1.12 | -19.4% |
| equal_weight | +14.0% | 0.94 | -27.6% |

## Read (dev only — NOT a result until the sealed hold-out)

- **Weak / fragile dev signal.** Despite a headline IC-IR of 0.76, only **+50.0% of folds are positive** and the IC is **concentrated in the most recent sub-period** (2019-2021 IC 0.0814 vs 2013-2015 -0.0075). That is the opposite of durable, regime-independent selection.

- **Does not beat SPY after costs:** model top-decile Sharpe 0.71 vs SPY 1.12 (net CAGR +14.9% vs +15.2%), with a far deeper drawdown.

- **Value-short exposure is mild** (corr -0.103): the apparent edge is not primarily a short-the-cheap bet, and the long leg (not the short) carries the L−S spread — so it is not merely a value-regime artifact, but it is also not robust.

- **Honest expectation for the hold-out:** a signal concentrated in 2019-2021 with 50% positive folds is exactly the profile that tends to **not** survive a fresh OOS period. Per D9, the verdict waits for the single 2022+ evaluation.


> **Hold-out remains sealed.** Step 3 (single 2022+ evaluation) only after explicit approval.
