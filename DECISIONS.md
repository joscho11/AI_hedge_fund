# Design Decisions

Append-only log of design choices and their rationale. Newest at the bottom.

---

## D1 — Data stack: free-only (yfinance + EDGAR + FRED), accept & quantify survivorship
**Date:** 2026-06-27

- **Prices:** yfinance (raw OHLCV + split/dividend-adjusted + corporate-action tables).
- **Fundamentals:** SEC EDGAR XBRL `companyfacts`, keyed by **filing date** (`filed`), all vintages
  retained so the as-of selector can pick `max(filed) <= t - lag`.
- **Macro:** FRED, restricted to real-time / unrevised series (yields, spreads, VIX-like). Revised
  economic series (GDP, unemployment) require ALFRED vintages and are excluded unless explicitly wired.

**Rationale / caveat.** EDGAR makes fundamentals point-in-time and delisting-inclusive (dead filers'
filings persist). yfinance prices are **survivors-biased** — no reliable delisted-ticker history and
no free point-in-time S&P 500 membership. We accept this for the learning build, **quantify** the
likely return inflation in `LEAKAGE_AUDIT.md`, and architect the provider interface so a paid
upgrade (Sharadar SEP+SF1) is a drop-in that never touches modeling code.

## D2 — Universe / rebalance / horizon
**Date:** 2026-06-27

S&P 500 (liquid large-cap) with per-date liquidity filters (`min_price`, 20-day median dollar
volume). Monthly rebalance. Forward-return horizon **H = 63 trading days** (~1 quarter), matching a
fundamentals-driven signal cadence and keeping turnover/cost drag sane.

## D3 — Target definition + **frozen** primary-target selection rule
**Date:** 2026-06-27

Label module emits three columns per (ticker, rebalance date):
- `fwd_ret_raw` — raw H-day forward return. **Diagnostics only; never a training target.**
- `fwd_ret_excess_median` — forward return minus universe-median forward return.
- `fwd_ret_excess_sector` — forward return minus SIC-sector-median forward return.

Sector classification comes free from the **EDGAR SIC code** per filer (coarser than GICS; coverage
reported).

**Frozen selection rule (committed before any model is fit; never re-evaluated against the hold-out):**

> Primary target = `fwd_ret_excess_sector` **iff** (a) sector classification covers ≥ 95% of
> universe-months **and** (b) the sector-neutral target's mean IC information ratio on the
> walk-forward **validation** folds ≥ that of `fwd_ret_excess_median`. Otherwise primary =
> `fwd_ret_excess_median`. Selection uses validation folds only — the Phase-5 hold-out is untouched
> until the single final evaluation.

## D9 — Full-universe re-run confirms (strengthens) the Phase 2 conclusions
**Date:** 2026-06-27

Scaled the validated Phase 1 pipeline to the full universe (**500/503 current S&P 500 names**,
80,676-row panel) and re-ran the baselines unchanged. No prior call revised. Findings:
- **Survivorship drift HELD:** equal-weight − SPY CAGR +3.0% (sample) → +3.5% (full).
- **Momentum is NOT a robust signal — conclusion strengthened.** With full breadth the mean IC fell
  to 0.004 (t=0.28), months-positive to 50.3% (coin flip), and decile monotonicity went negative
  (−0.10, U-shaped) — i.e., ~zero cross-sectional ranking power.
- **Methodological lesson (recorded for all later phases):** the top-decile momentum *portfolio*
  Sharpe rose to 1.17 (above equal-weight 1.09) even as its *IC collapsed*. A portfolio Sharpe edge
  with no significant IC beneath it is treated as fragile/period-specific, not alpha. **Going
  forward, no strategy is accepted on portfolio performance alone without IC support + out-of-sample
  confirmation.** This is the project's core anti-overfitting guardrail made concrete.

## D7 — Value baseline deferred from Phase 2 to Phase 3
**Date:** 2026-06-27

The fourth baseline (simple value) is **deferred to Phase 3**. A clean point-in-time valuation ratio
(earnings yield / P/S) requires TTM aggregation of quarterly fundamentals + shares-outstanding
alignment, all keyed off the EDGAR `filed` date — i.e., the as-of feature machinery that Phase 3
owns. Implementing it hastily in Phase 2 risks a restated or leaky metric, which would violate the
project's first rule. It is stubbed (`baselines/signals.py::simple_value_stub`, raises
NotImplementedError with a pointer here). Baselines 1–3 (SPY, equal-weight, 12-1 momentum) ship in
Phase 2. Per the kickoff prompt's own guidance ("If a clean as-of-t pull isn't quick, defer ... and
stub it with a clear TODO rather than risk a leaky or restated metric").

## D8 — Backtest holding return ≠ label horizon
**Date:** 2026-06-27

The backtest earns **realized rebalance-to-next-rebalance (~monthly) returns** computed from
adjusted closes (`backtest/engine.py::holding_period_returns`), kept entirely separate from the
**63-day label** used for IC/quantile evaluation. Cost model: one-way rate
`(commission_bps + slippage_bps)/1e4` charged on traded fraction `Σ|Δw|` after drifting prior
weights by realized returns (no charge for passive drift). This separation keeps Phase 4 walk-forward
CV (which must purge/embargo on the 63-day horizon) correct and independent of rebalance cadence.

## D5 — Universe is STAGED: Option 1 now, migrate to Option 3 after Sharadar
**Date:** 2026-06-27

Start on **S&P 500, monthly, H=63** (Option 1) to get a clean validated pipeline with the fewest
data headaches and prove we can beat baselines on the hardest (most picked-over) universe. **Migrate
to the broader ~1000–1500 mid/large universe (Option 3) later — at the same time we add Sharadar**,
so the broader universe's delisting realism is genuine rather than just more noise + XBRL tag-drift
debugging. Rationale: Option 3's survivorship benefit only materializes once we have point-in-time
data including delisted names; on the free yfinance stack a 1500-name universe is *itself* built
from today's survivors, so we'd pay the cost without the benefit (compounding two hard problems).

**Watch on migration:** information coefficient will likely DROP on the honest delisted-inclusive
universe; that drop is the real measure of how much S&P-500 backtest was survivorship flattery.

### Known, logged bias (free stack): CURRENT S&P 500 membership used as the universe
Free data cannot reconstruct historical S&P 500 membership, so the prototype uses **today's**
constituents at every historical rebalance date. This is a real lookahead/survivorship bias
(today's members are disproportionately past winners; names that were dropped/delisted are absent).
We log it explicitly here and in LEAKAGE_AUDIT.md and fix it with Sharadar's historical constituent
lists later — we do NOT pretend it is solved.

## D6 — Sector classification source (prototype): Wikipedia GICS sector
**Date:** 2026-06-27

For the sector-neutral target we use the **GICS sector** from the same Wikipedia S&P 500 table that
supplies membership (cleaner/more standard than SIC). Same current-snapshot caveat as D5 (current
sector, not point-in-time). EDGAR SIC remains available via `company_ref` as a cross-check/fallback.

## D4 — Fundamental availability lag
**Date:** 2026-06-27

Fundamentals usable at `filing_date + 1 trading day` (`availability.fundamental_lag_days = 1`) to
avoid same-day-filing lookahead. Amended filings (10-K/A) are treated as new vintages; the as-of
selector takes the latest `filed <= t`, i.e., the value *as known then*, not the restated value.
