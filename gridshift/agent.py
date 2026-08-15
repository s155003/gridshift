"""The Claude layer: natural language in, a structured job spec out.

Division of labour, stated plainly because it is the point:

* **Claude** turns "train my model for about four hours, needs to be done
  before I wake up, it's a 350W GPU" into a validated :class:`JobSpec`, and
  afterwards writes the human explanation of the plan.
* **:mod:`gridshift.scheduler`** does every calculation. Claude never
  multiplies a wattage by a carbon intensity, never picks a window, and never
  reports a number it computed itself.

That split is deliberate. Language models are excellent at the fuzzy edges of
this problem -- parsing "before I wake up", knowing a dishwasher is
interruptible and a database migration is not -- and are the wrong tool for
arithmetic you want to be able to unit-test. Every figure a user sees came out
of a pure function in ``scheduler.py``.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from dataclasses import dataclass
from typing import Any

from .forecast import Forecast
from .scheduler import JobSpec, ScheduleResult

MODEL = os.environ.get("GRIDSHIFT_MODEL", "claude-opus-5")

# The tool Claude must call. `strict` guarantees the arguments validate against
# this schema, so we never have to defensively parse a half-formed object.
SCHEDULE_TOOL: dict[str, Any] = {
    "name": "schedule_job",
    "description": (
        "Record the structured parameters of a flexible electrical workload so "
        "that GridShift's optimiser can find its lowest-carbon run window. Call "
        "this exactly once. Infer sensible values for anything the user did not "
        "state explicitly, using the guidance in each field description."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Short label for the job, e.g. 'nightly model training'.",
            },
            "duration_hours": {
                "type": "number",
                "description": "Total run time needed, in hours. Must be > 0.",
            },
            "power_kw": {
                "type": "number",
                "description": (
                    "Average power draw in kilowatts while running. Typical values "
                    "if the user does not say: consumer GPU workstation 0.5, "
                    "server/rack GPU job 0.7, laptop 0.05, CI runner 0.3, "
                    "dishwasher 1.2, washing machine 0.7, tumble dryer 2.5, "
                    "home EV charger 7.0, rapid EV charger 22.0, "
                    "immersion heater 3.0, small data-centre batch 50.0."
                ),
            },
            "deadline_hours_from_now": {
                "type": "number",
                "description": (
                    "How many hours from now the job must be FINISHED. Convert "
                    "phrases relative to the current time given in the system "
                    "prompt: 'by 8am', 'overnight', 'before I wake up' (~8 hours "
                    "or until 07:00 local, whichever is later), 'by tomorrow' "
                    "(24), 'this week' (168). If the user gives no deadline, use "
                    "48, the length of the forecast horizon."
                ),
            },
            "interruptible": {
                "type": "boolean",
                "description": (
                    "True if the job can be paused and resumed without losing "
                    "work: EV charging, battery charging, most batch queues, "
                    "water/space heating, freezers. False if it must run in one "
                    "unbroken block: a database migration, a dishwasher cycle, a "
                    "single training run without checkpointing, a video render "
                    "without resume."
                ),
            },
            "min_block_hours": {
                "type": "number",
                "description": (
                    "For interruptible jobs, the shortest sensible single block, "
                    "in hours. Models start-up cost. Use 1 for most things, 2 for "
                    "jobs with heavy warm-up such as a GPU cluster. Ignored when "
                    "interruptible is false."
                ),
            },
            "reasoning": {
                "type": "string",
                "description": (
                    "One sentence on any value you had to infer rather than read "
                    "directly from the user's request, so the user can correct you."
                ),
            },
        },
        "required": [
            "name", "duration_hours", "power_kw", "deadline_hours_from_now",
            "interruptible", "min_block_hours", "reasoning",
        ],
        "additionalProperties": False,
    },
}

SYSTEM = """You are the intent parser for GridShift, a carbon-aware scheduler.

The user describes a flexible electrical workload in plain language. Your only \
job is to call the `schedule_job` tool with well-chosen parameters. You do not \
compute emissions, choose run times, or estimate savings -- a separate \
deterministic optimiser does all of that from the parameters you provide.

Current time: {now:%Y-%m-%d %H:%M} UTC ({dow}).
Forecast horizon available: {horizon} hours ahead.

