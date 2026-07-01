# Honest vs flattered universe — the survivorship-free re-run

> **Backtested research, not advice. In-sample (no Phase-4 OOS yet).** 'Flattered' = current-membership S&P 500 (survivors only). 'Honest' = point-in-time membership + delisted names, with delisting-aware labels and holding returns.

## Headline: does the survivorship drift collapse?

Equal-weight − SPY CAGR: **+3.5% (flattered) → -0.9% (honest)**. 
The ~3.5pp/yr 'edge' from holding today's survivors **collapses toward zero** once removed/delisted names are included — confirming it was bias, not skill.

## Baselines — flattered → honest (net, common window)

| Strategy | CAGR flat → honest | Sharpe flat → honest | MaxDD flat → honest |
|---|---|---|---|
| SPY (buy & hold) | +13.5% → +14.4% | 0.961 → 1.002 | -23.9% → -23.9% |
| Equal-weight universe | +16.9% → +13.5% | 1.093 → 0.866 | -23.9% → -27.6% |
| 12-1 Momentum (top decile) | +21.3% → +14.3% | 1.173 → 0.875 | -21.4% → -20.4% |
| Value (cheapest decile) | +15.7% → +10.6% | 0.816 → 0.578 | -40.7% → -44.4% |

## Do the prior findings survive contact with delisted names?

- **Inverted value premium:** earnings-yield IC -0.019 (t -1.930) → -0.033 (t -3.639). Stays **negative** — value still didn't pay here, not merely a survivorship artifact.

- **vol_6m:** IC 0.045 (t 3.493) → -0.009 (t -0.730) — **fades** (|t|<2).
- **vol_12m:** IC 0.037 (t 2.844) → -0.013 (t -1.035) — **fades** (|t|<2).
- **12-1 momentum (signal):** IC 0.004 (t 0.283) → 0.009 (t 0.677) — still null.


> **D9 / multiple-comparisons caution:** this is the first out-of-the-survivorship-bubble read, **still in-sample**. A sign-flip or surviving IC here is a stronger hypothesis than before, but not yet a tradeable edge — that requires the Phase-4 purged, embargoed out-of-sample test.
