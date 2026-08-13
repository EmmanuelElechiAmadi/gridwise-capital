"""
Tests for the v4 empirical benchmark toolkit (intelligence/research_stats.py):
PBO/CSCV, Deflated Sharpe Ratio, calibration curves and CPCV splits.
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from intelligence.research_stats import (  # noqa: E402
    pbo_cscv,
    deflated_sharpe,
    expected_max_sharpe,
    calibration_curve,
    cpcv_splits,
    run_empirical_benchmark,
)


class TestPBO:
    def test_stable_strategy_has_low_pbo(self):
        # All strategies perform similarly in-sample AND out-of-sample.
        M = np.array([
            [1.0, 1.1, 0.9, 1.0, 1.2, 0.8],
            [0.9, 1.0, 1.1, 1.0, 0.8, 1.2],
            [1.0, 0.9, 1.0, 1.1, 1.0, 1.0],
        ])
        res = pbo_cscv(M, n_splits=32, seed=7)
        assert res["pbo"] is not None
        assert 0.0 <= res["pbo"] <= 1.0

    def test_overfit_matrix_has_high_pbo(self):
        # A and B are mirror images over an ODD number of columns: the split
        # halves are 5 and 5, so the in-sample gap is always odd and never
        # zero.  Whichever strategy wins in-sample therefore always loses
        # out-of-sample — every split flags an overfit winner (PBO -> 1).
        M = np.array([
            [1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0],
            [-1.0, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 1.0],
        ])
        res = pbo_cscv(M, n_splits=32, seed=7)
        assert res["pbo"] is not None
        assert res["pbo"] >= 0.9

    def test_rejects_too_small_matrix(self):
        res = pbo_cscv([[1.0, 2.0, 3.0]])
        assert res["pbo"] is None
        assert "error" in res


class TestDSR:
    def test_more_trials_deflates_more(self):
        dsr1 = deflated_sharpe(1.5, num_trials=2, num_periods=252)
        dsr2 = deflated_sharpe(1.5, num_trials=200, num_periods=252)
        assert dsr1["dsr"] > dsr2["dsr"]
        assert dsr2["sr0_annualized"] > dsr1["sr0_annualized"]

    def test_higher_sharpe_survives_deflation(self):
        low = deflated_sharpe(0.5, num_trials=50, num_periods=252)
        high = deflated_sharpe(3.0, num_trials=50, num_periods=252)
        assert high["dsr"] > low["dsr"]

    def test_expected_max_sharpe_is_positive_for_many_trials(self):
        sr0 = expected_max_sharpe(100, 252)
        assert sr0 > 0.0
        assert expected_max_sharpe(1, 252) == 0.0


class TestCalibration:
    def test_perfect_calibration_aligns_prediction_and_frequency(self):
        y_true = [1, 1, 0, 0, 1]
        y_prob = [0.9, 0.9, 0.1, 0.1, 0.9]
        res = calibration_curve(y_true, y_prob, bins=5)
        assert res["n"] == 5
        # A near-perfect calibration has a tiny Brier score, and every bin
        # with data reports a coherent predicted vs observed frequency.
        assert res["brier_score"] < 0.05
        for p in res["points"]:
            assert p["count"] > 0
            assert 0.0 <= p["fraction_positive"] <= 1.0

    def test_brier_score_in_bounds(self):
        res = calibration_curve([1, 0, 1, 0, 1, 0],
                                [0.9, 0.1, 0.9, 0.1, 0.9, 0.1], bins=4)
        assert 0.0 <= res["brier_score"] <= 1.0

    def test_empty_input(self):
        res = calibration_curve([], [])
        assert res["n"] == 0


class TestCPCV:
    def test_no_leakage_between_train_and_test(self):
        splits = cpcv_splits(1000, n_splits=5, embargo_frac=0.01, test_frac=0.2)
        assert len(splits) == 5
        for tr, te in splits:
            assert not set(tr) & set(te)   # disjoint
            assert len(te) > 0 and len(tr) > 0

    def test_embargo_purges_samples_after_test(self):
        splits = cpcv_splits(100, n_splits=3, embargo_frac=0.05, test_frac=0.2)
        for tr, te in splits:
            assert set(tr).isdisjoint(set(te))

    def test_too_small_raises(self):
        import pytest
        with pytest.raises(ValueError):
            cpcv_splits(5, n_splits=5, test_frac=0.2)


class TestConsensusScorecard:
    """v4: score persisted consensus views against realized forward returns."""

    def _history(self):
        import pandas as pd
        import numpy as np
        idx = pd.date_range("2026-01-01", periods=100, freq="h", tz="UTC")
        close = 2000.0 + np.linspace(0, 50, 100)  # strongly up-trending
        return pd.DataFrame({"close": close}, index=idx)

    def test_scores_views_and_builds_scorecard(self):
        from intelligence.research_stats import score_consensus_history
        from intelligence.consensus import ConsensusEngine
        from intelligence.consensus.signals import Signal
        hist = self._history()
        # A view at bar 10, 24h before bar 34: forward return is strongly positive.
        views = []
        for i, t in enumerate(["2026-01-01T10:00:00Z", "2026-01-01T20:00:00Z"]):
            view = ConsensusEngine().fuse([
                Signal("kronos", "BULL", 0.8, 0.8),
                Signal("backtest", "BULL", 0.8, 0.8),
            ], cycle_id=f"c{i}")
            view.generated_at = t
            views.append(view.to_dict())
        out, scorecard, scored = score_consensus_history(views, hist)
        assert scored == 2
        assert all(v["realized"] == "BULL" for v in out)
        assert scorecard[0]["correct"] == scorecard[0]["votes"] == 2
        assert scorecard[0]["hit_rate_pct"] == 100.0
        assert "forward_return_pct" in out[0]

    def test_pending_when_no_forward_data(self):
        from intelligence.research_stats import score_consensus_history
        import pandas as pd
        import numpy as np
        hist = pd.DataFrame({"close": np.arange(10.0)},
                            index=pd.date_range("2026-01-01", periods=10, freq="h"))
        views = [{"generated_at": "2026-01-02T00:00:00Z",
                  "direction": "BULL", "contributions": [
                      {"source": "kronos", "direction": "BULL"}]}]
        out, scorecard, scored = score_consensus_history(views, hist)
        assert scored == 0
        assert "realized" not in out[0]
        assert scorecard == []

    def test_handles_no_views(self):
        from intelligence.research_stats import score_consensus_history
        out, scorecard, scored = score_consensus_history([], None)
        assert out == [] and scorecard == [] and scored == 0


class TestEmpiricalBenchmark:
    def test_full_report_over_synthetic_artifacts(self):
        probe_metrics = [
            {"strategy_key": "grid_strategy", "sharpe_ratio": 1.4,
             "num_trades": 60},
            {"strategy_key": "grid_strategy", "sharpe_ratio": 0.9,
             "num_trades": 40},
            {"strategy_key": "breakout_strategy", "sharpe_ratio": 0.3,
             "num_trades": 25},
        ]
        M = np.array([
            [1.0, 1.1, 0.9, 1.0, 1.2, 0.8],
            [0.9, 1.0, 1.1, 1.0, 0.8, 1.2],
        ])
        report = run_empirical_benchmark(returns_matrix=M,
                                         probe_metrics=probe_metrics)
        assert report["pbo"]["pbo"] is not None
        assert report["dsr"]["dsr"] is not None
        assert report["dsr"]["best_strategy"] == "grid_strategy"
        assert "rf_calibration" in report  # empty points when no model given

    def test_missing_pieces_are_honest_none(self):
        report = run_empirical_benchmark()
        assert report["pbo"]["pbo"] is None
        assert report["dsr"]["dsr"] is None
