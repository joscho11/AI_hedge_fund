# Phase 0 Leakage & Timing Audit

Per-source as-of timing audit and the survivorship-bias quantification, validated against live data
on 2026-06-27 via `scripts/phase0_spotcheck.py`. Update this note whenever a provider changes.

## Summary verdict
- **Fundamental timing (lookahead): controlled.** EDGAR facts are keyed by `filed`, the as-of
  selector enforces `max(filed) <= t - lag`, and this was verified on live AAPL data (the FY2022
  10-K, filed 2022-10-28, is invisible at `as_of 2022-10-01` and visible at `2022-12-01`).
- **Survivorship (prices): NOT controlled on the free stack** — confirmed, and quantified below.
  This is the project's load-bearing caveat until/unless we upgrade the price source.

---

## 1. Prices (yfinance) — raw vs adjusted
Verified both series are returned and behave correctly:
- **AAPL** 2023-01..05: `max|close_raw - close_adj| = 2.64` (nonzero — dividend back-adjustment
  present, as expected for a dividend payer).
- **RKLB** same window: `max|raw-adj| = 0.00` (no dividends/splits — correct).

**Contract enforced in code** (`corporate_actions.py`): `close_adj` for return computation only;
`close_raw` for any price-LEVEL feature read as-of `t` (valuation ratios, 52wk-high distance,
dollar-volume liquidity). Rationale: yfinance `Adj Close` is re-adjusted to *today* on every new
split/dividend, so its absolute level at `t` is not what was observed then; only adjacent-ratio
returns are valid.

## 2. Fundamentals (EDGAR) — filing-date lag & reconciliation
AAPL annual revenue (`RevenueFromContractWithCustomerExcludingAssessedTax`), reconciled to reported
10-K figures:

| Fiscal period end | Value ($B) | First filed |
|---|---|---|
| 2022-09-24 | 394.33 | 2023-11-03* |
| 2023-09-30 | 383.28 | 2023-11-03 |
| 2024-09-28 | 391.04 | 2024-11-01 |

Matches Apple's reported FY2022/23/24 revenue ($394.3B / $383.3B / $391.0B). All 10-K facts are
dated **after** their fiscal period end.

\* **Comparative-figures subtlety (documented, not a bug):** the same period's value reappears in
later filings as a prior-year comparative (e.g., FY2022 revenue is restated as a comparative in the
FY2023 and FY2024 10-Ks). A naive `median(filed - period_end)` therefore reads ~398 days, which is
an artifact of comparatives, **not** the true first-disclosure lag (~34 days for AAPL: late-Sept
year-end → late-Oct/early-Nov 10-K). The as-of selector is unaffected because it takes the latest
`filed <= t`; feature code that wants "first disclosure" should use `min(filed)` per `period_end`.

## 3. As-of selector — live no-leakage proof (AAPL)
| `as_of` date | latest visible filing | RevenueFromContract... ($B) |
|---|---|---|
| 2022-10-01 | 2022-07-29 (Q3 10-Q) | 82.96 (quarterly) |
| 2022-12-01 | 2022-10-28 (FY22 10-K) | 394.33 |
| 2023-12-01 | 2023-11-03 (FY23 10-K) | 394.33 |

The FY2022 10-K (filed 2022-10-28) is correctly **invisible** one month before it was filed — no
lookahead. (The stale `Revenues` tag value of 265.6B that also appears is the annual-vs-quarterly /
deprecated-tag issue; period-type disambiguation is a feature-layer concern — see
`interfaces.py::FundamentalsProvider.as_of` docstring and DECISIONS D3.)

## 4. Survivorship gap (the big one) — quantified
Probed two stocks that were public and then delisted, via yfinance over 2015–2024:

| Ticker | yfinance price rows | Reality |
|---|---|---|
| **SIVB** (SVB Financial) | **0** | S&P 500 member for years; failed/bankrupt Mar-2023. yfinance returns **nothing**. |
| **BBBY** (Bed Bath & Beyond) | 2515 (through 2024-12-30) | Delisted ~2023, yet "data" extends into 2024 — stale / ticker-reuse artifact. |

**Two distinct free-stack failures, both confirmed:**
1. **Disappeared names** (SIVB): a former index member is entirely absent → any universe assembled
   from yfinance is survivors-only.
2. **Zombie/reused tickers** (BBBY): a delisted ticker returns plausible-looking but wrong/stale
   rows → silent contamination if not screened.

**Magnitude.** A backtest run only on names that survived to today systematically excludes the
losers (bankruptcies, failed mergers). Published estimates of survivorship inflation for US-equity
backtests run ~1–4%/yr of return, larger for higher-churn / smaller-cap universes and longer
windows. For a quarterly-rebalanced S&P 500 strategy the bias is at the lower end but **not
negligible and always optimistic**. Every Phase 2+ performance number will carry this caveat in
print until the price source is upgraded.

