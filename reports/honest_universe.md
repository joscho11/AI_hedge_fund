# Honest universe — point-in-time, delisting-inclusive S&P 500

Step 1 of the survivorship-free re-run. This universe replaces the current-membership ("flattered") one: at each monthly rebalance, members are reconstructed from Sharadar SP500 add/remove events, **including names later removed or delisted**.

## Construction & keys

- **Membership** = add/remove intervals (`added <= t < removed`); re-additions handled; a `removed` with no prior `added` (member before 1957 tracking) opens at -inf.
- **Entity key:** Sharadar `ticker` is non-recycled here (0 of 31,467 map to >1 permaticker), so ticker joins don't cross-wire companies; `permaticker` is still carried and SEP/SF1 lookups are bounded to each name's [firstpricedate, lastpricedate].

## Delisting-return rule (the part that's easy to get wrong)

Forward return `t -> t+H` on SEP adjusted close (`closeadj`). If a name's price history ends before `t+H` (it delisted inside the window) we use its **terminal** `closeadj` as the forward price — capturing the realized outcome, **never dropping the name** (dropping hides the loss and re-introduces survivorship bias). Acquisition → terminal ≈ deal price; **`bankruptcyliquidation` (ACTIONS) → floored at −100%**; other delistings use the real terminal SEP price. Applied in the Step-2 panel rebuild.

## Validation

- **Names per rebalance date:** min 500, median 503, max 505 over 180 monthly rebalances (start 2010-01-29=500, end 2024-12-31=503). Sits near index size with real churn.

- **Survivorship additions:** honest universe has **792 distinct names** vs the current index's 503; **317 names are in the honest panel but NOT in today's index** — exactly the removed/delisted names the flattered panel was missing. Of honest names, **212** are flagged delisted in TICKERS and **21** had a bankruptcy/liquidation.

- **Membership-leakage test:** 0 violations — no name appears before its add or after its remove (must be 0).

- **Independent cross-check:** vs Sharadar's quarterly `historical` membership snapshots (60 in-window dates), mean Jaccard overlap = **1.0000** (1.0 = identical membership).

### Spot-check — real removed names (present in their window, absent after removal)

| Removed date | Ticker | Name | member at remove−1y? | member at remove+1y? |
|---|---|---|---|---|
| 2024-12-23 | AMTM | AMENTUM HOLDINGS INC | no | no |
| 2024-12-23 | QRVO | QORVO INC | yes | no |
| 2024-12-17 | CTLT | CATALENT INC | yes | no |
| 2024-11-21 | MRO | MARATHON OIL CORP | yes | no |
| 2024-09-30 | BBWI | BATH & BODY WORKS INC | yes | no |
| 2024-09-23 | AAL | AMERICAN AIRLINES GROUP INC | yes | no |
| 2024-09-23 | BIO | BIO-RAD LABORATORIES INC | yes | no |
| 2024-09-23 | ETSY | ETSY INC | yes | no |

(Expected pattern: **yes** before removal, **no** after — point-in-time membership.)


> Next (Step 2, after review): rebuild the labeled panel on this universe with delisting-aware forward returns; keep the flattered panel as the 'before' comparison.
