"""Phase 4 CV harness validation: the purge/embargo boundary guarantee, plus functional checks that
the OOS-IC evaluator (a) reads ~0 on noise, (b) recovers real signal when present, and (c) screams
(~1) on a future-peek feature — so a null elsewhere is a finding, not a broken harness."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from src.cv.walk_forward import evaluate_walk_forward, label_end, walk_forward_folds
from src.data.types import COL_DATE, COL_TICKER
from src.utils.calendars import month_end_rebalance_dates

H, EMB = 63, 63


def _dev_dates():
    return month_end_rebalance_dates("2010-01-01", "2021-12-31")


def test_purge_embargo_boundary_guarantee():
    dates = _dev_dates()
    folds = walk_forward_folds(dates, H, EMB, min_train_months=36, n_folds=6)
    assert len(folds) == 6
    prev_test_end = None
    for f in folds:
        test_start = f.test_dates.min()
        cutoff = label_end(test_start, -EMB)  # offset(test_start, -embargo)
        # every train sample's 63d label window ends at/before the embargo cutoff (so < test_start)
        assert f.train_dates.max() < test_start
        for d in f.train_dates:
            assert label_end(d, H) <= cutoff < test_start
        # test blocks are ordered and non-overlapping
        if prev_test_end is not None:
            assert test_start > prev_test_end
        prev_test_end = f.test_dates.max()


def test_holdout_never_enters_dev_folds():
    folds = walk_forward_folds(_dev_dates(), H, EMB, min_train_months=36, n_folds=6)
    for f in folds:
        assert f.test_dates.max() < pd.Timestamp("2022-01-01")
        assert f.train_dates.max() < pd.Timestamp("2022-01-01")


def _synthetic_panel(seed=0):
    rng = np.random.default_rng(seed)
    dates = month_end_rebalance_dates("2010-01-01", "2018-12-31")
    rows = []
    for d in dates:
        for i in range(60):
            tgt = rng.normal()
            rows.append({
                COL_DATE: d, COL_TICKER: f"T{i:03d}",
                "target": tgt,
                "f_noise": rng.normal(),
                "f_signal": 0.6 * tgt + 0.8 * rng.normal(),
                "f_peek": tgt,  # a forbidden peek at the contemporaneous label
            })
    return pd.DataFrame(rows), walk_forward_folds(dates, H, EMB, min_train_months=36, n_folds=4)


def _ridge():
    return Ridge(alpha=1.0)


def test_noise_feature_oos_ic_near_zero():
    panel, folds = _synthetic_panel(seed=1)
    res = evaluate_walk_forward(panel, ["f_noise"], "target", _ridge, folds)
    assert abs(res.summary.mean_ic) < 0.08
    assert abs(res.summary.t_stat) < 2.5


def test_real_signal_is_recovered_oos():
    panel, folds = _synthetic_panel(seed=2)
    res = evaluate_walk_forward(panel, ["f_signal"], "target", _ridge, folds)
    assert res.summary.mean_ic > 0.2          # genuine signal detected OOS
    assert res.summary.t_stat > 3
    assert res.frac_folds_positive == 1.0


def test_future_peek_feature_is_flagged_by_ic():
    panel, folds = _synthetic_panel(seed=3)
    res = evaluate_walk_forward(panel, ["f_peek"], "target", _ridge, folds)
    assert res.summary.mean_ic > 0.95         # the metric screams on a leak
