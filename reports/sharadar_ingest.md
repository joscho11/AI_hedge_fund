# Sharadar ingest report

_Pulled 2026-06-29T21:34:41+00:00 · Nasdaq Data Link / Sharadar (personal, non-professional license)._

## Point-in-time keying rule (plain English)

Every fundamental figure is tagged with its **`datekey`** — the date it actually became public. A feature built for rebalance date `t` may use only rows with `datekey <= t`, so we never see a number before it was filed. We use only the **as-reported** dimensions (**ARQ / ART / ARY**); the most-recent dimensions (MRQ/MRT/MRY) retroactively rewrite past periods with later restatements and are **never used** — that would be lookahead.

## Tables pulled

| Table | Rows | Date coverage | Notes |
|---|---|---|---|
| SF1 | 3,195,411 | 1990-06-06–2026-06-26 (datekey) | dimensions: ARQ, ART, ARY, MRQ, MRT, MRY |
| TICKERS | 62,302 | — | delisted names: 31349 |
| SP500 | 59,164 | 1957-03-04–2026-06-27 | historical constituents (cached for the survivorship-free re-run) |
| SEP | 46,114,536 | 1997-12-31–2026-06-29 | daily prices incl. delisted |

**SF1 as-reported rows (the only ones we query): 1,546,079** of 3,195,411 total (48%). Distinct tickers: 17,768.

## Leakage guard (tested)

`tests/test_sharadar_pit.py`: `SharadarProvider.get_facts` refuses MR* dimensions, and a restated value (a newer `datekey`) does not change any feature at an earlier `t` — the as-of selector returns the value known *then*, not the restatement.
