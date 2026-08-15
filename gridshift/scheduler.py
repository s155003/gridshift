"""The emission-optimal scheduler.

Given a carbon intensity forecast and a description of a flexible workload,
find the run window that emits the least CO2.

This module is pure, deterministic and fully tested. **No language model is
involved in producing any number here.** The LLM layer in :mod:`gridshift.agent`
only translates human intent into a :class:`JobSpec` and narrates the result;
the arithmetic is all here, where it can be unit-tested.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

# Average tailpipe emissions for a petrol car, gCO2e per km (UK DEFRA 2023
# conversion factors, average car, ~0.17 kgCO2e/km). Used only to make totals
# legible to humans -- never in the optimisation itself.
G_CO2_PER_CAR_KM = 170.0


class ScheduleError(ValueError):
    """The job as specified cannot be placed in the available horizon."""


# Chosen on a held-out validation split, never on the test set. See
# scripts/tune_selection.py and the "Optimiser's curse" section of the README.
DEFAULT_SMOOTH_HOURS = 3


def smooth_forecast(x: np.ndarray, window_hours: float,
                    slot_hours: float) -> np.ndarray:
    """Centred moving average with edge padding. ``window <= 1 slot`` is a no-op.

    Why a scheduler low-pass filters its own input: choosing the cheapest
    hours is an ``argmin`` over noisy estimates, and ``argmin`` is biased
    towards wherever the forecast happens to be *too low*. Averaging
    neighbouring hours before selecting removes the single-hour noise spikes
    that win that argmin for the wrong reasons. It costs a little resolution
    and buys a lot of robustness -- on splittable jobs it moved our mean
    savings capture rate from 0.30 to 0.73.
    """
    n = int(round(window_hours / slot_hours))
    if n <= 1 or len(x) < 2:
        return np.asarray(x, dtype=float)
    n = min(n, len(x))
    pad = n // 2
    padded = np.pad(np.asarray(x, dtype=float), (pad, pad), mode="edge")
    kernel = np.ones(n) / n
    return np.convolve(padded, kernel, mode="valid")[:len(x)]


@dataclass
class JobSpec:
    """A flexible electrical load.

    Attributes
    ----------
    name:
        Human label, e.g. "nightly model training".
    duration_hours:
        How long the job needs to run in total.
    power_kw:
        Average electrical draw while running.
    deadline:
        Latest moment the job must be *finished*. ``None`` means "anywhere in
        the forecast horizon".
    earliest_start:
        Earliest moment the job may begin. ``None`` means "now".
    interruptible:
        If True the job may be split into multiple blocks (think: a batch
        queue, an EV charger, a freezer). If False it must run as one
        contiguous block (think: a database migration).
    min_block_hours:
        Minimum length of any single block, for interruptible jobs. Models
        start-up cost -- you do not want a scheduler that toggles your GPU
        cluster every 30 minutes.
    """

    name: str = "job"
    duration_hours: float = 1.0
    power_kw: float = 1.0
    deadline: dt.datetime | None = None
    earliest_start: dt.datetime | None = None
    interruptible: bool = False
    min_block_hours: float = 1.0

    def __post_init__(self) -> None:
        if self.duration_hours <= 0:
            raise ScheduleError("duration_hours must be positive")
        if self.power_kw <= 0:
            raise ScheduleError("power_kw must be positive")


@dataclass
class Block:
    start_index: int
    end_index: int          # exclusive
    start: dt.datetime
    end: dt.datetime

    @property
    def n_slots(self) -> int:
        return self.end_index - self.start_index


@dataclass
class ScheduleResult:
    job: JobSpec
    slot_hours: float
    times: list[dt.datetime]
    intensity: np.ndarray

    blocks: list[Block] = field(default_factory=list)
    energy_kwh: float = 0.0

    optimal_g: float = 0.0        # emissions of the chosen schedule
    naive_g: float = 0.0          # emissions if started immediately
    worst_g: float = 0.0          # emissions of the worst legal placement
    mean_g: float = 0.0           # emissions of an average legal placement

    @property
    def saved_g(self) -> float:
        return self.naive_g - self.optimal_g

    @property
    def saved_pct(self) -> float:
        return 100.0 * self.saved_g / self.naive_g if self.naive_g else 0.0

    @property
    def car_km_equivalent(self) -> float:
        return self.saved_g / G_CO2_PER_CAR_KM

    @property
    def optimal_intensity(self) -> float:
        """Effective gCO2/kWh of the chosen schedule."""
        return self.optimal_g / self.energy_kwh if self.energy_kwh else 0.0

    @property
    def naive_intensity(self) -> float:
        return self.naive_g / self.energy_kwh if self.energy_kwh else 0.0

    @property
    def start(self) -> dt.datetime | None:
        return self.blocks[0].start if self.blocks else None

    def summary(self) -> str:
        if not self.blocks:
            return "no feasible schedule"
        when = ", ".join(f"{b.start:%a %H:%M}-{b.end:%H:%M}" for b in self.blocks)
        return (
            f"{self.job.name}: run {when}  "
            f"({self.optimal_intensity:.0f} vs {self.naive_intensity:.0f} gCO2/kWh, "
            f"-{self.saved_pct:.0f}%, {self.saved_g/1000:.2f} kgCO2 saved)"
        )


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _index_bounds(times: Sequence[dt.datetime], job: JobSpec,
                  slot_hours: float, n_slots: int) -> tuple[int, int]:
    """Return [lo, hi) slot indices the job is allowed to occupy."""
    T = len(times)
    lo = 0
    if job.earliest_start is not None:
        while lo < T and times[lo] < job.earliest_start:
            lo += 1

    hi = T
    if job.deadline is not None:
        hi = 0
        # A slot may be used only if it *ends* at or before the deadline.
        for i, t in enumerate(times):
            if t + dt.timedelta(hours=slot_hours) <= job.deadline:
                hi = i + 1
            else:
                break

    if hi - lo < n_slots:
        raise ScheduleError(
            f"job needs {n_slots} slots ({job.duration_hours:g}h) but only "
            f"{max(hi - lo, 0)} fit between the earliest start and the deadline"
        )
    return lo, hi


def _contiguous(cost: np.ndarray, lo: int, hi: int, n: int) -> tuple[int, float]:
    """Cheapest contiguous run of ``n`` slots inside [lo, hi). Returns (start, cost)."""
    window = cost[lo:hi]
    # Sliding-window sums via a prefix-sum difference: O(T) instead of O(T*n).
    prefix = np.concatenate([[0.0], np.cumsum(window)])
    sums = prefix[n:] - prefix[:-n]
    k = int(np.argmin(sums))
    return lo + k, float(sums[k])


def _interruptible(cost: np.ndarray, lo: int, hi: int, n: int, min_block: int
                   ) -> tuple[list[tuple[int, int]], float]:
    """Cheapest set of blocks totalling ``n`` slots, each block >= ``min_block``.

    With ``min_block == 1`` the optimum is simply the ``n`` cheapest slots. For
    a larger minimum block the greedy choice can be wrong (taking an isolated
    cheap slot may be illegal), so we solve it exactly with a small dynamic
    program over (slot index, slots still to place).

    ``f[t][r]`` = minimum cost of placing ``r`` more slots using only slots
    ``t..hi-1``, with the convention that we are never mid-block at ``t``.
    From each state we may skip slot ``t``, or commit to a block of length
    ``L in [min_block, r]`` starting at ``t``.
    """
    if min_block <= 1:
        window = cost[lo:hi]
        idx = np.argsort(window, kind="stable")[:n]
        chosen = sorted(int(lo + i) for i in idx)
        total = float(sum(cost[i] for i in chosen))
        return _merge_runs(chosen), total

    T = hi - lo
    window = cost[lo:hi]
    prefix = np.concatenate([[0.0], np.cumsum(window)])
    INF = math.inf

    # Only r == 0 or r >= min_block are reachable, but allocating the full
    # table keeps the indexing obvious and the sizes here are tiny.
    f = np.full((T + 1, n + 1), INF)
    choice: dict[tuple[int, int], int] = {}   # (t, r) -> block length, 0 = skip
    f[:, 0] = 0.0

    for t in range(T - 1, -1, -1):
        for r in range(1, n + 1):
            best, best_L = f[t + 1][r], 0          # skip slot t
            max_L = min(r, T - t)
            for L in range(min_block, max_L + 1):
                rem = r - L
                if rem != 0 and rem < min_block:
                    continue                        # would strand an illegal remainder
                cand = (prefix[t + L] - prefix[t]) + f[t + L][rem]
                if cand < best:
                    best, best_L = cand, L
            f[t][r] = best
            choice[(t, r)] = best_L

    if not math.isfinite(f[0][n]):
        raise ScheduleError(
            f"cannot place {n} slots in blocks of at least {min_block} "
            f"within {T} available slots")

    blocks: list[tuple[int, int]] = []
    t, r = 0, n
    while r > 0 and t < T:
        L = choice.get((t, r), 0)
        if L == 0:
            t += 1
            continue
        blocks.append((lo + t, lo + t + L))
        t += L
        r -= L

    # The DP can emit two legal blocks that happen to abut. They are one run of
    # machine time, so present them as one -- otherwise the UI shows a job
    # "stopping" and "restarting" at the same instant.
    slots = [i for a, b in blocks for i in range(a, b)]
    return _merge_runs(sorted(slots)), float(f[0][n])


def _merge_runs(indices: list[int]) -> list[tuple[int, int]]:
    """Collapse a sorted slot list into (start, end) contiguous runs."""
    if not indices:
        return []
    runs, start, prev = [], indices[0], indices[0]
    for i in indices[1:]:
        if i == prev + 1:
            prev = i
            continue
        runs.append((start, prev + 1))
        start = prev = i
    runs.append((start, prev + 1))
    return runs


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------
def optimize(times: Sequence[dt.datetime], intensity: Sequence[float],
             job: JobSpec, *, slot_hours: float = 1.0,
             smooth_hours: float | None = None) -> ScheduleResult:
    """Find the lowest-emission placement of ``job`` against a forecast.

    Parameters
    ----------
    times:
        Start time of each forecast slot, ascending, evenly spaced.
    intensity:
        Carbon intensity in gCO2eq/kWh for each slot.
    job:
        The workload to place.
    slot_hours:
        Duration of one forecast slot.
    smooth_hours:
        Width of the low-pass filter applied to the forecast *before* choosing
        slots, to counter the optimiser's curse (see :func:`smooth_forecast`).
        Defaults to :data:`DEFAULT_SMOOTH_HOURS`; pass ``0`` to disable.

    Notes
    -----
    Selection and scoring deliberately use different signals. Slots are chosen
    using the smoothed forecast, but every emissions number reported back is
    computed from the raw forecast for the slots actually chosen -- smoothing
    is a decision aid, not a change to our best estimate of the answer.
    """
    times = list(times)
    ci = np.asarray(intensity, dtype=float)
    if len(times) != len(ci):
        raise ScheduleError("times and intensity must be the same length")
    if len(ci) == 0:
        raise ScheduleError("empty forecast")
    if np.isnan(ci).any():
        raise ScheduleError("forecast contains NaN")

    n_slots = max(1, int(math.ceil(job.duration_hours / slot_hours - 1e-9)))
    if n_slots > len(ci):
        raise ScheduleError(
            f"job needs {n_slots} slots but the forecast is only {len(ci)} long")

    energy_per_slot = job.power_kw * slot_hours       # kWh
    cost = ci * energy_per_slot                       # gCO2 per slot, for scoring

    w = DEFAULT_SMOOTH_HOURS if smooth_hours is None else smooth_hours
    sel_cost = smooth_forecast(ci, w, slot_hours) * energy_per_slot

    lo, hi = _index_bounds(times, job, slot_hours, n_slots)

    min_block = max(1, int(round(job.min_block_hours / slot_hours)))
    if job.interruptible:
        min_block = min(min_block, n_slots)
        runs, _ = _interruptible(sel_cost, lo, hi, n_slots, min_block)
    else:
        start, _ = _contiguous(sel_cost, lo, hi, n_slots)
        runs = [(start, start + n_slots)]

    # Re-score the chosen slots against the unsmoothed forecast.
    total = float(sum(cost[a:b].sum() for a, b in runs))

    step = dt.timedelta(hours=slot_hours)
    blocks = [Block(a, b, times[a], times[b - 1] + step) for a, b in runs]

    # --- reference points ------------------------------------------------
    # "Naive" = start as early as you are allowed to, which is what happens
    # today when nobody is thinking about the grid.
    naive = float(cost[lo:lo + n_slots].sum())

    # Worst legal contiguous placement, for context in the UI.
    window = cost[lo:hi]
    prefix = np.concatenate([[0.0], np.cumsum(window)])
    sums = prefix[n_slots:] - prefix[:-n_slots]
    worst = float(sums.max())
    mean = float(sums.mean())

    return ScheduleResult(
        job=job,
        slot_hours=slot_hours,
        times=times,
        intensity=ci,
        blocks=blocks,
        energy_kwh=energy_per_slot * n_slots,
        optimal_g=total,
        naive_g=naive,
        worst_g=worst,
        mean_g=mean,
    )


def savings_capture_rate(times: Sequence[dt.datetime],
                         forecast: Sequence[float],
                         truth: Sequence[float],
                         job: JobSpec, *, slot_hours: float = 1.0,
                         smooth_hours: float | None = None) -> float:
    """How much of the *achievable* saving does a given forecast capture?

    This is the metric that actually matters for GridShift, and it is not RMSE.
    A forecast can be biased by 40 gCO2/kWh everywhere and still schedule
    perfectly, because scheduling only depends on getting the *ranking* of
    time slots right.

    Returns a value in (-inf, 1]. 1.0 means the forecast picked a window as
    good as perfect foresight; 0.0 means it did no better than starting
    immediately; negative means it actively made things worse.
    """
    plan = optimize(times, forecast, job, slot_hours=slot_hours,
                    smooth_hours=smooth_hours)
    truth_arr = np.asarray(truth, dtype=float)
    energy_per_slot = job.power_kw * slot_hours

    # Score the forecast-chosen window against what really happened.
    realised = sum(
        float(truth_arr[b.start_index:b.end_index].sum()) * energy_per_slot
        for b in plan.blocks
    )

    # The oracle sees the truth, so it must not be handicapped by smoothing.
    oracle = optimize(times, truth, job, slot_hours=slot_hours, smooth_hours=0)
    best, naive = oracle.optimal_g, oracle.naive_g

    denom = naive - best
    if denom <= 1e-9:
        return 1.0            # nothing was there to save; no forecast can lose
    return (naive - realised) / denom
