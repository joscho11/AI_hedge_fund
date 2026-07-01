# Congressional-trading signal — Phase A (feasibility, descriptive/in-sample)

> **Exploratory, in-sample, no strategy, no hold-out touched (D9 spirit).** Every entry uses the **disclosure date**, never the trade date (using the trade date is lookahead). Forward returns from archived Sharadar SEP (delisting-aware).

## Data availability — the honest picture

- **Classic free stock-watcher datasets are DEFUNCT:** `housestockwatcher.com` no longer resolves; the Senate GitHub aggregate (`timothycarambat/senate-stock-watcher-data`) is **frozen at 2020-12 and has no `disclosure_date` field** — unusable for the tradeable question. Old S3 endpoints now return 403.

- **Working current free source:** `kadoa-org/congress-trading-monitor` `trades.json` — current, both chambers, **carries `filing_date` (disclosure) + `days_to_file`**. But it is a **rolling recent slice** (filings 2025-12-19→2026-06-26, ~5k rows), **not** full 2012+ history in one file. Its `scatter.json` (26k rows) is a 35-filer curated subset with **no filing date** — can't support this diagnostic.

- **Implication:** this Phase A runs on a **recent ~6-month window** — enough for a *directional* feasibility read, but thin and regime-specific. A robust Phase B needs fuller history: assemble per-filer files, or a **paid API** (Quiver ~1,800 equities from 2016; Apify ~$2.20/1k rows). **No purchase made** — that's your call.

## Clean & match

- Raw rows 5,000 → kept **2,476** tradeable US-common-equity disclosures. Dropped: missing_dates 0, blank_ticker 2,095, non_common_equity(bonds/options/etf/crypto/etc) 429.

- **Match rate to archived SEP prices: 100.0%** (609 distinct tickers). Amount ranges carried as low/high brackets (never point-valued); ownership retained.

## Descriptive splits

- Buy/Sell/Other: {'buy': 1232, 'sell': 1231, 'other': 13}. Chamber: {'house': 1909, 'senate': 246}. Ownership: {'Unknown': 1579, 'DC': 249, 'JT': 209, 'SP': 193, 'Joint': 101, 'Spouse': 92}.
- **Disclosure lag (days trade→disclosure): median 28, mean 62, p90 156; 22% filed >45 days after the trade.** This is the built-in disadvantage — you learn of the trade ~a month later.
- Concentration — top buying members: {'Gilbert Cisneros': 333, 'Julia Letlow': 138, 'Donald J Trump': 102, 'April McClain Delaney': 82, 'David J. Taylor': 63, 'Markwayne Mullin': 62, 'Rohit Khanna': 59, 'Maria Elvira Salazar': 39}.
- Top bought tickers: {'MSFT': 33, 'AAPL': 25, 'JPM': 24, 'WFC': 24, 'AMZN': 22, 'GOOGL': 16, 'META': 16, 'DASH': 16}.

## THE decisive diagnostic — trade-date vs disclosure-date forward return (BUYS)

Buys with a realized forward window: **1,099** (of 1,232 equity buys; the rest are too recent for prices to have realized the horizon).

| Horizon | Entry = TRADE date (hyped, NOT tradeable) | Entry = DISCLOSURE date (the only tradeable one) | Drift captured after lag |
|---|---|---|---|
| 21d | mean +2.20%, median +1.17% (n=1099) | mean +0.80%, median -0.71% (n=1099) | 36% of the trade-date mean |
| 63d | mean +4.42%, median +1.11% (n=930) | mean +2.98%, median +0.35% (n=699) | 67% of the trade-date mean |

## Verdict

- **The 45-day lag substantially erodes the effect, and the only tradeable number is weak.** At 21 days the disclosure-date mean is +0.80% (vs +2.20% from the trade date — ~64% of the effect gone), and the **median is -0.71%** — the *typical* disclosed buy, entered when you could act, is slightly **down**. The mean stays positive only via a few tail winners.

- **The 63-day disclosure-date mean (+2.98%) is almost certainly mostly market beta, not alpha:** this is a recent **rising-market** ~6-month window and the returns here are **not** benchmark-adjusted. A proper test must subtract the market.

- **Read:** on this thin recent sample, following congressional buys *from the disclosure date* does not show a compelling, broad-based edge. **Weak case for a Phase B on free data as-is.** If pursued at all, it would first require (a) market/beta-adjusted returns, (b) genuine multi-year history (not this 6-month slice — paid API or assembling per-filer files), and (c) strict pre-registration. Honest prior (the lag eats most of the edge) is **supported**.

- **Caveats:** recent ~6-month window only; not benchmark-adjusted; concentration in a few prolific members; amounts are brackets; high multiple-comparisons risk for a thin niche signal (we just watched a dev t=3.28 evaporate on a hold-out).


> **STOP for review.** Phase B (one pre-registered disclosure-date-entry hypothesis on a sealed hold-out) is NOT built — its design and whether it's worth the data cost depend on your read of the above.
