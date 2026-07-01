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

## D20 — Full Sharadar bundle archived locally (subscription cancellable)
**Date:** 2026-06-30

Before cancelling Nasdaq Data Link, the **entire entitled Sharadar Core US Equities Bundle** was
banked to local disk at `data_archive/` (gitignored; local, non-cloud): raw bulk-export zips
(source of truth) under `sharadar_raw/<T>/` + ZSTD parquet under `sharadar_parquet/<T>.parquet`, with
per-table provenance. **13 tables, all complete & spot-checked, ~5.6 GB total** (SF1 3.2M, SF2 11.6M
insiders, SF3 46.1M 13F holdings, SF3A/SF3B aggregates, SEP 46.1M, SFP 15.3M funds, DAILY 39.9M
metrics, ACTIONS, EVENTS 2.5M, SP500, TICKERS, INDICATORS dictionary). Manifest +
**SAFE-TO-CANCEL=TRUE** verdict + cancellation checklist in `reports/sharadar_full_archive.md`
(scripts: `archive_sharadar.py` resumable pull, `verify_archive.py` manifest). SF1 & SEP raw re-pull
skipped (parquet-only) per directive. Unlocks future ideas offline forever (PEAD via EVENTS/SF1,
insider clusters via SF2, institutional-ownership via SF3, benchmarks via SFP, fast valuations via
DAILY). **Backup caveat:** archive is the only copy (gitignored, un-redownloadable post-cancel) →
copy `data_archive/` to a second disk.

## D19 — Phase 5 modeling PRE-REGISTRATION (small-cap arena; locked before modeling)
**Date:** 2026-06-30

Re-registration for the small-cap universe. **Unchanged from D16:** the two models (Ridge,
alpha∈{1,10,100,1000}; LightGBM, num_leaves{15,31}×min_child_samples{100,300}, lr0.03, n_est400,
ff0.7, ss0.8, seed7), nested inner walk-forward HP tuning, purged/embargoed EXPANDING walk-forward
(min_train 36m, 6 folds, embargo=horizon=63td), the 50 cross-sectional `_z` features (+context
conditioning for the GBT), trainable targets {excess_median, excess_sector} (raw=diagnostic), and the
**frozen selection rule: IC-IR(folds) → %positive folds → mean IC → sector-neutral tiebreaker**.
Verdict metric = mean OOS IC + IC-IR + t-stat + %positive folds.

**New locked items for this arena:** (a) the small-cap universe definition (D18); (b) the
**{25,30,50,100} bps cost sweep with the ≥50 bps verdict bar** carried into any backtest — an edge
that needs <50 bps to look good is a cost artifact. (c) Decomposition must additionally check a
**size-tilt** (corr of model score with market cap), since "edge" in a small-cap universe can be a
pure small-minus-big bet. Dev = ≤2021-12; 2022+ hold-out sealed until the Step-4 gate. Stopping rule:
this IS the whole experiment (2 models × 2 targets); no post-hoc additions. Second null = success.

## D18 — Phase 5 small/mid-cap universe: PRE-REGISTRATION CANDIDATES (pending Joseph's approval)
**Date:** 2026-06-30

