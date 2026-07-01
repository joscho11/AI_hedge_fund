"""Purged, embargoed walk-forward cross-validation — the leakage-controlled evaluator for Phase 4.

The leak this guards against: labels are 63-trading-day forward returns, so a training sample at
rebalance date d "sees" prices through label_end(d) = d + 63td. If label_end(d) reaches into a test
block, that training label was computed from test-period prices → leakage. We therefore keep a
training sample only if its label window ends at least `embargo_days` trading days BEFORE the test
block starts:

    keep train d  ⟺  label_end(d) ≤ offset(test_start, −embargo_days)

With embargo_days ≥ horizon this both PURGES overlapping-label samples and adds an EMBARGO gap.

Scheme: EXPANDING window (train on all eligible past), pre-registered in DECISIONS. Per-date
cross-sectional normalization is already done in the feature stores (leak-safe); the only fitted
preprocessing here is constant-0 imputation of missing z-features (0 = the cross-sectional mean —
leak-free, no parameters learned from data).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline

from ..data.types import COL_DATE, COL_TICKER
from ..eval.metrics import ICSummary, information_coefficient
from ..utils.calendars import offset_trading_days


@dataclass(frozen=True)
class Fold:
    train_dates: pd.DatetimeIndex
    test_dates: pd.DatetimeIndex


def label_end(d, horizon_days: int, exchange: str = "XNYS") -> pd.Timestamp:
    return offset_trading_days(d, horizon_days, exchange)


def walk_forward_folds(
    dates, horizon_days: int, embargo_days: int, *,
    min_train_months: int = 36, n_folds: int = 6, scheme: str = "expanding",
    rolling_months: int | None = None, exchange: str = "XNYS",
) -> list[Fold]:
    """Build purged/embargoed walk-forward folds over `dates` (the development rebalance dates)."""
    dates = pd.DatetimeIndex(sorted(pd.DatetimeIndex(dates).normalize().unique()))
    train_floor = dates[0] + pd.DateOffset(months=min_train_months)
    test_pool = dates[dates >= train_floor]
    if len(test_pool) < n_folds:
        raise ValueError("not enough dates after min_train for the requested n_folds")
    blocks = np.array_split(test_pool, n_folds)

    folds = []
    for block in blocks:
        test_dates = pd.DatetimeIndex(block)
        test_start = test_dates.min()
        cutoff = offset_trading_days(test_start, -embargo_days, exchange)
        cand = dates[dates < test_start]
        if scheme == "rolling" and rolling_months:
            cand = cand[cand >= (test_start - pd.DateOffset(months=rolling_months))]
        keep = [d for d in cand if offset_trading_days(d, horizon_days, exchange) <= cutoff]
        if keep:
            folds.append(Fold(pd.DatetimeIndex(keep), test_dates))
    return folds


def _pipeline(make_model):
    # Features are already per-date z-scores; impute missing with 0 (the cross-sectional mean) — a
    # constant, so nothing is learned from the training data (leak-free).
    return Pipeline([("imp", SimpleImputer(strategy="constant", fill_value=0.0)),
                     ("est", make_model())])


@dataclass
class WalkForwardResult:
    ic_series: pd.Series        # per-test-date OOS IC
    summary: ICSummary          # mean IC, IR, t-stat, % positive (per date)
    fold_mean_ic: list[float]   # mean OOS IC within each fold
    frac_folds_positive: float
    preds: pd.DataFrame         # [date, ticker, score, <target>] over all test blocks (OOS)


def nested_walk_forward(
    panel: pd.DataFrame, feature_cols: list[str], target_col: str,
    grid: list[tuple[dict, "callable"]], outer_folds: list[Fold], *,
    horizon_days: int, embargo_days: int, inner_n_folds: int = 3, inner_min_train_months: int = 24,
    exchange: str = "XNYS",
) -> tuple["WalkForwardResult", list[dict]]:
    """Nested walk-forward: for each OUTER fold, pick hyper-parameters by an INNER walk-forward on
    that fold's TRAIN block only (objective = inner mean OOS IC), then refit the chosen config on the
    full outer-train and predict the outer-test. No outer-test or hold-out data touches HP selection.
    `grid` is a list of (hp_dict, make_model) candidates. Returns the outer OOS result + chosen HPs."""
    preds, fold_mean_ic, chosen = [], [], []
    for ofold in outer_folds:
        tr = panel[panel[COL_DATE].isin(ofold.train_dates)]
        inner_folds = walk_forward_folds(
            ofold.train_dates, horizon_days, embargo_days,
            min_train_months=inner_min_train_months, n_folds=inner_n_folds, exchange=exchange)
        # pick HP by inner mean IC (fall back to first candidate if inner folds can't form)
        best_hp, best_make, best_score = grid[0][0], grid[0][1], -np.inf
        if inner_folds:
            for hp, make in grid:
                r = evaluate_walk_forward(tr, feature_cols, target_col, make, inner_folds)
                score = r.summary.mean_ic if pd.notna(r.summary.mean_ic) else -np.inf
                if score > best_score:
                    best_hp, best_make, best_score = hp, make, score
        chosen.append(best_hp)
        # refit on full outer-train, predict outer-test
        te = panel[panel[COL_DATE].isin(ofold.test_dates)].dropna(subset=[target_col]).copy()
        trc = tr.dropna(subset=[target_col])
        if trc.empty or te.empty:
            continue
        model = _pipeline(best_make)
        model.fit(trc[feature_cols], trc[target_col])
        te["score"] = model.predict(te[feature_cols])
        preds.append(te[[COL_DATE, COL_TICKER, "score", target_col]])
        s, _ = information_coefficient(te, "score", target_col)
        if len(s):
            fold_mean_ic.append(float(s.mean()))

    preds_df = (pd.concat(preds, ignore_index=True) if preds
                else pd.DataFrame(columns=[COL_DATE, COL_TICKER, "score", target_col]))
    ic_series, summary = information_coefficient(preds_df, "score", target_col)
    frac_pos = float(np.mean([m > 0 for m in fold_mean_ic])) if fold_mean_ic else float("nan")
    return WalkForwardResult(ic_series, summary, fold_mean_ic, frac_pos, preds_df), chosen


def evaluate_walk_forward(
    panel: pd.DataFrame, feature_cols: list[str], target_col: str, make_model, folds: list[Fold],
) -> WalkForwardResult:
    """Fit on each fold's train block, predict its OOS test block, score by per-date Spearman IC."""
    preds = []
    fold_mean_ic = []
    for fold in folds:
        tr = panel[panel[COL_DATE].isin(fold.train_dates)].dropna(subset=[target_col])
        te = panel[panel[COL_DATE].isin(fold.test_dates)].dropna(subset=[target_col]).copy()
        if tr.empty or te.empty:
            continue
        model = _pipeline(make_model)
        model.fit(tr[feature_cols], tr[target_col])
        te["score"] = model.predict(te[feature_cols])
        preds.append(te[[COL_DATE, COL_TICKER, "score", target_col]])
        s, _ = information_coefficient(te.rename(columns={target_col: target_col}), "score", target_col)
        if len(s):
            fold_mean_ic.append(float(s.mean()))

    preds_df = (pd.concat(preds, ignore_index=True) if preds
                else pd.DataFrame(columns=[COL_DATE, COL_TICKER, "score", target_col]))
    ic_series, summary = information_coefficient(preds_df, "score", target_col)
    frac_pos = float(np.mean([m > 0 for m in fold_mean_ic])) if fold_mean_ic else float("nan")
    return WalkForwardResult(ic_series, summary, fold_mean_ic, frac_pos, preds_df)
