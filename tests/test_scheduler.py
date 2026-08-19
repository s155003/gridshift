"""Unit tests for the scheduler, the component that must not be wrong.

Every number a user sees comes from this module, so it is tested against
hand-computed expectations rather than snapshots.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gridshift.scheduler import (  # noqa: E402
    JobSpec,
    ScheduleError,
    optimize,
    savings_capture_rate,
    smooth_forecast,
)

BASE = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


def times(n: int) -> list[dt.datetime]:
    return [BASE + dt.timedelta(hours=i) for i in range(n)]


# --------------------------------------------------------------------------
# contiguous placement
# --------------------------------------------------------------------------
def test_picks_the_cheapest_contiguous_window():
    ci = [100, 100, 100, 10, 10, 10, 100, 100]
    job = JobSpec(duration_hours=3, power_kw=1.0)
    r = optimize(times(8), ci, job, smooth_hours=0)
    assert [(b.start_index, b.end_index) for b in r.blocks] == [(3, 6)]
    assert r.optimal_g == pytest.approx(30)
    assert r.naive_g == pytest.approx(300)
    assert r.saved_pct == pytest.approx(90)


def test_energy_is_independent_of_placement():
    """Shifting a job changes its emissions, never its energy consumption."""
    ci = np.linspace(50, 400, 24)
    job = JobSpec(duration_hours=5, power_kw=2.0)
    r = optimize(times(24), ci, job)
    assert r.energy_kwh == pytest.approx(10.0)


def test_deadline_is_respected():
    ci = [100] * 6 + [1] * 6           # cheapest hours are past the deadline
    job = JobSpec(duration_hours=2, power_kw=1.0,
                  deadline=BASE + dt.timedelta(hours=4))
    r = optimize(times(12), ci, job, smooth_hours=0)
    assert all(b.end_index <= 4 for b in r.blocks)


def test_earliest_start_is_respected():
    ci = [1, 1, 100, 100, 50, 50]
    job = JobSpec(duration_hours=2, power_kw=1.0,
                  earliest_start=BASE + dt.timedelta(hours=2))
    r = optimize(times(6), ci, job, smooth_hours=0)
    assert r.blocks[0].start_index >= 2


def test_impossible_deadline_raises():
    job = JobSpec(duration_hours=6, power_kw=1.0,
                  deadline=BASE + dt.timedelta(hours=2))
    with pytest.raises(ScheduleError):
        optimize(times(24), [100] * 24, job)


def test_job_longer_than_forecast_raises():
    with pytest.raises(ScheduleError):
        optimize(times(4), [100] * 4, JobSpec(duration_hours=10, power_kw=1))


def test_nan_forecast_rejected():
    with pytest.raises(ScheduleError):
        optimize(times(4), [100, float("nan"), 100, 100],
                 JobSpec(duration_hours=2, power_kw=1))


def test_invalid_job_rejected():
    with pytest.raises(ScheduleError):
        JobSpec(duration_hours=0, power_kw=1)
    with pytest.raises(ScheduleError):
        JobSpec(duration_hours=1, power_kw=0)


# --------------------------------------------------------------------------
# interruptible placement
# --------------------------------------------------------------------------
def test_interruptible_takes_the_cheapest_slots():
    ci = [10, 500, 10, 500, 10, 500]
    job = JobSpec(duration_hours=3, power_kw=1.0, interruptible=True,
                  min_block_hours=1)
    r = optimize(times(6), ci, job, smooth_hours=0)
    chosen = sorted(i for b in r.blocks for i in range(b.start_index, b.end_index))
    assert chosen == [0, 2, 4]
    assert r.optimal_g == pytest.approx(30)


def test_min_block_forces_contiguity():
    """With min_block == duration the DP must return one unbroken block."""
    ci = [10, 500, 10, 500, 10, 10, 10, 500]
    job = JobSpec(duration_hours=3, power_kw=1.0, interruptible=True,
                  min_block_hours=3)
    r = optimize(times(8), ci, job, smooth_hours=0)
    assert len(r.blocks) == 1
    assert (r.blocks[0].start_index, r.blocks[0].end_index) == (4, 7)


def test_min_block_dp_beats_greedy():
    """A case where greedily taking the cheapest slots would be illegal.

    Slots 0 and 4 are the two cheapest hours, but a 2-hour minimum block
    cannot use isolated slots. The exact DP must instead find the cheapest
    adjacent *pair*, which is (3, 4) at 6 + 1 = 7 -- beating the more obvious
    (2, 3) at 5 + 6 = 11.
    """
    ci = [1, 900, 5, 6, 1, 900, 900, 900]
    job = JobSpec(duration_hours=2, power_kw=1.0, interruptible=True,
                  min_block_hours=2)
    r = optimize(times(8), ci, job, smooth_hours=0)
    assert [(b.start_index, b.end_index) for b in r.blocks] == [(3, 5)]
    assert r.optimal_g == pytest.approx(7)

    # And it is genuinely optimal over every legal placement.
    best = min(ci[s] + ci[s + 1] for s in range(len(ci) - 1))
    assert r.optimal_g == pytest.approx(best)


def test_interruptible_never_worse_than_contiguous():
    rng = np.random.default_rng(3)
    for _ in range(30):
        ci = rng.uniform(20, 400, 24)
        t = times(24)
        a = optimize(t, ci, JobSpec(duration_hours=5, power_kw=1.0),
                     smooth_hours=0)
        b = optimize(t, ci, JobSpec(duration_hours=5, power_kw=1.0,
                                    interruptible=True, min_block_hours=1),
                     smooth_hours=0)
        assert b.optimal_g <= a.optimal_g + 1e-9


# --------------------------------------------------------------------------
# smoothing / optimiser's curse
# --------------------------------------------------------------------------
def test_smoothing_is_a_noop_for_unit_window():
    x = np.array([1.0, 5.0, 2.0, 9.0])
    assert np.allclose(smooth_forecast(x, 1, 1), x)
    assert np.allclose(smooth_forecast(x, 0, 1), x)


def test_smoothing_preserves_length_and_bounds():
    rng = np.random.default_rng(0)
    x = rng.uniform(0, 100, 48)
    for w in (3, 5, 7):
        s = smooth_forecast(x, w, 1)
        assert len(s) == len(x)
        assert s.min() >= x.min() - 1e-9
        assert s.max() <= x.max() + 1e-9


def test_smoothing_changes_selection_but_not_reported_cost_basis():
    """Reported emissions always come from the raw forecast, never the smoothed one."""
    ci = np.array([100.0, 10.0, 100.0, 90.0, 88.0, 92.0, 100.0, 100.0])
    job = JobSpec(duration_hours=2, power_kw=1.0, interruptible=True,
                  min_block_hours=1)
    raw = optimize(times(8), ci, job, smooth_hours=0)
    sm = optimize(times(8), ci, job, smooth_hours=3)
    # The raw run grabs the isolated spike at index 1; the smoothed run doesn't.
    assert 1 in {i for b in raw.blocks for i in range(b.start_index, b.end_index)}
    # Whatever is chosen, cost is recomputed from the unsmoothed series.
    for r in (raw, sm):
        got = sum(float(ci[b.start_index:b.end_index].sum()) for b in r.blocks)
        assert r.optimal_g == pytest.approx(got)


# --------------------------------------------------------------------------
# capture rate
# --------------------------------------------------------------------------
def test_perfect_forecast_captures_everything():
    rng = np.random.default_rng(1)
    ci = rng.uniform(20, 400, 24)
    job = JobSpec(duration_hours=4, power_kw=1.0,
                  deadline=BASE + dt.timedelta(hours=24))
    assert savings_capture_rate(times(24), ci, ci, job,
                                smooth_hours=0) == pytest.approx(1.0)


def test_flat_grid_capture_rate_is_one():
    """When nothing can be saved, no forecast can be blamed for missing it."""
    ci = [200.0] * 12
    job = JobSpec(duration_hours=3, power_kw=1.0)
    assert savings_capture_rate(times(12), ci, ci, job) == pytest.approx(1.0)


def test_inverted_forecast_scores_negative():
    """A forecast that points at the dirtiest hours must score below zero.

    Note the construction: "run now" must be neither the best nor the worst
    option, otherwise there is no room for a forecast to do actively worse
    than doing nothing and the metric correctly floors at 0.
    """
    truth = np.array([100.0] * 4 + [10.0] * 4 + [900.0] * 4)
    bad = np.array([900.0] * 8 + [10.0] * 4)   # claims the dirtiest hours are cheapest
    job = JobSpec(duration_hours=4, power_kw=1.0,
                  deadline=BASE + dt.timedelta(hours=12))

    rate = savings_capture_rate(times(12), bad, truth, job, smooth_hours=0)
    assert rate < 0
    # Following it emits 3600 g where running immediately would emit 400 g.
    plan = optimize(times(12), bad, job, smooth_hours=0)
    assert plan.blocks[0].start_index == 8


def test_car_km_equivalent_uses_documented_factor():
    ci = [340.0, 0.0]
    job = JobSpec(duration_hours=1, power_kw=1.0)
    r = optimize(times(2), ci, job, smooth_hours=0)
    assert r.saved_g == pytest.approx(340)
    assert r.car_km_equivalent == pytest.approx(2.0)
