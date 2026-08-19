/* Optional upgrade: parse the workload with Claude instead of the local rules.
 *
 * The page is a static site with no backend, so there is nowhere to hide a
 * server-side key. Rather than ship one in client JavaScript, where it would
 * be readable by anyone who opens devtools, this uses a key the reader
 * supplies themselves. It is held in localStorage on their machine and sent
 * only to api.anthropic.com.
 *
 * The local parser in parseWorkload.js stays the default and handles the page
 * on its own. This just does better on unusual phrasings.
 *
 * As with the CLI: Claude decides what the job *is*. It never computes an
 * emissions figure. Every number the reader sees still comes out of
 * scheduler.js.
 */

const KEY_STORAGE = "gridshift.anthropic_key";
const MODEL = "claude-opus-5";
const ENDPOINT = "https://api.anthropic.com/v1/messages";

export function getStoredKey() {
  try {
    return localStorage.getItem(KEY_STORAGE) || "";
  } catch {
    return "";
  }
}

export function setStoredKey(key) {
  try {
    if (key) localStorage.setItem(KEY_STORAGE, key);
    else localStorage.removeItem(KEY_STORAGE);
  } catch {
    /* private mode, or storage disabled. The local parser still works. */
  }
}

const TOOL = {
  name: "schedule_job",
  description:
    "Record the structured parameters of a flexible electrical workload so " +
    "GridShift's optimiser can find its lowest-carbon run window. Call this " +
    "exactly once. Infer sensible values for anything the user did not state.",
  input_schema: {
    type: "object",
    properties: {
      name: { type: "string", description: "Short label, e.g. 'EV charge'." },
      duration_hours: { type: "number", description: "Total run time in hours." },
      power_kw: {
        type: "number",
        description:
          "Average kW while running. If unstated, infer from the appliance: " +
          "home EV charger 7, rapid charger 22, dishwasher 1.2, washing machine 0.7, " +
          "tumble dryer 2.5, oven 2.1, immersion heater 3, heat pump 2, home battery 5, " +
          "consumer GPU 0.7, CI runner 0.3, laptop 0.06, data-centre batch 50.",
      },
      deadline_hours_from_now: {
        type: "number",
        description:
          "Hours from now the job must be FINISHED. 'overnight' or 'before I wake' " +
          "means until about 07:00 local. 'by tomorrow' is 24. No deadline given " +
          "means use the full forecast horizon.",
      },
      interruptible: {
        type: "boolean",
        description:
          "True if it can pause and resume without losing work: EV charging, " +
          "batteries, batch queues, water and space heating, freezers. False if it " +
          "must run unbroken: a dishwasher cycle, a render, a database migration.",
      },
      min_block_hours: { type: "number", description: "Shortest sensible single block. Usually 1, or 2 for heavy warm-up." },
      reasoning: { type: "string", description: "One sentence on anything you inferred rather than read." },
    },
    required: ["name", "duration_hours", "power_kw", "deadline_hours_from_now", "interruptible", "min_block_hours", "reasoning"],
    additionalProperties: false,
  },
};

/**
 * Returns the same shape as parseWorkload, with source: "claude".
 * Throws on any failure so the caller can fall back to the local parser.
 */
export async function parseWithClaude(text, { key, now = new Date(), horizon = 48, signal } = {}) {
  if (!key) throw new Error("no API key");

  const system =
    `You are the intent parser for GridShift, a carbon-aware scheduler. The user ` +
    `describes a flexible electrical workload. Call schedule_job with well-chosen ` +
    `parameters. You do not compute emissions or choose run times; a deterministic ` +
    `optimiser does that from what you provide.\n\n` +
    `Current time: ${now.toISOString()} (${now.toLocaleString([], { weekday: "long" })}).\n` +
    `Forecast horizon: ${horizon} hours.\n\n` +
    `Be decisive. Infer reasonable values rather than refusing, and say what you ` +
    `inferred in reasoning.`;

  const res = await fetch(ENDPOINT, {
    method: "POST",
    signal,
    headers: {
      "content-type": "application/json",
      "x-api-key": key,
      "anthropic-version": "2023-06-01",
      // Required for calls made directly from a browser.
      "anthropic-dangerous-direct-browser-access": "true",
    },
    body: JSON.stringify({
      model: MODEL,
      max_tokens: 1024,
      system,
      tools: [TOOL],
      tool_choice: { type: "tool", name: "schedule_job" },
      messages: [{ role: "user", content: text }],
    }),
  });

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`Anthropic API ${res.status}: ${body.slice(0, 160)}`);
  }

  const data = await res.json();
  const block = (data.content || []).find((b) => b.type === "tool_use");
  if (!block) throw new Error("no tool call in response");
  const a = block.input;

  const duration = Math.max(0.5, Math.min(Number(a.duration_hours) || 4, 24));
  const deadline = Math.min(
    Math.max(Number(a.deadline_hours_from_now) || horizon, Math.ceil(duration)),
    horizon,
  );

  return {
    job: {
      name: String(a.name || "job"),
      durationHours: duration,
      powerKw: Math.max(0.01, Math.min(Number(a.power_kw) || 1, 500)),
      interruptible: Boolean(a.interruptible),
      minBlockHours: Math.max(1, Number(a.min_block_hours) || 1),
      deadlineIndex: Math.round(deadline),
    },
    notes: a.reasoning ? [String(a.reasoning)] : [],
    matched: String(a.name || ""),
    source: "claude",
  };
}
