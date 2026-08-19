# Devpost submission: copy and paste

Everything below is ready to paste into the matching Devpost fields.

---

## Project title

**GridShift: run it when the grid is clean**

## Elevator pitch (short description, ~200 chars)

> Grid carbon intensity swings 13.8× across the year. GridShift forecasts that
> curve from weather alone and moves flexible workloads into the cleanest hours,
> cutting CO₂ by up to 40% with no new hardware.

---

## Problem statement

Electricity is not equally dirty all day. On Great Britain's grid over the last
twelve months, carbon intensity ranged from **20 to 282 gCO₂/kWh**, a **13.8×
swing**. The same kilowatt-hour can carry fourteen times the CO₂ depending purely
on *when* you draw it.

A huge share of demand doesn't care when it runs. An EV charging overnight, a model
training job due by morning, a dishwasher, a CI queue, a water heater. These have
a **deadline, not a start time**. Today almost all of it runs whenever it was
switched on, which means a great deal of entirely avoidable CO₂ is emitted for no
benefit to anyone.

The reason carbon-aware scheduling hasn't spread is not that nobody thought of it.
It's a **data problem**: only a handful of grids on Earth publish an open,
real-time carbon-intensity forecast. Great Britain does. California, Texas, India,
and Australia do not. Without a forecast, there is nothing to schedule against.

## Solution overview

GridShift's core insight is that **you do not need a carbon API. You need weather.**
Grid carbon intensity is largely a function of things weather already tells you:
how hard the wind is blowing across the turbine fleet, how much sun is hitting the
panels, and how cold it is (which drives demand).

So GridShift **learns** the mapping *weather → carbon intensity* where ground truth
exists (GB, which publishes an open API), and **transfers** it anywhere on Earth
using free global weather forecasts.

Three pieces:

1. A gradient-boosted model trained on **8,640 hours** of real GB grid data paired
   with real reanalysis weather, forecasting the 48-hour carbon curve.
2. A deterministic optimiser that places a job, respecting its deadline, its power
   draw, and whether it can be paused, into the lowest-emission window.
3. A Claude tool-use layer that turns *"train my model for four hours, done before
   I wake up"* into a structured job spec, and narrates the resulting plan.

Ships as a CLI, a Python library, and a zero-backend web dashboard that runs the
trained trees directly in the browser.

## Results

Chronological train (70%) / validation (15%) / test (15%) split. Parameters fit on
train, scheduling policy chosen on validation, **every reported number from the
test set, touched once.**

- **29.3% lower MAE** than an hour-of-day climatology baseline (30.81 vs 43.58)
- Real CO₂ reductions measured against actual grid data:
  **−40.5%** data-centre batch · **−31.0%** ML training · **−27.8%** dishwasher ·
  **−22.6%** EV charge · **−6.3%** CI batch
- **Savings capture rate 0.82–0.91** on jobs with real deadline slack (1.0 = perfect
  foresight)
- 41 tests passing, including Python↔JavaScript parity enforced in CI

## AI usage explanation

**Three layers, and the boundary between them is the design.**

**1. Gradient-boosted forecasting model (the core AI).** 400 trees, 31 features,
weather + calendar → gCO₂/kWh. Deliberately **non-autoregressive**: it never sees a
past carbon-intensity value, because a model that needs yesterday's intensity to
predict tomorrow's cannot transfer to a grid that publishes none. Domain physics is
encoded in the features rather than left for the trees to rediscover. There is a real
turbine power curve (cubic ramp from 3.5 m/s cut-in to 12.5 m/s rated, flat to
25 m/s, then zero as turbines feather in a storm), asymmetric heating/cooling
degree-days, and a `dunkelflaute` term for the calm-and-dark conditions that force
gas onto the margin. Permutation importance confirms the model leans on *physical*
signals (`renew_proxy` +6.56 MAE, `dunkelflaute` +3.24) over the clock
(`hour_sin` +3.30), which is what has to be true for the transfer idea to work.

**2. Claude, via strict-schema tool use, for intent.** Natural language → validated
`JobSpec`. It infers what a human would: an EV charger is interruptible, a
dishwasher cycle isn't; a "rack GPU job" draws about 0.7 kW; "before I wake up"
means roughly 07:00. It then explains the finished plan in plain language.

**3. A deterministic optimiser for everything numeric.**

> **Claude never computes a number the user sees.** It doesn't multiply a wattage by
> a carbon intensity, doesn't choose a window, doesn't estimate a saving. Every
> figure comes from a pure function in `scheduler.py`, unit-tested against
> hand-computed expectations.

That split is deliberate and, we'd argue, the right architecture for LLMs in
climate tooling: use them for the fuzzy edges where they're excellent, and never
for arithmetic you want to be able to test. GridShift also runs with **no API key
at all**, since a deterministic parser takes over, so the demo cannot break on a network
call.

## What makes it technically interesting

**We found a bug that made the product actively harmful, and fixed it honestly.**

The first evaluation returned a **negative** savings capture rate (−0.44) for EV
charging: following our advice emitted *more* CO₂ than plugging in immediately.

The cause wasn't a coding error, it was the **optimiser's curse**. A contiguous job
averages the forecast over a window, so errors partly cancel. A *splittable* job
takes an `argmin` over individual hours, and `argmin` over noisy estimates
preferentially selects **the hours the model most under-predicts.**

We hypothesised the fix was pessimism (select on a predicted upper quantile) and
swept quantile regression at 0.5–0.9 against smoothing windows. **The hypothesis was
wrong.** Pessimism barely helped. What worked was low-pass filtering the forecast
*before* selection, so single-hour noise spikes can't win the `argmin` alone. Chosen
on validation, then measured once on test: **EV charging went −0.88 → +0.03**, with
no regression on any other archetype.

We report the fixed EV number as **0.03**, not a tuned-until-pretty figure. It's the
weakest case in the product and it's visible in the README.

## Demo

- **Live dashboard:** https://s155003.github.io/gridshift/
- **Source:** https://github.com/s155003/gridshift
- **Video:** (see `DEMO_SCRIPT.md`)

The dashboard runs the actual trained gradient-boosted trees **client-side**. It
fetches a live weather forecast, evaluates 400 decision trees in JavaScript, and
schedules against the result. There is no backend. A CI test asserts the JavaScript
implementation matches Python to 1e-9.

## Built with

`python` · `scikit-learn` · `numpy` · `pandas` · `anthropic` (Claude tool use) ·
`javascript` · `svg` · `github-actions` · National Grid ESO Carbon Intensity API ·
Open-Meteo API

## Limitations we're upfront about

- Transfer to non-GB regions is **not validated**, because no ground truth exists to check
  it. The shape should transfer (it's physics); the level is a calibration. Labelled
  `transferred` everywhere it appears in the UI.
- Uses **average**, not marginal, carbon intensity. Average is what is openly
  published, but marginal is arguably the correct signal for a shifting decision.
- The EV archetype remains weak (0.03). Where a real carbon API exists, use it, which is what
  GridShift does for GB.
