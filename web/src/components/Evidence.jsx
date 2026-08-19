/* The measured results, so the page is not just a claim.
 *
 * Every figure here comes from scripts/train.py on a chronological
 * train/validation/test split, with the test set touched once. The weak
 * numbers are shown next to the strong ones on purpose: a tool that overstates
 * its accuracy in this domain is worse than no tool.
 */

const SAVINGS = [
  { job: "Data-centre batch", slack: "48h", cut: 40.5, capture: 0.82 },
  { job: "ML training run", slack: "24h", cut: 31.0, capture: 0.84 },
  { job: "Dishwasher", slack: "12h", cut: 27.8, capture: 0.91 },
  { job: "EV charge", slack: "14h", cut: 22.6, capture: 0.03 },
  { job: "CI batch", slack: "8h", cut: 6.3, capture: 0.57 },
];

function Stat({ figure, unit, children }) {
  return (
    <div className="border-l-2 border-accent pl-3">
      <p className="m-0 text-[1.6rem] tnum leading-none">
        {figure}
        {unit && <span className="text-ink-2 text-[0.8rem]"> {unit}</span>}
      </p>
      <p className="m-0 mt-1.5 text-[0.85rem] text-ink-2 max-w-[30ch]">{children}</p>
    </div>
  );
}

export default function Evidence() {
  return (
    <>
      <div className="grid gap-6 sm:grid-cols-3 mb-8">
        <Stat figure="8,640" unit="hours">
          of real Great Britain grid data, paired with reanalysis weather, split
          chronologically so the test set is genuinely unseen.
        </Stat>
        <Stat figure="29.3" unit="%">
          lower error than an hour-of-day baseline. That baseline is the honest
          bar, because anyone can tell you the grid is cleaner at 3am.
        </Stat>
        <Stat figure="13.8" unit="x">
          between the cleanest and dirtiest hour of the year, from 20 to 282
          gCO<sub>2</sub>/kWh.
        </Stat>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-[0.85rem]">
          <caption className="text-left label mb-2">
            Measured against what the grid actually did, on the test set
          </caption>
          <thead>
            <tr>
              {["Workload", "Deadline slack", "CO2 cut", "Capture rate"].map((h, i) => (
                <th
                  key={h}
                  scope="col"
                  className={
                    "sticky top-0 bg-plane border-b border-ink label px-2.5 py-1.5 " +
                    (i === 0 ? "text-left" : "text-right")
                  }
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {SAVINGS.map((r, i) => (
              <tr
                key={r.job}
                className={"border-b border-rule-2 hover:bg-hover " + (i % 2 ? "bg-plane-2" : "")}
              >
                <td className="px-2.5 py-1.5">{r.job}</td>
                <td className="px-2.5 py-1.5 text-right tnum">{r.slack}</td>
                <td className="px-2.5 py-1.5 text-right tnum text-pos font-semibold">
                  &minus;{r.cut.toFixed(1)}%
                </td>
                <td
                  className={
                    "px-2.5 py-1.5 text-right tnum " + (r.capture < 0.2 ? "text-neg" : "")
                  }
                >
                  {r.capture.toFixed(2)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-ink-2 text-[0.85rem] mt-3 max-w-[68ch]">
        Capture rate is the fraction of the CO<sub>2</sub> a perfect-foresight
        oracle could have saved. 1.00 is as good as knowing the future, 0.00 is
        no better than running immediately. Savings scale with deadline slack,
        which is why a data-centre batch with two days of room does far better
        than a CI job that must finish inside the workday.
      </p>

      <details className="mt-4 border-t border-rule pt-2">
        <summary className="cursor-pointer label text-accent">
          Show the bug that made this actively harmful
        </summary>
        <div className="mt-3 text-[0.9rem] text-ink-2 max-w-[68ch] space-y-3">
          <p className="m-0">
            The first honest evaluation gave EV charging a capture rate of{" "}
            <b className="text-neg font-semibold tnum">&minus;0.44</b>. Negative.
            Following the advice emitted <i>more</i> CO<sub>2</sub> than plugging
            in immediately.
          </p>
          <p className="m-0">
            The cause was statistical rather than a coding error. A job that must
            run in one block averages the forecast over a window, so errors partly
            cancel. A splittable job takes an <code>argmin</code> over individual
            hours, and <code>argmin</code> over noisy estimates preferentially
            selects the hours the model most <i>under</i>-predicts. Selection
            amplifies exactly the errors you would least like to trust.
          </p>
          <p className="m-0">
            The fix hypothesis was pessimism, selecting on a predicted upper
            quantile. That turned out to be wrong, and it barely helped. What
            worked was low-pass filtering the forecast before selection, so a
            single noisy hour cannot win the <code>argmin</code> alone. Chosen on
            validation, then measured once on test: EV charging went from{" "}
            <b className="text-neg font-semibold tnum">&minus;0.88</b> to{" "}
            <b className="text-pos font-semibold tnum">+0.03</b>, with no
            regression anywhere else.
          </p>
          <p className="m-0">
            It is still the weakest case in the product, and it is shown above
            rather than quietly dropped.
          </p>
        </div>
      </details>
    </>
  );
}