Second arena (less-efficient small/mid-cap US equities). Same honest pipeline; NEW universe + fresh
sealed 2022+ hold-out. **Logged as a CONTINUATION of the same experiment program** — any positive
result must be read against the multiple-arenas selection effect (this is arena #2).

**APPROVED & FROZEN 2026-06-30** (Joseph): cap band, liquidity floors, common-stock scope as below;
cost changed to the {25,30,50,100} bps sweep with the ≥50 bps verdict bar.

Candidates (to lock on approval):
- **Scope:** domestic common stock only — Sharadar `category ∈ {"Domestic Common Stock",
  "Domestic Common Stock Primary Class"}`; exclude Secondary Class, ADR, Canadian, Preferred,
  Warrant, Unit, ETF/ETN/ETD/ETMF, CEF, IDX, Institutional. **Delisted-inclusive from the start.**
- **PIT market-cap band:** at each rebalance t, `market_cap = closeunadj(t) × sharesbas(ARQ,
  datekey≤t)`. Band = **[$300M, $5B]**. Additionally **exclude any concurrent S&P 500 member** at t
  (the large-cap arena already tested) to keep the two universes disjoint. Names lacking as-of-t
  shares (no ARQ sharesbas with datekey≤t) can't get a cap → excluded that date (documented).
- **Liquidity (non-negotiable, the honesty guard):** raw price `> $5` AND 20-day median dollar
  volume `> $1M/day`, computed as-of t on SEP raw prices. Without these the backtest "trades" names
  that don't trade — the classic small-cap illusion.
- **Transaction costs (FROZEN as a sweep, not a point estimate):** pre-registered one-way sensitivity
  sweep **{25, 30, 50, 100} bps**. **Verdict bar: an edge must survive at ≥ 50 bps to count.** A
  result that only works at the optimistic (25–30 bps) end is judged a **cost artifact, not an edge**.
  (Small-cap spreads/impact are wide; 6 bps as used for large-caps would be dishonest here.)
- **Rebalance / horizon:** unchanged — monthly, 63-trading-day forward label.
- **Entity key:** ticker (recycling empirically 0 even here), permaticker carried + date-bounded
  SEP/SF1 lookups as defense-in-depth.
- **Missing fundamentals:** small names have spottier SF1 → features NaN where missing, never filled;
  coverage reported per family in Step 2.

Membership is defined purely by these as-of-t filters (no index table); leakage test = a name enters
the band only when its as-of-t cap/liquidity qualify it.

## D17 — Lesson (future pre-registrations only): IC-IR can mask fold concentration
**Date:** 2026-06-30

The frozen D16 rule selected `lgbm × excess_median` (IC-IR 0.76) over `ridge × excess_sector` (which
had better fold-consistency, 67% positive folds). The selected combo's dev IC was concentrated in
2019-2021 with only 50% positive folds — i.e., a high IC-IR (mean/std across folds) can be produced
by a few large-magnitude folds and still mask poor directional consistency. **We honored the frozen
rule (no switching after seeing results).** Lesson for FUTURE pre-registrations: rank by % positive
folds (and/or a sub-period stability check) at least co-equally with IC-IR. This note changes nothing
in Phase 4.

## D16 — Phase 4 PRE-REGISTRATION (locked before any model trains)
**Date:** 2026-06-29

Everything below is fixed in advance. No post-hoc additions to chase a number; every run logged in
EXPERIMENTS. The 2022+ hold-out is touched exactly once, after the model is frozen (Step 3).

**Data split.** Development = honest panel (`panel_honest.parquet`) from start → **2021-12**.
Hold-out = **2022-01-01 → end** (config `holdout_start`), untouched until the single final eval.

**CV scheme.** Purged, embargoed **EXPANDING** walk-forward (`src/cv/walk_forward.py`):
min_train = 36 months, **n_folds = 6** over the dev period. Purge+embargo rule: keep a train sample
only if `label_end(d) = d+63td ≤ offset(test_start, −63td)` (embargo_days = horizon = 63), so no
train label window reaches within 63 trading days of a test block. Validated by
`tests/test_walk_forward_cv.py` (boundary guarantee + noise≈0 + signal-recovery + future-peek≈1).

**Feature set.** The 50 cross-sectional, per-date-z-scored features (`<feat>_z`): momentum 8 +
valuation 12 + quality 22 + fundamental_momentum 8. Missing z imputed to 0 (cross-sectional mean;
leak-free constant). The GBT additionally receives the **context conditioning** inputs (sector_id +
term_spread/credit_spread/vix/mkt_ret_63d) as native features; the linear model uses the 50 only.

**Model set (exactly two).**
- **Ridge** (linear, L2). Grid: `alpha ∈ {1, 10, 100, 1000}`.
- **LightGBM** (GBT). Grid: `num_leaves ∈ {15, 31}` × `min_child_samples ∈ {100, 300}`;
  fixed `learning_rate=0.03`, `n_estimators=400`, `feature_fraction=0.7`, `subsample=0.8`,
  `subsample_freq=1`, `reg_lambda=1.0`, `random_state=7`.
Hyperparameters tuned by **nested/inner walk-forward** on the train block of each outer fold only —
never on the hold-out, never on outer-test.

**Trainable targets.** `fwd_ret_excess_median` and `fwd_ret_excess_sector`. `fwd_ret_raw` is
diagnostic only, never a training target.

**Primary metric & selection rule (frozen; selection rewards cross-fold CONSISTENCY, not one lucky
fold).** Reported verdict metric per combo = mean OOS IC, **IC-IR** (mean OOS IC / std across folds),
t-stat, and **% positive folds**. **Selection rule (in order):** (1) **IC-IR**, (2) **% positive
folds**, (3) **mean OOS IC** (secondary), (4) **sector-neutral (`excess_sector`) tiebreaker** when
within noise of `excess_median` (the more honest stock-selection measure; per frozen target rule D3).
Decile monotonicity + top−bottom spread and the costed backtest are SECONDARY and not trusted without
IC support (D9).

**Secondary backtest (reported, not used for selection).** Long top-decile EW and long-short
(top−bottom decile) EW, monthly, 6 bps one-way, on the honest panel with delisting-aware holding
returns, vs SPY + equal-weight. Plus a regime/sub-period breakdown and an explicit check of whether
any edge is driven by the value short (given value's negative sign).

**Stopping rule.** The above IS the complete experiment: 2 models × 2 trainable targets (+ their
fixed inner-CV grids) = the entire run. No additional models, features, or targets will be added to
improve a result. A small/null OOS IC is the expected and acceptable outcome and will be reported as
plainly as a positive one.

## D15 — Remaining feature families (quality, fundamental momentum, context) on the honest universe
**Date:** 2026-06-29

Three more FeatureFamily instances, all PIT (datekey<=t, AR* only), built on the honest panel:
- **quality** (`src/features/quality.py`): profitability (roe/roic/roa, gross/op/net/ebitda margin),
  balance sheet (debt-to-equity, current ratio, interest coverage), cash (FCF yield = ART fcfps /
  price-at-t, FCF margin), + net-margin stability; level + sector-relative. Missing rules: ROE /
  debt-to-equity NaN when equity<=0; interest coverage NaN when intexp<=0; op/FCF margin NaN when
  revenue<=0 (never a huge number).
- **fundamental_momentum** (`src/features/fundamental_momentum.py`): strict **two-point as-of**
  YoY growth (revenue/EPS/GP/FCF), acceleration (ΔYoY q/q), margin trends — both endpoints taken
  as-of their date, so a later restatement of either can't change an earlier-t value (tested). YoY
  NaN when the year-ago base<=0. **Analyst estimate revisions are intentionally ABSENT** (SF1 is
  reported fundamentals, not estimates); no proxy fabricated — noted in the report.
- **context** (`src/features/context.py`): sector_id (cross-sectional categorical) + macro regime
  (FRED term spread / credit spread / VIX / trailing market return). Macro is **date-level
  conditioning**, constant across names → standalone cross-sectional IC is ~0 by construction; this
  family **overrides normalization (stored raw) and reports NO cross-sectional IC** (`cross_sectional
  = False`). Conditioning for model interactions, not a ranking signal.

All diagnostic ICs are in-sample/exploratory; verdicts wait for Phase-4 purged/embargoed OOS (D9).

## D13 — Honest universe construction + delisting-return rules
**Date:** 2026-06-29

Point-in-time, delisting-inclusive S&P 500 (`src/universe/honest_sp500.py`, `src/labels/honest_panel.py`):
- **Membership** = Sharadar SP500 add/remove intervals (`added <= t < removed`; re-additions; a
  `removed` with no prior add opens at -inf). Validated: **mean Jaccard 1.0000** vs Sharadar's
  independent quarterly `historical` snapshots; **0 membership-leakage** violations.
- **Entity key:** ticker (Sharadar ticker namespace is non-recycled here — 0/31,467 → >1 permaticker;
  Joseph signed off), permaticker carried + SEP/SF1 lookups date-bounded as defense-in-depth.
- **Delisting returns (both label AND backtest holding return are delisting-aware):** forward/holding
  return on SEP `closeadj`; if a name delists inside the window, use its TERMINAL price — **never
  NaN-drop / never silent 0** (that would re-hide the loss). Only `bankruptcyliquidation` (ACTIONS)
  floored at −100%; acquisitions/other delistings use the real terminal SEP price.
- Honest results are the dashboard DEFAULT; flattered preserved at `data_cache/results_flattered/`
  and `panel_500tickers.parquet` as the labeled 'before'.

## D14 — Honest re-run findings (survivorship removed): what was real vs artifact
**Date:** 2026-06-29

First out-of-the-survivorship-bubble read (still in-sample; not yet Phase-4 OOS):
- **The ~3.5pp/yr equal-weight−SPY drift collapses to −0.9pp** — confirmed survivorship bias, not skill.
- **The vol_6m/vol_12m "signal" was a SURVIVORSHIP ARTIFACT** — IC +0.045 (t3.49) → −0.009 (t−0.73);
  it disappears once delisted names are included. Lesson reinforced (D9): an in-sample significant IC
  on a biased universe is a prime false positive.
- **Inverted value premium is GENUINE here** (not bias): earnings_yield IC stays negative and
  strengthens (t−1.93 → −3.64); cheap stocks genuinely underperformed in this 2010s sample.
- **Momentum stays null.** None of these count as edge until they survive Phase-4 purged/embargoed OOS.

## D11 — Sharadar adopted as the point-in-time fundamentals source
**Date:** 2026-06-29

Data-source decision finalized: **Sharadar** (Nasdaq Data Link, personal/non-professional license).
Ingested full history of SF1 (fundamentals), TICKERS (reference/sector/delisted), SP500 (historical
constituents) to the parquet cache; SEP deferred (multi-GB, only for the survivorship re-run).
`SharadarProvider` sits behind the existing `FundamentalsProvider` interface so feature families are
source-agnostic. **PIT rules (load-bearing):** key on SF1 `datekey` (availability date); a feature
at `t` uses only `datekey <= t`; **as-reported dimensions ARQ/ART/ARY only** — MR* (restatement-
backfilled) are refused by the provider, as using them would leak. EDGAR provider retained as a
fallback/cross-check. Key loaded from `.env` (gitignored) via `src/utils/secrets.py`.

## D12 — Valuation family construction + value-baseline metric
**Date:** 2026-06-29

Valuation features = {earnings_yield, sales_yield, ev_ebitda, book_to_price} × {level, sector-
relative (vs as-of TICKERS sector median), own-history (z vs trailing 5y)}. **Numerator = price at t
(`close_raw`); denominator = fundamental as-of-t** (flows from ART/TTM, stocks from ARQ). Negative/
zero earnings, sales, book, or EBITDA → feature **undefined (NaN), never 0**. The deferred (D7) value
baseline uses **earnings yield** (single robust, capital-structure-light, canonical value ratio);
"cheapest decile" = highest earnings yield, long-only EW through the existing Phase-2 harness.

**Finding (honest, in-sample):** on the survivorship-flattered current-S&P-500 / 2010s sample the
**value premium is inverted** — earnings_yield and book_to_price have *negative* IC (cheap stocks
underperformed; the value drought + growth-winner survivorship). The value baseline trails equal-
weight. Sign may differ on point-in-time, delisting-inclusive data. Per D9, not trusted until OOS.

## D10 — Feature-family template (Phase 3 pattern)
**Date:** 2026-06-28

All feature families subclass `src/features/base.py::FeatureFamily` and implement only
`compute_raw` (long [date,ticker,<raw cols>], strictly as-of-t). Shared in the base:
**per-date** cross-sectional normalization (winsorize 1/99 → z-score + percentile rank, **never
pooled across dates**); join to the panel keys; a `quality_report` (coverage, missing rate,
per-feature as-of timing + missing rule from `FeatureSpec`, and diagnostic per-feature IC vs all 3
targets); and feature-store IO that writes `data_cache/features/<name>.parquet` + a provenance
sidecar (source panel path/rows/names, specs, build time) — mirroring the Phase-2 results
provenance so features can't silently desync from a panel.

**Provider-agnostic by design:** `compute_raw` takes a `providers` dict (momentum reads a prices
DataFrame; fundamental families will read a `FundamentalsProvider`). The pattern assumes no specific
source, so the **EDGAR-vs-Sharadar decision never touches it** — fundamental families plug in behind
the existing interface unchanged. Missing data is never forward-filled (each feature declares its
rule). First instance: `momentum` (8 price-only trailing features).

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
