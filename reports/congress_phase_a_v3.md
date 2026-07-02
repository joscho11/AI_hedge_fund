# Congress Phase A v3 — clustering + member persistence (market-adjusted, dev only)

> **Exploratory, in-sample, DEV ≤2022; 2023+ hold-out SEALED (D9/D21).** Entry = disclosure date; buys; market-adjusted (−SPY). **Arena #3 + multiple sub-tests — heavy multiple-comparisons risk; nothing here is a result without OOS.**

Dev equity buys with realized forward returns: **12,022**.

## TEST 1 — Clustering (≥3 distinct members, same ticker, 30-day window; entry = completing disclosure)

- **Cluster-event count: 291.** Enough events for a descriptive read.

| Group | adj 21d mean (med) | adj 63d mean (med, t) | n(63d) |
|---|---|---|---|
| **Cluster** (entry=completing) | +0.51% (+0.47%) | +0.21% (+1.32%, t 0.27) | 291 |
| Isolated buys | +0.21% (-0.18%) | +0.29% (-0.36%, t 1.83) | 11188 |

- Cluster premium (63d adj, cluster − isolated): **-0.09%**.
- By sub-period (cluster 63d adj): P1: +1.06% (n=76), P2: -0.09% (n=215).

## TEST 2 — Member persistence (P1 2014-18 → P2 2019-22; NOT a leaderboard)

- **Members clearing ≥25 buys + ≥10/period: 32** (the effective sample).
- **P1↔P2 rank correlation of per-member market-adjusted 63d return: 0.06** (p=0.74). ≈0 ⇒ a member's P1 performance does NOT predict P2 — selection noise.
- **P1 top-quintile members' P2 return: +1.38%** vs rest +1.16% (diff +0.22%, n_top=7). If the top-P1 members don't beat the rest in P2, following them is not a real edge.

## Verdict

- **Test 1 (clustering): no usable cluster edge.** Cluster 63d market-adjusted return +0.21% (t 0.27) is not a significant, material premium over isolated buys. No case for a hold-out test.

- **Test 2 (member persistence): does NOT persist.** P1↔P2 rank corr 0.06, top-P1 minus rest in P2 +0.22% — a member's past market-adjusted performance does not predict the future. **Individual-member 'edge' is selection noise; no one worth following.**


- **Multiple-comparisons frame:** arena #3, and within it clustering + persistence + sub-period + owner slices. Even a nominally significant dev result here is a weak prior given how many things have been tried across the program.


> **STOP for review. 2023+ hold-out untouched.** A sealed-hold-out test happens only if a dev result genuinely warrants it and you approve.
