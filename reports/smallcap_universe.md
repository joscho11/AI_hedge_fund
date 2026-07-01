# Phase 5 — small/mid-cap universe (point-in-time, delisted-inclusive)

> Pre-registration candidates (DECISIONS D18), pending approval before the pipeline rebuilds on this universe.

## Pre-registered filters (candidates)

- Domestic common stock only (primary listings); delisted-inclusive.
- Market-cap band **[$300M, $5B]** (price-at-t × as-of-t ARQ sharesbas); concurrent S&P 500 members excluded.
- Liquidity: price **> $5**, 20-day median dollar volume **> $1M/day** (as-of t).
- One-way cost **30 bps** (sensitivity {25,50,100}); monthly, 63d label.

## Validation

- **Names per rebalance:** 1400 / 1582 / 1848 (min/median/max); start 2010-01-29=1434, end 2024-12-31=1483. Distinct names ever: **4,939** (vs 789 in the large-cap honest universe).

- **Realized market-cap band ($M):** min 300, p25 731, median 1372, p75 2506, max 5000 — within the [$300M, $5B] band by construction. Median 20d dollar volume: $8.5M/day.

- **Delisting/bankruptcy:** 51.6% of universe names are flagged delisted (2,549 names); 431 had a bankruptcy/liquidation. Far higher churn than large-caps — survivorship bias would be severe here, so delisted-inclusion + delisting-aware labels (Step 2) are essential.

- **Ticker-recycling check (scoped to this universe):** **0 collisions** — no ticker maps to >1 permaticker even in this churny universe (Sharadar disambiguates recycled symbols at source). Ticker joins are safe; permaticker carried + date-bounded lookups as defense-in-depth.

- **Fundamentals coverage:** 99.2% of membership rows have an as-of-t ART revenue. Spottier than large-caps; features will be NaN where missing (never filled), with coverage reported per family in Step 2.

- **Point-in-time membership:** all filters (liquidity, market cap, S&P exclusion) use only data with date/datekey ≤ t; a name enters the band only when its as-of-t cap/liquidity qualify it (see `tests/test_smallcap_universe.py`).


> Next (Step 2, after approval): delisting-aware labeled panel + five feature families on this universe; small-cap baselines. Hold-out (2022+) stays sealed.
