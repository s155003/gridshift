/* Precision behind a click. The default view stays uncluttered; the exact
   hour-by-hour figures live in a disclosure. Box-score table treatment:
   sticky header, zebra rows, right-aligned tabular numerals, dense padding. */
export default function ForecastTable({ times, values, blocks }) {
  const chosen = new Set();
  for (const b of blocks) {
    for (let i = b.startIndex; i < b.endIndex; i++) chosen.add(i);
  }

  return (
    <details className="mt-4 border-t border-rule pt-2">
      <summary className="cursor-pointer label text-accent">
        Show the hour-by-hour forecast
      </summary>

      <div className="overflow-x-auto max-h-80 overflow-y-auto mt-2">
        <table className="w-full border-collapse text-[0.82rem]">
          <thead>
            <tr>
              {["Hour", "gCO2/kWh", "Scheduled"].map((h, i) => (
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
            {times.map((t, i) => {
              const on = chosen.has(i);
              return (
                <tr
                  key={i}
                  className={"border-b border-rule-2 hover:bg-hover " + (i % 2 ? "bg-plane-2" : "")}
                >
                  <td className={"px-2.5 py-1.5 tnum " + (on ? "text-pos font-semibold" : "")}>
                    {on && <span className="text-accent">&#9656; </span>}
                    {t.toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" })}
                  </td>
                  <td className={"px-2.5 py-1.5 text-right tnum " + (on ? "text-pos font-semibold" : "")}>
                    {values[i].toFixed(0)}
                  </td>
                  <td className={"px-2.5 py-1.5 text-right tnum " + (on ? "text-pos font-semibold" : "")}>
                    {on ? "yes" : ""}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </details>
  );
}