Be decisive. If the user is vague about power draw or duration, infer a \
reasonable value from the field descriptions rather than refusing, and say what \
you inferred in `reasoning`."""


class AgentUnavailable(RuntimeError):
    """No API key, or the API could not be reached."""


@dataclass
class ParsedJob:
    spec: JobSpec
    reasoning: str
    source: str          # "claude" or "fallback"


# --------------------------------------------------------------------------
# Claude-backed parsing
# --------------------------------------------------------------------------
def _client():
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise AgentUnavailable("anthropic SDK not installed") from exc
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise AgentUnavailable("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic()


def parse_job(text: str, *, now: dt.datetime | None = None,
              horizon_hours: int = 48) -> ParsedJob:
    """Turn a natural-language request into a :class:`JobSpec`.

    Falls back to a deterministic regex parser when no API key is configured,
    so the demo never depends on a network call succeeding.
    """
    now = now or dt.datetime.now(dt.UTC)
    try:
        client = _client()
    except AgentUnavailable:
        return _fallback_parse(text, now=now, horizon_hours=horizon_hours)

    system = SYSTEM.format(now=now, dow=now.strftime("%A"), horizon=horizon_hours)
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            system=system,
            tools=[SCHEDULE_TOOL],
            tool_choice={"type": "tool", "name": "schedule_job"},
            messages=[{"role": "user", "content": text}],
        )
    except Exception:
        return _fallback_parse(text, now=now, horizon_hours=horizon_hours)

    block = next((b for b in resp.content if getattr(b, "type", "") == "tool_use"), None)
    if block is None:
        return _fallback_parse(text, now=now, horizon_hours=horizon_hours)

    args = dict(block.input)
    deadline_h = float(args.get("deadline_hours_from_now") or horizon_hours)
    spec = JobSpec(
        name=str(args.get("name") or "job"),
        duration_hours=float(args["duration_hours"]),
        power_kw=float(args["power_kw"]),
        deadline=now + dt.timedelta(hours=min(deadline_h, horizon_hours)),
        earliest_start=now,
        interruptible=bool(args.get("interruptible", False)),
        min_block_hours=float(args.get("min_block_hours") or 1.0),
    )
    return ParsedJob(spec=spec, reasoning=str(args.get("reasoning", "")),
                     source="claude")


# --------------------------------------------------------------------------
# Deterministic fallback -- keeps the demo alive without an API key
# --------------------------------------------------------------------------
_POWER_HINTS: list[tuple[str, float]] = [
    ("rapid charger", 22.0), ("ev", 7.0), ("car", 7.0),
    ("data centre", 50.0), ("data center", 50.0), ("cluster", 50.0),
    ("dryer", 2.5), ("dishwasher", 1.2), ("washing", 0.7),
    ("immersion", 3.0), ("heater", 3.0), ("heat pump", 2.0),
    ("gpu", 0.7), ("training", 0.7), ("render", 0.5),
    ("ci", 0.3), ("build", 0.3), ("backup", 0.1), ("laptop", 0.05),
]
_INTERRUPTIBLE_HINTS = ("ev", "car", "charge", "batch", "queue", "freezer",
                        "heater", "backup", "sync", "immersion")
_ATOMIC_HINTS = ("dishwasher", "migration", "render", "cycle", "wash")


def _fallback_parse(text: str, *, now: dt.datetime,
                    horizon_hours: int = 48) -> ParsedJob:
    """Regex/keyword parser used when Claude is unavailable.

    Deliberately simple. It exists so that a judge with no API key still sees
    a working product, and so the test-suite has a network-free path.
    """
    low = text.lower()
    notes = []

    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h\b)", low)
    duration = float(m.group(1)) if m else 4.0
    if not m:
        notes.append("assumed 4h duration")

    m = re.search(r"(\d+(?:\.\d+)?)\s*kw", low)
    if m:
        power = float(m.group(1))
    else:
        m = re.search(r"(\d+(?:\.\d+)?)\s*w\b", low)
        if m:
            power = float(m.group(1)) / 1000.0
        else:
            power = next((p for k, p in _POWER_HINTS if k in low), 0.5)
            notes.append(f"assumed {power} kW draw")

    deadline_h = float(horizon_hours)
    m = re.search(r"(?:by|before|within)\s+(\d+)\s*(?:hours?|hrs?|h\b)", low)
    if m:
        deadline_h = float(m.group(1))
    elif "overnight" in low or "wake" in low or "morning" in low:
        deadline_h = 10.0
        notes.append("read 'overnight' as a 10h window")
    elif "tomorrow" in low:
        deadline_h = 24.0
    else:
        m = re.search(r"(?:by|before)\s+(\d{1,2})\s*(am|pm)", low)
        if m:
            hour = int(m.group(1)) % 12 + (12 if m.group(2) == "pm" else 0)
            target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            if target <= now:
                target += dt.timedelta(days=1)
            deadline_h = (target - now).total_seconds() / 3600.0

    interruptible = (any(k in low for k in _INTERRUPTIBLE_HINTS)
                     and not any(k in low for k in _ATOMIC_HINTS))

    # A short, readable label rather than echoing the user's whole sentence.
    _LABELS = [
        ("ev", "EV charge"), ("car", "EV charge"), ("charge", "battery charge"),
        ("dishwasher", "dishwasher"), ("washing", "washing machine"),
        ("dryer", "tumble dryer"), ("train", "model training"),
        ("gpu", "GPU job"), ("render", "render"), ("backup", "backup"),
        ("build", "CI build"), ("ci", "CI build"), ("heater", "water heating"),
        ("immersion", "water heating"), ("batch", "batch job"),
    ]
    name = next((label for k, label in _LABELS if k in low), None)
    if name is None:
        name = " ".join(text.strip().split()[:4]) or "job"

    spec = JobSpec(
        name=name,
        duration_hours=max(duration, 0.5),
        power_kw=max(power, 0.01),
        deadline=now + dt.timedelta(hours=min(deadline_h, horizon_hours)),
        earliest_start=now,
        interruptible=interruptible,
        min_block_hours=1.0,
    )
    return ParsedJob(
        spec=spec,
        reasoning="; ".join(notes) or "parsed without an LLM (no API key set)",
        source="fallback",
    )


# --------------------------------------------------------------------------
# Narration
# --------------------------------------------------------------------------
EXPLAIN_SYSTEM = """You are GridShift's explainer. You are given a schedule that \
a deterministic optimiser has already computed. Write 2-4 short sentences for the \
user.

