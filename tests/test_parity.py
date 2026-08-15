"""Cross-language parity: the browser must agree with Python.

The dashboard re-implements the scheduler and the model evaluator in
JavaScript so the published page needs no backend. Two implementations of the
same maths is exactly the situation where they quietly drift apart, so these
tests run the JS under Node and assert it matches Python on random inputs.

Skipped automatically when Node is unavailable.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gridshift.model import CarbonIntensityModel  # noqa: E402
from gridshift.scheduler import JobSpec, optimize  # noqa: E402

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")


def run_node(script: str, payload: dict) -> dict:
    """Run an ES-module snippet with `INPUT` bound to ``payload``."""
    tmp = ROOT / "tests" / "_parity_tmp.mjs"
    tmp.write_text(
        f"const INPUT = {json.dumps(payload)};\n{script}", encoding="utf-8")
    try:
        out = subprocess.run(
            [NODE, str(tmp)], capture_output=True, text=True, timeout=120,
            cwd=str(ROOT))
        if out.returncode != 0:
            raise AssertionError(f"node failed:\n{out.stderr}")
        return json.loads(out.stdout)
    finally:
        tmp.unlink(missing_ok=True)


SCHED_JS = """
import { optimize } from "../web/scheduler.js";
const times = INPUT.intensity.map((_, i) => new Date(Date.UTC(2026, 0, 1, i)));
const out = INPUT.jobs.map((j) => {
  const r = optimize(times, INPUT.intensity, j, { slotHours: 1 });
  return {
    blocks: r.blocks.map((b) => [b.startIndex, b.endIndex]),
    optimalG: r.optimalG, naiveG: r.naiveG, savedPct: r.savedPct,
  };
});
console.log(JSON.stringify(out));
"""


@pytest.mark.parametrize("seed", range(6))
def test_scheduler_matches_javascript(seed: int) -> None:
    rng = np.random.default_rng(seed)
    intensity = np.round(rng.uniform(30, 400, 48), 3)
    base = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    times = [base + dt.timedelta(hours=i) for i in range(48)]

    jobs = [
        dict(name="a", durationHours=4, powerKw=0.7,
             interruptible=False, minBlockHours=1, deadlineIndex=24),
        dict(name="b", durationHours=6, powerKw=7.0,
             interruptible=True, minBlockHours=1, deadlineIndex=14),
        dict(name="c", durationHours=8, powerKw=50.0,
             interruptible=True, minBlockHours=2, deadlineIndex=48),
        dict(name="d", durationHours=3, powerKw=1.2,
             interruptible=True, minBlockHours=3, deadlineIndex=20),
    ]

    js = run_node(SCHED_JS, {"intensity": intensity.tolist(), "jobs": jobs})

    for spec_dict, got in zip(jobs, js):
        job = JobSpec(
            name=spec_dict["name"],
            duration_hours=spec_dict["durationHours"],
            power_kw=spec_dict["powerKw"],
            interruptible=spec_dict["interruptible"],
            min_block_hours=spec_dict["minBlockHours"],
            deadline=times[spec_dict["deadlineIndex"] - 1] + dt.timedelta(hours=1),
            earliest_start=times[0],
        )
        want = optimize(times, intensity, job, slot_hours=1.0)
        assert [[b.start_index, b.end_index] for b in want.blocks] == got["blocks"], (
            f"block mismatch for {job.name}")
        assert want.optimal_g == pytest.approx(got["optimalG"], rel=1e-9)
        assert want.naive_g == pytest.approx(got["naiveG"], rel=1e-9)
        assert want.saved_pct == pytest.approx(got["savedPct"], rel=1e-9)


MODEL_JS = """
import { readFileSync } from "node:fs";
import { predictOne } from "../web/model.js";
const spec = JSON.parse(readFileSync(new URL("../web/model.json", import.meta.url)));
console.log(JSON.stringify(INPUT.rows.map((r) => predictOne(spec, r))));
"""


@pytest.mark.skipif(not (ROOT / "web" / "model.json").exists(),
                    reason="model not exported yet")
def test_model_matches_javascript() -> None:
    """The exported trees must evaluate identically in Node and Python."""
    spec = json.loads((ROOT / "web" / "model.json").read_text(encoding="utf-8"))
    names = spec["features"]

    rng = np.random.default_rng(0)
    rows = []
    for _ in range(25):
        rows.append({n: float(round(rng.uniform(-1.5, 3.0), 4)) for n in names})

    js = run_node(MODEL_JS, {"rows": rows})

    model = CarbonIntensityModel.load(ROOT / "models" / "carbon_model.joblib")
    X = np.array([[r[n] for n in names] for r in rows], dtype=float)
    py = model.predict_from_json_spec(X)

    for a, b in zip(py, js):
        assert a == pytest.approx(b, rel=1e-6, abs=1e-6)