**Mitigations on the free stack (best-effort, do not fully close the gap):**
- Source point-in-time S&P 500 constituent-change lists (e.g., published add/drop histories) so the
  universe at `t` includes names that later left, and keep dead tickers in the panel wherever any
  price history is recoverable.
- Screen zombie tickers: cross-check trading activity against a known delist date; drop rows after
  delisting; never trust post-delist prints.
- **Real fix:** Sharadar SEP (delisting-inclusive prices) + SF1 (PIT fundamentals), ~$30–50/mo. The
  `PriceProvider` interface is built so this is a drop-in with no change to features/models.

## 5. Macro (FRED) — point-in-time handling
- Real-time/unrevised series returned (`DGS10`, `VIXCLS`); **`GDP` correctly excluded** by
  `realtime_only=True` (revised series need ALFRED vintages to be point-in-time).
- **Operational note (fixed):** `fred.stlouisfed.org` silently hangs (read timeout) for generic
  User-Agents; the provider now sends a browser-like UA. Documented so it isn't rediscovered later.

---

# Phase 1 — Labeled panel: why it is leak-free

The panel has two kinds of columns with opposite temporal rules, and the leak-free argument is
about keeping them on the correct side of `t`.

**As-of-`t` columns (must use only data ≤ t):** `close_raw`, `dollar_vol_20d`, `sector`,
eligibility. The liquidity screen (`universe/builder.py`) computes the 20-day median dollar volume
with a **trailing, inclusive, past-only** rolling window (`min_periods=20`, so the first 20 sessions
of any ticker are NaN→ineligible, never back-filled). A unit test injects a dollar-volume spike
*strictly after* `t` and asserts the name stays ineligible at `t` — the future cannot promote a name
into the universe. Price floor uses the raw close at `t`.

**The label column (deliberately forward — this IS the prediction target):** `fwd_ret_raw` is the
total return from `t` to the trading session `H=63` days later, computed on `close_adj`. The leak
guard here is the *opposite* one: if `t+H` falls beyond a ticker's last observed price, the label is
**unrealized and dropped, never forward-filled** (test: horizon past data end ⇒ row absent). So the
panel never contains a return that did not actually complete.

**Cross-sectional targets use contemporaneous data only:** `fwd_ret_excess_median` subtracts the
same-date universe median; `fwd_ret_excess_sector` subtracts the same-date, same-sector median.
Both are pure within-`t` operations — no other date's information enters. Unknown sector ⇒
`excess_sector = NaN` (flagged, not faked as 0). Sanity check in the build: the per-date median of
`fwd_ret_excess_median` is 0 by construction (verified `max|·| = 0.00e+00`).

**Validation run (110-name sector-stratified sample, 2010–2024):** 17,520 labeled rows, 176 monthly
rebalances, median 99 names/date, 100% sector coverage, last realized label 2024-09-30 (correct
given the 63d horizon and the 2024-12-31 data end). Notably, **raw forward return averages +4.3% per
63 days (~18%/yr)** — a direct, measurable fingerprint of the current-membership survivorship bias
(today's constituents are disproportionately the period's winners). This is exactly why the honest
targets demean cross-sectionally: `excess_median`/`excess_sector` have per-date median 0 and remove
that common drift, leaving relative outperformance to be predicted.

**Overlapping windows (acknowledged, deferred to Phase 4):** monthly rebalancing (~21 trading days
apart) with a 63-day horizon means consecutive samples share ~2 months of forward return. This is
*not* a Phase-1 panel bug — the label alignment is correct — but it WILL leak across train/test in
naive CV. It is the precise reason Phase 4 uses purged + embargoed walk-forward CV
(`validation.embargo_days = purge_days = 63 ≥ horizon`). Logged here so it is not forgotten.

### Residual biases NOT solved here (carried, by design — see DECISIONS D5/D6)
- **Current S&P 500 membership** used at every historical date (no free PIT membership). Optimistic
  survivorship/lookahead bias; fixed with Sharadar historical constituents on the Option-3 migration.
- **Current GICS sector** used for all dates (no free PIT sector). Same current-snapshot caveat.
- **Delisted names absent** (yfinance) — quantified in §4 above.

These are real and acknowledged; the panel is "leak-free" in the sense that the *timing logic* is
correct given the available data, NOT in the sense that the free data is itself point-in-time.

## Open items carried into later phases
- [ ] Point-in-time S&P 500 membership source (Phase 1 universe construction).
- [ ] Zombie-ticker screen wired into the universe builder (Phase 1).
- [ ] First-disclosure-lag helper (`min(filed)` per period) for fundamental-momentum features (Phase 3).
- [ ] Decide on Sharadar upgrade before any number is treated as a real edge estimate (before/at Phase 2).
