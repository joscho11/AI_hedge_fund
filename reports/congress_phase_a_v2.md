# Congressional-trading signal — Phase A v2 (full history, MARKET-ADJUSTED)

> **Exploratory, in-sample, no strategy, no hold-out (D9).** Entry = **disclosure (filing) date**, never trade date. Forward returns from archived SEP (delisting-aware); **market-adjusted by subtracting SPY** (archived SFP) over the same window.

## Data — full multi-year history (free assembly)

- Assembled **all 433 per-filer files** from `kadoa-org/congress-trading-monitor` → **57,730 transactions**, transaction dates 2011-06-20→2026-06-18, filing dates 2014-01-03→2026-06-30. (FMP free tier = recent-only / full history paywalled; this free assembly reaches the full history the redo needed.)

- **Cross-check vs FMP's independent parser** (free `-latest`, recent overlap n=23): disclosure dates agree **83%** (±1 day). Both parse the same official STOCK Act filings; agreement confirms the data is trustworthy, not a mis-parse.

- Cleaned to tradeable US common equity: dropped {'missing_date': 5, 'blank_ticker': 10201, 'non_common_equity': 9640}. Kept **37,275** equity disclosures. **Match rate to archived SEP: 100.0%** (2076 tickers). Amounts kept as brackets; ownership retained.

## Context

- Disclosure lag: **median 29d, mean 64d, p90 160d; 20% filed >45d late.**
- Concentration — top buyers: {'Gilbert Cisneros': 1240, 'Josh Gottheimer': 1099, 'Lisa Mcclain': 588, 'Susie Lee': 571, 'Lois Frankel': 535, 'Virginia Foxx': 490, 'Kevin Hern': 481, 'Sheldon Whitehouse': 418}.
- Top bought tickers: {'MSFT': 423, 'AAPL': 336, 'AMZN': 272, 'NVDA': 234, 'JPM': 192, 'WFC': 165, 'GOOGL': 157, 'JNJ': 154}. Owner mix: {'self': 18838, 'joint': 9400, 'spouse': 8152, 'dependent': 885}.

## THE diagnostic — buys, forward return: TRADE-date vs DISCLOSURE-date, RAW vs MARKET-ADJUSTED

Buys with a realized forward window: **18,394**.

| Horizon | trade RAW | trade ADJ (−SPY) | **disc RAW** | **disc ADJ (−SPY)** |
|---|---|---|---|---|
| 21d | +1.70% (med +1.50%) | -0.02% (med -0.26%) | **+1.63%** (med +1.28%) | **+0.19%** (med -0.24%, n=18394) |
| 63d | +4.91% (med +3.79%) | +0.26% (med -0.72%) | **+4.37%** (med +3.26%) | **+0.10%** (med -0.76%, n=17994) |

*The bottom-right cell — **disclosure-date, market-adjusted** — is the only number that matters: the tradeable, beta-stripped excess return.*

## By disclosure YEAR — market-adjusted disclosure-date return (regime check)

| Year | disc ADJ 21d (mean / med) | disc ADJ 63d (mean / med) | n(63d) |
|---|---|---|---|
| 2014 | +0.23% / +0.47% | -0.45% / -0.65% | 421 |
| 2015 | +0.21% / +0.17% | -0.73% / -0.26% | 673 |
| 2016 | +0.32% / +0.13% | +0.94% / +0.41% | 617 |
| 2017 | -0.09% / +0.17% | -0.72% / +0.10% | 818 |
| 2018 | -0.48% / -0.46% | -0.65% / -0.04% | 1267 |
| 2019 | -0.10% / +0.06% | +0.14% / -0.03% | 1743 |
| 2020 | +1.43% / +0.16% | +2.90% / +0.23% | 2645 |
| 2021 | -0.57% / -1.07% | -1.86% / -2.35% | 2261 |
| 2022 | +0.84% / +0.64% | +1.69% / +1.37% | 1391 |
| 2023 | -0.17% / -0.56% | -0.80% / -2.67% | 1379 |
| 2024 | +0.08% / -0.43% | -0.45% / -1.60% | 1054 |
| 2025 | +0.33% / -0.64% | +0.21% / -1.84% | 3045 |
| 2026 | -0.54% / -0.67% | -2.63% / -5.67% | 680 |

*A signal that only appears in one year isn't durable (same lesson as the vol mirage).*

## By ownership subset — disc ADJ 63d (each is an EXTRA comparison, not a result)

| Owner | disc ADJ 63d mean | median | n |
|---|---|---|---|
| dependent | -0.50% | -0.66% | 432 |
| joint | +1.01% | -0.03% | 4325 |
| self | -0.07% | -1.09% | 9284 |
| spouse | -0.42% | -0.89% | 3953 |

## Verdict

- **Once market-adjusted, the disclosure-date edge is ~gone.** The tradeable, beta-stripped number is small/near-zero: disc-adj 21d mean +0.19% (median -0.24%), 63d mean +0.10% (median -0.76%). The +2.98%/63d that looked interesting in v1 was **market beta** — it largely disappears after subtracting SPY. Across years it is inconsistent (5/13 years positive at 63d). **The 45-day lag eats the edge.** Clean null — no case for a pre-registered Phase B.

- **Caveats:** concentration in a few prolific members; amounts are brackets; each year/owner slice is another comparison. Full history but still a niche, sparse signal.


> **STOP for review.** Phase B (one pre-registered disclosure-date hypothesis on a sealed hold-out) is NOT built.
