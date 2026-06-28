"""Finance evaluation metrics. Built once, reused by baselines and the Phase 4/5 ML strategy.

Three families:
  * information_coefficient — per-date Spearman rank corr(signal, realized forward target).
  * quantile_returns        — decile-sorted mean forward target + monotonicity + top-minus-bottom.
  * performance_stats       — CAGR/vol/Sharpe/Sortino/maxDD/turnover/hit-rate (gross & net).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from scipy import stats

from ..data.types import COL_DATE


# ------------------------------------------------------------------- Information Coefficient
@dataclass
class ICSummary:
    target: str
    n_dates: int
    mean_ic: float
    std_ic: float
    ic_ir: float          # mean / std (the "information ratio" of the IC series)
    t_stat: float         # mean / (std / sqrt(n)) — H0: mean IC = 0
    frac_positive: float


def information_coefficient(
    scored: pd.DataFrame, signal_col: str, target_col: str
) -> tuple[pd.Series, ICSummary]:
    """Per-date Spearman IC between signal and target, plus a summary with a t-stat on mean IC."""
    per_date = {}
    for t, g in scored.groupby(COL_DATE):
        sub = g[[signal_col, target_col]].dropna()
        if len(sub) >= 5 and sub[signal_col].nunique() > 1 and sub[target_col].nunique() > 1:
            rho, _ = stats.spearmanr(sub[signal_col], sub[target_col])
            per_date[t] = rho
    s = pd.Series(per_date).sort_index()
    n = len(s)
    mean, std = float(s.mean()), float(s.std(ddof=1)) if n > 1 else (float(s.mean()), np.nan)
    ir = mean / std if std and not np.isnan(std) else np.nan
    t_stat = mean / (std / np.sqrt(n)) if std and n > 1 else np.nan
    return s, ICSummary(
        target=target_col, n_dates=n, mean_ic=mean, std_ic=std, ic_ir=ir,
        t_stat=t_stat, frac_positive=float((s > 0).mean()) if n else np.nan,
    )


# --------------------------------------------------------------------------- Quantile dec/spread
@dataclass
class QuantileResult:
    target: str
    n_quantiles: int
    mean_by_quantile: dict       # quantile index (0=lowest signal) -> mean target
    top_minus_bottom: float
    monotonicity: float          # Spearman(quantile index, mean target); +1 = perfectly increasing


def quantile_returns(
    scored: pd.DataFrame, signal_col: str, target_col: str, n_quantiles: int = 10
) -> QuantileResult:
    """Sort each date into `n_quantiles` by signal; average the target within each quantile per date,
    then average across dates (equal weight per date). Quantile 0 = lowest signal."""
    def _assign(g: pd.DataFrame) -> pd.DataFrame:
        g = g[[signal_col, target_col]].dropna()
        if len(g) < n_quantiles:
            return pd.DataFrame(columns=["q", target_col])
        q = pd.qcut(g[signal_col].rank(method="first"), n_quantiles, labels=False, duplicates="drop")
        return pd.DataFrame({"q": q.values, target_col: g[target_col].values})

    pieces = [p for _, grp in scored.groupby(COL_DATE) if not (p := _assign(grp)).empty]
    if not pieces:
        return QuantileResult(target_col, n_quantiles, {}, np.nan, np.nan)
    # Per-date mean per quantile, then average over dates.
    stacked = pd.concat(
        [p.groupby("q")[target_col].mean() for p in pieces], axis=1
    )
    mean_by_q = stacked.mean(axis=1)
    qs = mean_by_q.index.to_numpy(dtype=float)
    vals = mean_by_q.to_numpy(dtype=float)
    mono = float(stats.spearmanr(qs, vals).correlation) if len(qs) > 1 else np.nan
    tmb = float(vals[-1] - vals[0])
    return QuantileResult(
        target=target_col, n_quantiles=n_quantiles,
        mean_by_quantile={int(k): float(v) for k, v in mean_by_q.items()},
        top_minus_bottom=tmb, monotonicity=mono,
    )


# --------------------------------------------------------------------------- Portfolio performance
@dataclass
class PerfStats:
    cagr: float
    ann_vol: float
    sharpe: float
    sortino: float
    max_drawdown: float
    hit_rate: float
    avg_turnover: float        # one-way fraction per rebalance
    total_cost_drag: float     # cumulative cost as fraction (gross cum - net cum)
    n_periods: int


def _max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    return float((equity / peak - 1.0).min())


def performance_stats(
    returns: pd.Series,
    periods_per_year: int = 12,
    rf: float = 0.0,
    turnover: pd.Series | None = None,
    gross_returns: pd.Series | None = None,
) -> PerfStats:
    """Annualized stats from a per-rebalance return series (monthly => periods_per_year=12)."""
    r = returns.dropna()
    n = len(r)
    if n == 0:
        return PerfStats(*([np.nan] * 8), 0)
    equity = (1.0 + r).cumprod()
    cagr = float(equity.iloc[-1] ** (periods_per_year / n) - 1.0)
    ann_vol = float(r.std(ddof=1) * np.sqrt(periods_per_year)) if n > 1 else np.nan
    excess = r - rf / periods_per_year
    sharpe = float(excess.mean() / r.std(ddof=1) * np.sqrt(periods_per_year)) if n > 1 and r.std(ddof=1) else np.nan
    downside = r[r < 0]
    dd_std = downside.std(ddof=1) if len(downside) > 1 else np.nan
    sortino = float(excess.mean() / dd_std * np.sqrt(periods_per_year)) if dd_std and not np.isnan(dd_std) else np.nan
    cost_drag = np.nan
    if gross_returns is not None:
        g = (1.0 + gross_returns.dropna()).cumprod()
        cost_drag = float(g.iloc[-1] - equity.iloc[-1]) if len(g) else np.nan
    return PerfStats(
        cagr=cagr, ann_vol=ann_vol, sharpe=sharpe, sortino=sortino,
        max_drawdown=_max_drawdown(equity), hit_rate=float((r > 0).mean()),
        avg_turnover=float(turnover.dropna().mean()) if turnover is not None else np.nan,
        total_cost_drag=cost_drag, n_periods=n,
    )


def stats_to_dict(p: PerfStats) -> dict:
    return asdict(p)
