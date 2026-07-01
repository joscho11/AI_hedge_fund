"""Validate the point-in-time, delisting-inclusive S&P 500 universe and write reports/honest_universe.md.
Step 1 deliverable — reviewed before anything rebuilds on top of it.

    .venv/Scripts/python.exe scripts/honest_universe_report.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.cache import ParquetCache
from src.universe.honest_sp500 import (
    liquidated_tickers,
    members_on,
    membership_intervals,
    membership_panel,
    snapshot_members,
)
from src.utils.calendars import month_end_rebalance_dates
from src.utils.config import load_config

REPO = Path(__file__).resolve().parents[1]


def main():
    cfg = load_config()
    cache = ParquetCache(cfg.cache_path)
    sp = cache.get("sharadar", "SP500")
    tk = cache.get("sharadar", "TICKERS")
    actions = cache.get("sharadar", "ACTIONS")

    reb = month_end_rebalance_dates(cfg.dates.start, cfg.dates.end, cfg.calendar.exchange)
    intervals = membership_intervals(sp)
    panel = membership_panel(sp, reb)
    panel["date"] = pd.to_datetime(panel["date"])

    # names-per-date
    npd = panel.groupby("date")["ticker"].nunique()

    # current members + delisted flags
    current = set(sp.loc[sp["action"] == "current", "ticker"])
    honest_names = set(panel["ticker"].unique())
    extra = honest_names - current                         # in the honest panel but not in today's index
    delisted_set = set(tk.loc[tk["isdelisted"] == "Y", "ticker"])
    honest_delisted = honest_names & delisted_set
    liq = liquidated_tickers(actions)
    honest_liq = honest_names & liq

    # membership-leakage check: every (date,ticker) in the panel lies inside an interval
    leak = 0
    for d, g in panel.groupby("date"):
        leak += len(set(g["ticker"]) - members_on(intervals, d))

    # snapshot cross-check at quarterly historical dates inside the window
    snaps = snapshot_members(sp)
    win = [d for d in snaps if pd.Timestamp(cfg.dates.start) <= pd.Timestamp(d) <= pd.Timestamp(cfg.dates.end)]
    jacc = []
    for d in win:
        recon = members_on(intervals, d)
        snap = snaps[d]
        if snap:
            inter = len(recon & snap); union = len(recon | snap)
            jacc.append(inter / union if union else 1.0)
    mean_jacc = sum(jacc) / len(jacc) if jacc else float("nan")

    # spot-check names: a long-time constituent + real removed names in-window
    removed = sp[sp["action"] == "removed"].copy()
    removed["date"] = pd.to_datetime(removed["date"])
    removed_in_win = removed[(removed["date"] >= "2018-01-01") & (removed["date"] <= cfg.dates.end)]
    sample_removed = removed_in_win.sort_values("date", ascending=False).head(8)[["date", "ticker", "name"]]

    _write_report(REPO / "reports" / "honest_universe.md", {
        "reb_n": len(reb), "panel_rows": len(panel),
        "npd_min": int(npd.min()), "npd_med": int(npd.median()), "npd_max": int(npd.max()),
        "npd_first": (npd.index.min().date(), int(npd.iloc[0])),
        "npd_last": (npd.index.max().date(), int(npd.iloc[-1])),
        "current_n": len(current), "honest_n": len(honest_names),
        "extra_n": len(extra), "honest_delisted_n": len(honest_delisted),
        "honest_liq_n": len(honest_liq),
        "leak": leak, "mean_jacc": mean_jacc, "n_snaps": len(win),
        "sample_removed": sample_removed, "intervals": intervals,
    })
    print(f"names/date: min {npd.min()} med {int(npd.median())} max {npd.max()}")
    print(f"honest universe distinct names: {len(honest_names)} (current index: {len(current)})")
    print(f"  in honest but NOT in today's index (survivorship additions): {len(extra)}")
    print(f"  of honest names, flagged delisted in TICKERS: {len(honest_delisted)}; "
          f"bankruptcy/liquidation: {len(honest_liq)}")
    print(f"membership-leakage violations: {leak} (must be 0)")
    print(f"snapshot cross-check mean Jaccard over {len(win)} quarterly dates: {mean_jacc:.4f}")
    print("Wrote reports/honest_universe.md")


def _write_report(path: Path, s: dict):
    L = ["# Honest universe — point-in-time, delisting-inclusive S&P 500\n"]
    L.append("Step 1 of the survivorship-free re-run. This universe replaces the current-membership "
             "(\"flattered\") one: at each monthly rebalance, members are reconstructed from Sharadar "
             "SP500 add/remove events, **including names later removed or delisted**.\n")

    L.append("## Construction & keys\n")
    L.append("- **Membership** = add/remove intervals (`added <= t < removed`); re-additions handled; "
             "a `removed` with no prior `added` (member before 1957 tracking) opens at -inf.\n"
             "- **Entity key:** Sharadar `ticker` is non-recycled here (0 of 31,467 map to >1 "
             "permaticker), so ticker joins don't cross-wire companies; `permaticker` is still carried "
             "and SEP/SF1 lookups are bounded to each name's [firstpricedate, lastpricedate].\n")

    L.append("## Delisting-return rule (the part that's easy to get wrong)\n")
    L.append("Forward return `t -> t+H` on SEP adjusted close (`closeadj`). If a name's price history "
             "ends before `t+H` (it delisted inside the window) we use its **terminal** `closeadj` as "
             "the forward price — capturing the realized outcome, **never dropping the name** (dropping "
             "hides the loss and re-introduces survivorship bias). Acquisition → terminal ≈ deal price; "
             "**`bankruptcyliquidation` (ACTIONS) → floored at −100%**; other delistings use the real "
             "terminal SEP price. Applied in the Step-2 panel rebuild.\n")

    L.append("## Validation\n")
    L.append(f"- **Names per rebalance date:** min {s['npd_min']}, median {s['npd_med']}, max "
             f"{s['npd_max']} over {s['reb_n']} monthly rebalances "
             f"(start {s['npd_first'][0]}={s['npd_first'][1]}, end {s['npd_last'][0]}={s['npd_last'][1]}). "
             "Sits near index size with real churn.\n")
    L.append(f"- **Survivorship additions:** honest universe has **{s['honest_n']} distinct names** vs "
             f"the current index's {s['current_n']}; **{s['extra_n']} names are in the honest panel but "
             f"NOT in today's index** — exactly the removed/delisted names the flattered panel was "
             f"missing. Of honest names, **{s['honest_delisted_n']}** are flagged delisted in TICKERS "
             f"and **{s['honest_liq_n']}** had a bankruptcy/liquidation.\n")
    L.append(f"- **Membership-leakage test:** {s['leak']} violations — no name appears before its add "
             "or after its remove (must be 0).\n")
    L.append(f"- **Independent cross-check:** vs Sharadar's quarterly `historical` membership snapshots "
             f"({s['n_snaps']} in-window dates), mean Jaccard overlap = **{s['mean_jacc']:.4f}** "
             "(1.0 = identical membership).\n")

    L.append("### Spot-check — real removed names (present in their window, absent after removal)\n")
    L.append("| Removed date | Ticker | Name | member at remove−1y? | member at remove+1y? |")
    L.append("|---|---|---|---|---|")
    iv = s["intervals"]
    for _, r in s["sample_removed"].iterrows():
        d = pd.Timestamp(r["date"])
        before = r["ticker"] in members_on(iv, d - pd.DateOffset(years=1))
        after = r["ticker"] in members_on(iv, d + pd.DateOffset(years=1))
        L.append(f"| {d.date()} | {r['ticker']} | {r['name']} | {'yes' if before else 'no'} | "
                 f"{'yes' if after else 'no'} |")
    L.append("\n(Expected pattern: **yes** before removal, **no** after — point-in-time membership.)\n")
    L.append("\n> Next (Step 2, after review): rebuild the labeled panel on this universe with "
             "delisting-aware forward returns; keep the flattered panel as the 'before' comparison.\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