Rules:
* Every number you mention must be copied exactly from the JSON. Do not compute, \
round differently, or infer any new figure.
* Say when to run it, roughly why the grid is cleaner then (wind, solar, low \
overnight demand), and what the saving is.
* Plain language, no bullet points, no preamble, no markdown headings.
* If the saving is under 5%, say so honestly rather than overselling it."""


def explain(result: ScheduleResult, forecast: Forecast,
            *, parsed: ParsedJob | None = None) -> str:
    """Ask Claude to narrate a schedule the optimiser already produced."""
    payload = {
        "job": result.job.name,
        "region": forecast.region.name,
        "forecast_tier": forecast.tier,
        "run_windows": [
            {"start": b.start.strftime("%a %d %b %H:%M"),
             "end": b.end.strftime("%H:%M")}
            for b in result.blocks
        ],
        "effective_intensity_gco2_per_kwh": round(result.optimal_intensity),
        "if_run_now_gco2_per_kwh": round(result.naive_intensity),
        "energy_kwh": round(result.energy_kwh, 2),
        "co2_saved_kg": round(result.saved_g / 1000, 2),
        "percent_saved": round(result.saved_pct),
        "equivalent_car_km_avoided": round(result.car_km_equivalent),
    }
    try:
        client = _client()
        resp = client.messages.create(
            model=MODEL,
            max_tokens=600,
            system=EXPLAIN_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload, indent=2)}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        if text.strip():
            return text.strip()
    except Exception:
        pass
    return _template_explain(result, forecast)


def _template_explain(result: ScheduleResult, forecast: Forecast) -> str:
    """Deterministic narration, used when Claude is unavailable."""
    if not result.blocks:
        return "No feasible window was found inside the deadline."
    when = " and ".join(f"{b.start:%a %H:%M}-{b.end:%H:%M}" for b in result.blocks)
    if result.saved_pct < 5:
        return (
            f"Run {result.job.name} at {when}. The grid is fairly flat across "
            f"this window, so shifting only saves {result.saved_pct:.0f}% "
            f"({result.saved_g/1000:.2f} kg CO2) -- the deadline leaves little "
            f"room to move."
        )
    return (
        f"Run {result.job.name} at {when}, when {forecast.region.name}'s grid is "
        f"forecast at {result.optimal_intensity:.0f} gCO2/kWh instead of the "
        f"{result.naive_intensity:.0f} you would get starting now. That is a "
        f"{result.saved_pct:.0f}% cut -- {result.saved_g/1000:.2f} kg of CO2 for "
        f"{result.energy_kwh:.1f} kWh of the same work, about "
        f"{result.car_km_equivalent:.0f} km of driving avoided."
    )
