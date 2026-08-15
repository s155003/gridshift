# Demo video script — 2:30

Record at 1080p. Terminal on a dark theme, font size up. Judges watch a lot of
these, so the hook has to land in the first fifteen seconds.

Optional but recommended before recording:

```bash
setx ANTHROPIC_API_KEY "sk-ant-..."     # so the Claude parse line reads "claude"
```

---

## 0:00 – 0:20 · The hook

**Show:** the live dashboard, GB selected, EV preset.

> "This is the carbon intensity of the British electricity grid for the next
> 48 hours. Same kilowatt-hour — but over the last year it ranged from 20 to 282
> grams of CO₂. A **13.8× swing**, depending only on *when* you draw it.
>
> An enormous amount of demand doesn't care when it runs. Your EV charging
> overnight. A training job due by morning. A dishwasher. These have a deadline,
> not a start time — and today they all just run whenever you switched them on."

## 0:20 – 0:45 · The product

**Do:** drag the deadline slider from 4h out to 14h. The highlighted window jumps to
the clean trough; the big percentage climbs.

> "GridShift finds the lowest-carbon window inside your deadline. Six hours of EV
> charging, done by morning — shifted, that's **[X]% less CO₂**, about
> **[Y] kilograms**, for exactly the same charge. No new hardware. Nothing changes
> except the clock."

## 0:45 – 1:10 · Natural language

**Show:** terminal.

```bash
python -m gridshift.cli schedule "train my model for 4 hours on a 700W GPU, done before 8am"
```

> "Claude parses that sentence into a structured job — duration, power draw,
> deadline, and whether it can be paused. It knows a training run can't be chopped
> in half but an EV charger can.
>
> But Claude doesn't compute *any* of these numbers. Every figure here comes out of
> a deterministic optimiser that's unit-tested against hand-computed answers. The
> language model handles the fuzzy edges; the arithmetic is code you can test."

## 1:10 – 1:40 · The real problem

**Do:** switch region to **California (CAISO)**, then India.

> "Here's the part that makes this more than a dashboard over an existing API.
>
> Britain is one of the only grids on Earth that publishes an open carbon-intensity
> forecast. California doesn't. India doesn't. Australia doesn't. Without a
> forecast, there's nothing to schedule against — which is the real reason
> carbon-aware computing hasn't spread.
>
> So GridShift learns *weather → carbon intensity* where ground truth exists, then
> transfers it anywhere using free global weather. This page is running the actual
> trained model — 400 decision trees — **in your browser**. There is no backend."

**Point at the amber `transferred` badge and the caveat box.**

> "And it tells you when it's extrapolating. That's labelled, not buried."

## 1:40 – 2:10 · The honest bit

**Show:** the README optimiser's-curse section / `assets/optimizer_curse.png`.

> "The first time we evaluated this properly, splittable jobs came back at
> **negative 0.88** — following our advice emitted *more* CO₂ than doing nothing.
>
> That's the optimiser's curse. When you pick the cheapest individual hours, you
> systematically select the hours your model most *under*-predicts. Selection
> amplifies exactly the errors you'd most like to avoid.
>
> We guessed the fix was pessimism. **We were wrong** — that barely helped. What
> worked was smoothing the forecast before selecting. Chosen on a validation split,
> then measured once on test: **negative 0.88 to plus 0.03**, with no regression
> anywhere else."

## 2:10 – 2:30 · Close

**Show:** `pytest tests -q` → `41 passed`.

> "Twelve months of real grid data. Chronological train/validation/test split —
> every number measured on data the model never saw. Forty-one tests, including
> parity tests that run the JavaScript under Node and check it matches Python.
>
> Measured against what the grid actually did: **6 to 40% less CO₂** for work that
> was going to happen anyway.
>
> GridShift. Run it when the grid is clean."

---

## Shot list (if you'd rather cut it together)

1. Dashboard, GB, EV preset — the curve with the highlighted window
2. Deadline slider drag — savings number climbing
3. Region → CAISO — amber `transferred` badge appearing
4. Terminal — `schedule "train my model..."` with the sparkline output
5. Terminal — `gridshift regions`
6. README — the capture-rate table and `optimizer_curse.png`
7. Terminal — `pytest tests -q` → `41 passed`

## Things to say if a judge asks

- **"Isn't this just a wrapper over an API?"** — For Britain, the official feed *is*
  better than our model and we use it. The project exists for the ~95% of the world
  with no such feed, where the only option is to learn the curve from weather.
- **"How do you know the transfer works?"** — We don't, and we say so. The physics
  driving the *shape* is universal; the *level* is calibrated to published annual
  averages. It's labelled `transferred` in the UI and flagged in the README
  limitations. Validating it needs ground truth we don't have.
- **"Why is the EV number so low?"** — Six hours of charging inside a 14-hour window
  is mostly constrained; there's little to capture and our forecast isn't sharp
  enough to capture it. The official GB feed gets 0.86 on identical windows. We left
  it visible instead of dropping the archetype.
