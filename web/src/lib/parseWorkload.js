/* Turn "charge my EV overnight" into a schedulable job.
 *
 * This runs entirely in the browser with no key and no network. It is the
 * default path, and it is deliberately good enough to be the only path: the
 * page must work for someone who has never heard of an API key.
 *
 * `parseWithClaude` in claudeParse.js upgrades this when the reader supplies
 * their own key. The two return the same shape, so nothing downstream cares
 * which one ran.
 */

/* Typical draw and duration for things people actually schedule. Power figures
 * are nameplate-ish averages while running, not peak. */
const DEVICES = [
  // transport
  { k: ["ev", "electric car", "electric vehicle", "tesla", "car charger", "charge the car"], label: "EV charge", kw: 7, hours: 6, split: true, block: 1 },
  { k: ["rapid charger", "fast charger", "dc charger"], label: "Rapid EV charge", kw: 22, hours: 2, split: true, block: 1 },
  { k: ["e-bike", "ebike", "scooter"], label: "E-bike charge", kw: 0.1, hours: 4, split: true, block: 1 },
  // laundry and kitchen
  { k: ["dishwasher", "dish washer"], label: "Dishwasher", kw: 1.2, hours: 2, split: false, block: 1 },
  { k: ["washing machine", "laundry", "washer"], label: "Washing machine", kw: 0.7, hours: 2, split: false, block: 1 },
  { k: ["tumble dryer", "dryer", "tumble-dry"], label: "Tumble dryer", kw: 2.5, hours: 1.5, split: false, block: 1 },
  { k: ["oven", "roast", "bake"], label: "Oven", kw: 2.1, hours: 1.5, split: false, block: 1 },
  { k: ["freezer", "fridge"], label: "Freezer pre-cool", kw: 0.4, hours: 3, split: true, block: 1 },
  // heat and water
  { k: ["immersion", "water heater", "hot water", "water heating", "boiler"], label: "Water heating", kw: 3, hours: 3, split: true, block: 1 },
  { k: ["heat pump", "heating", "storage heater"], label: "Heating", kw: 2, hours: 4, split: true, block: 1 },
  { k: ["underfloor"], label: "Underfloor heating", kw: 1.5, hours: 4, split: true, block: 1 },
  { k: ["pool", "hot tub", "jacuzzi"], label: "Pool heating", kw: 3.5, hours: 4, split: true, block: 1 },
  { k: ["dehumidifier"], label: "Dehumidifier", kw: 0.3, hours: 4, split: true, block: 1 },
  // home battery and solar
  { k: ["home battery", "powerwall", "battery storage", "charge the battery"], label: "Home battery", kw: 5, hours: 4, split: true, block: 1 },
  // compute
  { k: ["train", "training", "fine-tune", "finetune", "model run"], label: "ML training run", kw: 0.7, hours: 4, split: false, block: 1 },
  { k: ["gpu", "cuda", "a100", "h100", "4090"], label: "GPU job", kw: 0.7, hours: 4, split: false, block: 1 },
  { k: ["inference", "embedding"], label: "Inference batch", kw: 0.5, hours: 2, split: true, block: 1 },
  { k: ["ci", "build", "compile", "pipeline"], label: "CI build", kw: 0.3, hours: 2, split: false, block: 1 },
  { k: ["render", "export video", "encode", "transcode"], label: "Render", kw: 0.5, hours: 3, split: false, block: 1 },
  { k: ["backup", "sync", "upload", "rsync"], label: "Backup", kw: 0.1, hours: 3, split: true, block: 1 },
  { k: ["data centre", "data center", "cluster", "rack", "fleet"], label: "Data-centre batch", kw: 50, hours: 8, split: true, block: 2 },
  { k: ["server", "vm", "container"], label: "Server job", kw: 0.4, hours: 4, split: true, block: 1 },
  { k: ["mining", "miner", "hashrate"], label: "Mining", kw: 3, hours: 6, split: true, block: 1 },
  { k: ["simulation", "solver", "cfd", "monte carlo"], label: "Simulation", kw: 1.5, hours: 6, split: true, block: 1 },
  { k: ["laptop", "desktop", "pc"], label: "Computer", kw: 0.06, hours: 3, split: true, block: 1 },
  // industrial and misc
  { k: ["kiln", "furnace", "smelter"], label: "Kiln", kw: 8, hours: 6, split: false, block: 1 },
  { k: ["compressor", "pump", "irrigation"], label: "Pump", kw: 4, hours: 4, split: true, block: 1 },
  { k: ["3d print", "printer"], label: "3D print", kw: 0.2, hours: 6, split: false, block: 1 },
  { k: ["vacuum", "roomba"], label: "Robot vacuum", kw: 0.05, hours: 1.5, split: true, block: 1 },
];

const SPLITTABLE_HINTS = ["charge", "charging", "batch", "queue", "backup", "sync", "heat", "heating", "battery", "pre-cool", "top up"];
const ATOMIC_HINTS = ["dishwasher", "cycle", "wash", "render", "migration", "bake", "roast", "print"];

const NUM = "(\\d+(?:\\.\\d+)?)";

