# Design exceptions, GridShift only

`DESIGN.md` governs a reference tool: something you arrive at with a question,
where nothing should render until you ask for it. GridShift is a different
kind of thing. It is a live instrument that also has to argue for its own
existence, because almost nobody arrives already knowing that electricity is
dirtier at some hours than others.

Each exception below suspends a specific rule, for a stated reason. Anything
not listed here still applies, and the palette, the 2px radii, the box-score
tables, the ban on shadows and the ban on em dashes all carry over unchanged.

---

## 1. The landing page explains before it demonstrates

**Rule suspended:** nothing renders until asked for; landing page is a search
box and an empty state.

**Why:** the reference-tool rule assumes a visitor who already has a question.
GridShift's visitor does not. Tested on a real reader, the previous build
opened with "Grid carbon intensity moves by the hour", which leads with an
abstraction and gives a chart and sliders to someone who does not yet know why
they should care. The feedback was direct: *it doesn't make sense what the
product actually does.*

So the page now opens with the problem in plain language and a concrete stake,
then demonstrates, then shows the evidence. The tool still loads live data
immediately, because an empty state on a live monitor destroys the point.

---

## 2. Colour encodes carbon intensity

**Rule suspended:** no rainbow accent colours.

**Why:** the ban is on colour used as decoration, where hue carries no meaning
and the palette drifts into novelty. Here hue is the data. Every hour is
tinted by its gCO2/kWh on a three-stop ramp, so the shape of the argument is
visible before a word is read: the day is not flat, and the clean hours are
somewhere specific.

The ramp is deliberately muted and editorial rather than neon:

| Stop | Colour | Meaning |
|---|---|---|
| clean | `#2f7d5c` | low intensity, run here |
| middle | `#c9a227` | ordinary |
| dirty | `#a83232` | high intensity, avoid (already the DESIGN.md negative) |

It is a sequential scale over one variable, not an accent palette. Nothing in
the interface takes a colour from it except marks that represent intensity.

---

## 3. A serif for display type

**Rule suspended:** system sans only.

**Why:** the original rule targets Inter, Geist and Space Grotesk, which
signal generated rather than designed. That reasoning is sound and it is the
reason for this exception rather than against it. A page set entirely in
system sans with thin rules and grey text is the *other* default that reads as
machine output, and that was the second half of the feedback.

Georgia is on every machine, costs no network request, and reads as
considered. Display type is Georgia; all UI, labels, data and tabular figures
stay system sans. The two never mix inside one element.

---

## 4. Motion may respond to scroll

**Rule suspended:** partially. Decorative animation is still banned outright.

**Why:** on a page that now has sections, a reader needs to know a section has
arrived. Sections fade and rise a few pixels once, on first view. That is
orientation, which is work.

Still banned, and absent: parallax, particle fields, WebGL, animated
gradients, letter-by-letter reveals, anything looping, and anything that
happens because it looks impressive. Everything collapses under
`prefers-reduced-motion`.

---

## What did not change

- Palette, 2px radii, no shadows, no gradients
- Box-score treatment for tables
- Figures inside sentences, never a wall of oversized bare numbers
- Precision behind a click
- Zero em dashes
- Verify by rendering the page and looking at it, not by assuming
  (`node shoot.mjs` in `web/` drives a real browser at the deployed URL)
