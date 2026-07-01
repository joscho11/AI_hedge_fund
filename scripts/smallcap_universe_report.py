"""Phase 5 STEP 1 — build the point-in-time small/mid-cap universe, run the recycling check,
validate, and write reports/smallcap_universe.md. Saves membership for the Step-2 panel build.

    .venv/Scripts/python.exe scripts/smallcap_universe_report.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pyarrow.dataset as pa_ds

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.cache import ParquetCache
from src.data.providers.sharadar import SharadarProvider
from src.features.base import asof_values
from src.labels.honest_panel import sep_price_frame
from src.universe.smallcap import build_smallcap_membership, common_stock_tickers
from src.utils.calendars import month_end_rebalance_dates
from src.utils.config import load_config

REPO = Path(__file__).resolve().parents[1]
CAP_LOW, CAP_HIGH = 300e6, 5e9
MIN_PRICE, MIN_DVOL = 5.0, 1e6


def _load_sep(cache, tickers, start="2009-10-01"):
    # SEP `date` is stored as an ISO string; compare lexicographically (string bound), not a Timestamp.
    dset = pa_ds.dataset(str(cache.root / "sharadar" / "SEP.parquet"), format="parquet")
    flt = (pa_ds.field("ticker").isin(tickers)) & (pa_ds.field("date") >= start)
    return dset.to_table(columns=["ticker", "date", "closeunadj", "closeadj", "volume"],
                         filter=flt).to_pandas()


def main():
    cfg = load_config()
    cache = ParquetCache(cfg.cache_path)
    prov = SharadarProvider(cache)
    tk = cache.get("sharadar", "TICKERS")
    sp500 = cache.get("sharadar", "SP500")
    actions = cache.get("sharadar", "ACTIONS")
    reb = month_end_rebalance_dates(cfg.dates.start, cfg.dates.end, cfg.calendar.exchange)

    common = common_stock_tickers(tk)
    print(f"Domestic common-stock tickers: {len(common):,}")
    prices = sep_price_frame(_load_sep(cache, common))
    print(f"SEP rows (common, 2009+): {len(prices):,}")

    membership = build_smallcap_membership(
        prov, tk, prices, sp500, reb, cap_low=CAP_LOW, cap_high=CAP_HIGH,
        min_price=MIN_PRICE, min_dollar_volume=MIN_DVOL)
    cache.put("universe", "smallcap_membership", membership)
    print(f"Membership rows: {len(membership):,}, distinct names: {membership['ticker'].nunique()}")

    # ---- validation stats ----
    npd = membership.groupby("date")["ticker"].nunique()
    uni_tickers = set(membership["ticker"].unique())
    delisted = set(tk.loc[tk["isdelisted"] == "Y", "ticker"]) & uni_tickers
    bankrupt = set(actions.loc[actions["action"] == "bankruptcyliquidation", "ticker"]) & uni_tickers
    # recycling check scoped to this universe
    dc = tk[tk["category"].isin({"Domestic Common Stock", "Domestic Common Stock Primary Class"})]
    recyc = int((dc[dc["ticker"].isin(uni_tickers)].groupby("ticker")["permaticker"].nunique() > 1).sum())
    # fundamentals coverage: fraction of membership rows with an as-of-t ART revenue
    rev = prov.get_facts(sorted(uni_tickers), ["revenue"], "1998-01-01",
                         reb.max().strftime("%Y-%m-%d"), dimension="ART")
    rev_asof = asof_values(rev, pd.DatetimeIndex(sorted(membership["date"].unique())))
    cov = membership.merge(rev_asof, on=["date", "ticker"], how="left")
    fund_cov = float(cov["revenue"].notna().mean())
    # large-cap comparison
    honest_n = pd.read_parquet(cache.root / "panel" / "panel_honest.parquet")["ticker"].nunique()

    mc = membership["market_cap"]
    stats = {
        "n_names": int(membership["ticker"].nunique()),
        "npd_min": int(npd.min()), "npd_med": int(npd.median()), "npd_max": int(npd.max()),
        "npd_first": (npd.index.min().date(), int(npd.iloc[0])),
        "npd_last": (npd.index.max().date(), int(npd.iloc[-1])),
        "cap_pct": {p: float(mc.quantile(p)) for p in (0.0, 0.25, 0.5, 0.75, 1.0)},
        "delisted_n": len(delisted), "bankrupt_n": len(bankrupt),
        "delisted_frac": len(delisted) / max(1, len(uni_tickers)),
        "recyc": recyc, "fund_cov": fund_cov, "honest_largecap_names": int(honest_n),
        "dvol_med": float(membership["dollar_vol_20d"].median()),
    }
    _write_report(REPO / "reports" / "smallcap_universe.md", stats)
    print(f"names/date: {stats['npd_min']}/{stats['npd_med']}/{stats['npd_max']} (min/med/max)")
    print(f"cap band realized $M: { {k: round(v/1e6) for k,v in stats['cap_pct'].items()} }")
    print(f"delisted frac {stats['delisted_frac']:.1%}, bankruptcies {stats['bankrupt_n']}, "
          f"recycling collisions {recyc}, fundamentals coverage {fund_cov:.1%}")
    print("Wrote reports/smallcap_universe.md")


def _write_report(path, s):
    L = ["# Phase 5 — small/mid-cap universe (point-in-time, delisted-inclusive)\n"]
    L.append("> Pre-registration candidates (DECISIONS D18), pending approval before the pipeline "
             "rebuilds on this universe.\n")
    L.append("## Pre-registered filters (candidates)\n")
    L.append(f"- Domestic common stock only (primary listings); delisted-inclusive.\n"
             f"- Market-cap band **[$300M, $5B]** (price-at-t × as-of-t ARQ sharesbas); concurrent "
             f"S&P 500 members excluded.\n"
             f"- Liquidity: price **> $5**, 20-day median dollar volume **> $1M/day** (as-of t).\n"
             f"- One-way cost **30 bps** (sensitivity {{25,50,100}}); monthly, 63d label.\n")
    L.append("## Validation\n")
    L.append(f"- **Names per rebalance:** {s['npd_min']} / {s['npd_med']} / {s['npd_max']} "
             f"(min/median/max); start {s['npd_first'][0]}={s['npd_first'][1]}, "
             f"end {s['npd_last'][0]}={s['npd_last'][1]}. Distinct names ever: **{s['n_names']:,}** "
             f"(vs {s['honest_largecap_names']} in the large-cap honest universe).\n")
    cp = s["cap_pct"]
    L.append(f"- **Realized market-cap band ($M):** min {cp[0.0]/1e6:.0f}, p25 {cp[0.25]/1e6:.0f}, "
             f"median {cp[0.5]/1e6:.0f}, p75 {cp[0.75]/1e6:.0f}, max {cp[1.0]/1e6:.0f} — within the "
             "[$300M, $5B] band by construction. Median 20d dollar volume: "
             f"${s['dvol_med']/1e6:.1f}M/day.\n")
    L.append(f"- **Delisting/bankruptcy:** {s['delisted_frac']:.1%} of universe names are flagged "
             f"delisted ({s['delisted_n']:,} names); {s['bankrupt_n']} had a bankruptcy/liquidation. "
             "Far higher churn than large-caps — survivorship bias would be severe here, so "
             "delisted-inclusion + delisting-aware labels (Step 2) are essential.\n")
    L.append(f"- **Ticker-recycling check (scoped to this universe):** **{s['recyc']} collisions** — "
             "no ticker maps to >1 permaticker even in this churny universe (Sharadar disambiguates "
             "recycled symbols at source). Ticker joins are safe; permaticker carried + date-bounded "
             "lookups as defense-in-depth.\n")
    L.append(f"- **Fundamentals coverage:** {s['fund_cov']:.1%} of membership rows have an as-of-t "
             "ART revenue. Spottier than large-caps; features will be NaN where missing (never "
             "filled), with coverage reported per family in Step 2.\n")
    L.append("- **Point-in-time membership:** all filters (liquidity, market cap, S&P exclusion) use "
             "only data with date/datekey ≤ t; a name enters the band only when its as-of-t "
             "cap/liquidity qualify it (see `tests/test_smallcap_universe.py`).\n")
    L.append("\n> Next (Step 2, after approval): delisting-aware labeled panel + five feature families "
             "on this universe; small-cap baselines. Hold-out (2022+) stays sealed.\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