/** "6 hours", "6h", "90 minutes", "an hour and a half" */
function parseDuration(s) {
  let m = s.match(new RegExp(`${NUM}\\s*(?:hours?|hrs?|h)\\b`));
  if (m) return { value: +m[1], explicit: true };
  m = s.match(new RegExp(`${NUM}\\s*(?:minutes?|mins?|m)\\b`));
  if (m) return { value: +m[1] / 60, explicit: true };
  if (/\bhalf an hour\b/.test(s)) return { value: 0.5, explicit: true };
  if (/\ban hour and a half\b/.test(s)) return { value: 1.5, explicit: true };
  if (/\ban hour\b/.test(s)) return { value: 1, explicit: true };
  if (/\ball night\b/.test(s)) return { value: 8, explicit: true };
  if (/\ball day\b/.test(s)) return { value: 12, explicit: true };
  return { value: null, explicit: false };
}

/** "700W", "7kW", "3.5 kilowatts", "700 watts" */
function parsePower(s) {
  let m = s.match(new RegExp(`${NUM}\\s*(?:kilowatts?|kw)\\b`));
  if (m) return { value: +m[1], explicit: true };
  m = s.match(new RegExp(`${NUM}\\s*(?:watts?|w)\\b`));
  if (m) return { value: +m[1] / 1000, explicit: true };
  return { value: null, explicit: false };
}

/** Hours from now until the job must be finished. */
function parseDeadline(s, now, horizon) {
  let m = s.match(new RegExp(`(?:by|before|within|in)\\s+${NUM}\\s*(?:hours?|hrs?|h)\\b`));
  if (m) return { value: +m[1], explicit: true, note: null };

  // "by 8am", "before 7 pm", "by 08:30"
  m = s.match(/(?:by|before)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?/);
  if (m) {
    let hour = +m[1];
    const mins = m[2] ? +m[2] : 0;
    const ap = m[3];
    if (ap === "pm" && hour < 12) hour += 12;
    if (ap === "am" && hour === 12) hour = 0;
    const target = new Date(now);
    target.setHours(hour, mins, 0, 0);
    if (target <= now) target.setDate(target.getDate() + 1);
    return { value: (target - now) / 3600e3, explicit: true, note: null };
  }

  if (/\b(overnight|tonight|before i wake|by morning|in the morning)\b/.test(s)) {
    const target = new Date(now);
    target.setHours(7, 0, 0, 0);
    if (target <= now) target.setDate(target.getDate() + 1);
    const h = Math.max(3, (target - now) / 3600e3);
    return { value: h, explicit: true, note: "read as finishing by 07:00" };
  }
  if (/\btomorrow\b/.test(s)) return { value: 24, explicit: true, note: null };
  if (/\b(this week|whenever|no rush|sometime|any time|anytime)\b/.test(s))
    return { value: horizon, explicit: true, note: "no deadline, so the full forecast is available" };
  if (/\b(today|this afternoon|this evening)\b/.test(s)) return { value: 10, explicit: true, note: null };
  if (/\b(asap|now|immediately|urgent)\b/.test(s))
    return { value: 4, explicit: true, note: "read as urgent, so only a short window" };

  return { value: null, explicit: false, note: null };
}

/**
 * @param {string} text  what the reader typed
 * @param {{now?: Date, horizon?: number}} opts
 * @returns {{job: object, notes: string[], matched: string|null, source: "local"}}
 */
export function parseWorkload(text, { now = new Date(), horizon = 48 } = {}) {
  const s = ` ${text.toLowerCase().trim()} `;
  const notes = [];

  const device = DEVICES.find((d) => d.k.some((kw) => s.includes(kw))) ?? null;

  const dur = parseDuration(s);
  const pow = parsePower(s);
  const dl = parseDeadline(s, now, horizon);

  const durationHours = dur.value ?? device?.hours ?? 4;
  if (!dur.explicit) {
    notes.push(device ? `assumed ${durationHours}h, typical for ${device.label.toLowerCase()}`
                      : `assumed ${durationHours}h run time`);
  }

  const powerKw = pow.value ?? device?.kw ?? 1;
  if (!pow.explicit) {
    notes.push(device ? `assumed ${powerKw} kW, typical for ${device.label.toLowerCase()}`
                      : `assumed ${powerKw} kW draw`);
  }

  let deadline = dl.value ?? horizon;
  if (!dl.explicit) notes.push("no deadline given, so the whole forecast is available");
  else if (dl.note) notes.push(dl.note);
  deadline = Math.min(Math.max(deadline, Math.ceil(durationHours)), horizon);

  let interruptible = device?.split ?? false;
  if (SPLITTABLE_HINTS.some((h) => s.includes(h))) interruptible = true;
  if (ATOMIC_HINTS.some((h) => s.includes(h))) interruptible = false;
  if (/\b(can't pause|cannot pause|one go|uninterrupted|in one block)\b/.test(s)) interruptible = false;
  if (/\b(can pause|resumable|checkpoint|splittable)\b/.test(s)) interruptible = true;

  const name = device?.label ?? (text.trim().split(/\s+/).slice(0, 4).join(" ") || "job");

  return {
    job: {
      name,
      durationHours: Math.max(0.5, Math.min(durationHours, 24)),
      powerKw: Math.max(0.01, Math.min(powerKw, 500)),
      interruptible,
      minBlockHours: device?.block ?? 1,
      deadlineIndex: Math.round(deadline),
    },
    notes,
    matched: device?.label ?? null,
    source: "local",
  };
}

/** Shown under the input so people can see what it understands. */
export const EXAMPLES = [
  "charge my EV overnight",
  "run the dishwasher before 7am",
  "train a model for 4 hours on a 700W GPU by tomorrow",
  "8 hour data centre batch, no rush",
  "heat the hot water tank for 3 hours",
  "90 minute tumble dryer cycle tonight",
];
