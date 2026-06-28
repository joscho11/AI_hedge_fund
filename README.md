# equity-alpha

A rigorous, honestly-validated **cross-sectional US equity ranking system**. Each rebalance
date it scores every stock in the universe by predicted forward return, ranks them, backtests
trading policies on those rankings, and reports performance **gross and net of realistic costs**
against honest baselines.

> The deliverable is a *correct, well-validated* system and an honest read on where edge exists —
> not a system that maximizes backtest returns. A backtest that looks amazing is treated as a
> likely data leak until proven otherwise.

## Hard constraints (violating any invalidates the project)

1. **No lookahead bias.** Every feature at time `t` uses only information public at `t`.
   Fundamentals are lagged to their SEC **filing date**, never the fiscal period-end.
2. **No survivorship bias** *(see the caveat below — the free data stack cannot fully honor this)*.
3. **Strict temporal validation.** Purged, embargoed walk-forward CV. Never random-split time series.
4. **No p-hacking.** Final hold-out touched exactly once. Every variant logged in `EXPERIMENTS.md`.
5. **Cost-aware evaluation.** Every number reported gross *and* net of cost + slippage; turnover reported.
6. **Incremental, validated builds.** Each phase ships a tested artifact and stops for review.

## Locked decisions (see `DECISIONS.md` for full rationale)

| Decision | Choice |
|---|---|
| Data stack | **Free-only**: yfinance (prices) + SEC EDGAR (point-in-time fundamentals) + FRED (macro). Survivorship bias accepted & quantified, not hidden. Provider interface allows a later drop-in upgrade (Sharadar SF1/SEP). |
| Universe | S&P 500, liquid large-cap, with liquidity filters |
| Rebalance / horizon | Monthly rebalance, **H = 63** trading-day forward return |
| Target | Label module emits **three** columns — `fwd_ret_raw` (diagnostic only), `fwd_ret_excess_median`, `fwd_ret_excess_sector`. Primary chosen by a **frozen rule** (see `DECISIONS.md`), on validation folds only. |

### ⚠️ Free-stack survivorship caveat
EDGAR retains delisted filers' fundamentals, so fundamentals can be genuinely point-in-time and
delisting-inclusive. **Prices cannot**: yfinance does not reliably serve delisted/acquired tickers,
and there is no free point-in-time S&P 500 membership. So the *price* universe is survivors-biased
regardless of how clean the timing logic is. `LEAKAGE_AUDIT.md` quantifies the likely inflation.
The honest fix is Sharadar SEP+SF1 (~$30–50/mo) — the provider interface is built so that swap
never touches modeling code.

## Phased plan

- **Phase 0 — Scaffolding & data layer.** *(current)* Repo, config, provider interfaces,
  yfinance + EDGAR + FRED clients, parquet cache, corporate-action handling, tests, and a
  validation spot-check → leakage/timing audit note.
- **Phase 1 — Universe & target construction.** Dated universe + liquidity filters; forward &
  excess-return targets; tests proving no future data bleeds into `t`.
- **Phase 2 — Baselines.** Buy-and-hold SPY, equal-weight, 12-1 momentum, simple value — net of costs.
- **Phase 3 — Features.** Momentum, fundamental level/quality, fundamental momentum, valuation,
  (estimate revisions if available), sector/macro context — each with explicit as-of timing.
- **Phase 4 — Modeling & walk-forward validation.** Linear + GBT under purged/embargoed CV;
  IC stats, quantile spreads, in-vs-out-of-sample gap.
- **Phase 5 — Strategy backtest & exit policies.** Portfolio construction, costs, exit rules,
  regime breakdown; one-time hold-out touch.
- **Phase 6 (optional) — Paper trading.** Wire the final model to Alpaca paper trading.

## Layout

```
config.yaml          # all tunables; no magic numbers in code
src/
  data/              # interfaces, types, cache, corporate actions, providers/
  universe/          # Phase 1
  labels/            # Phase 1
  features/          # Phase 3
  models/            # Phase 4
  backtest/          # Phase 2 + 5
  eval/              # IC, quantiles, regimes
  utils/             # config loader, calendars
tests/               # mirrors src/; leakage tests from day 1
DECISIONS.md         # design choices + rationale
EXPERIMENTS.md       # every feature/model variant (multiple-comparisons ledger)
LEAKAGE_AUDIT.md     # per-source as-of timing audit
```

## Setup

```bash
python -m venv .venv
. .venv/Scripts/activate        # Windows; use .venv/bin/activate on mac/linux
pip install -r requirements.txt
pytest -m "not network"          # offline unit/leakage tests
pytest -m network                # live-API smoke checks (rate-limited)
```

Environment: Windows 11, Python 3.11.
