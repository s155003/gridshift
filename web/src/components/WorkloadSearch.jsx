import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Search, Loader2, Sparkles, KeyRound } from "lucide-react";
import { EXAMPLES, parseWorkload } from "../lib/parseWorkload.js";
import { getStoredKey, parseWithClaude, setStoredKey } from "../lib/claudeParse.js";

/* Type what you are running instead of picking from a menu.
 *
 * The local rules parse it instantly with no key. If the reader has supplied
 * their own Anthropic key, Claude parses it instead and usually does better on
 * unusual phrasings. Either way the result is a job spec, and every number
 * downstream still comes from the deterministic scheduler.
 */
export default function WorkloadSearch({ horizon, onParsed, parsed }) {
  const [text, setText] = useState("charge my EV overnight");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [keyOpen, setKeyOpen] = useState(false);
  const [key, setKey] = useState(() => getStoredKey());
  const abortRef = useRef(null);

  // Parse once on mount so the page arrives with a real schedule.
  useEffect(() => {
    onParsed(parseWorkload("charge my EV overnight", { horizon }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function submit(e) {
    e?.preventDefault();
    const q = text.trim();
    if (!q) return;
    setErr(null);

    // Always take the local result immediately, so the page never waits.
    const local = parseWorkload(q, { horizon });
    onParsed(local);

    if (!key) return;

    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setBusy(true);
    try {
      const better = await parseWithClaude(q, { key, horizon, signal: ctrl.signal });
      if (!ctrl.signal.aborted) onParsed(better);
    } catch (e2) {
      if (e2.name !== "AbortError") setErr(e2.message.replace(/^Anthropic API /, "Claude: "));
    } finally {
      if (!ctrl.signal.aborted) setBusy(false);
    }
  }

  return (
    <div>
      <form onSubmit={submit}>
        <label htmlFor="workload" className="label mb-1.5 block">
          What are you running?
        </label>
        <div className="flex items-center gap-2 rounded-xs border border-rule bg-white px-2.5 py-1.5 focus-within:border-accent">
          <Search className="h-4 w-4 shrink-0 text-ink-2" aria-hidden="true" />
          <input
            id="workload"
            type="text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="charge my EV overnight"
            autoComplete="off"
            className="w-full bg-transparent text-[0.95rem] text-ink outline-none placeholder:text-ink-2/60"
          />
          {busy && <Loader2 className="h-4 w-4 shrink-0 animate-spin text-accent" aria-label="parsing" />}
        </div>
        <button
          type="submit"
          className="mt-2 w-full rounded-xs border border-ink bg-ink py-1.5 text-[0.86rem] font-semibold text-white transition-colors hover:bg-accent hover:border-accent"
        >
          Schedule it
        </button>
      </form>

      <div className="mt-2.5 flex flex-wrap gap-1">
        {EXAMPLES.slice(0, 4).map((ex) => (
          <button
            key={ex}
            type="button"
            onClick={() => {
              setText(ex);
              onParsed(parseWorkload(ex, { horizon }));
            }}
            className="rounded-xs border border-rule bg-white px-2 py-0.5 text-[0.72rem] text-ink-2 transition-colors hover:border-accent hover:text-ink"
          >
            {ex}
          </button>
        ))}
      </div>

      {/* What it understood, so an assumption is visible rather than silent. */}
      <AnimatePresence initial={false}>
        {parsed && (
          <motion.div
            key={parsed.job.name + parsed.source}
            initial={{ opacity: 0, y: -3 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            className="mt-3 border-t border-rule pt-2 text-[0.78rem] text-ink-2"
          >
            <p className="m-0">
              Read as <b className="text-ink">{parsed.job.name}</b>,{" "}
              <span className="tnum">{parsed.job.durationHours}h</span> at{" "}
              <span className="tnum">{parsed.job.powerKw} kW</span>, finishing within{" "}
              <span className="tnum">{parsed.job.deadlineIndex}h</span>,{" "}
              {parsed.job.interruptible ? "splittable" : "in one block"}.
              {parsed.source === "claude" && (
                <span className="ml-1 inline-flex items-center gap-1 text-accent">
                  <Sparkles className="h-3 w-3" aria-hidden="true" /> Claude
                </span>
              )}
            </p>
            {parsed.notes.length > 0 && (
              <p className="m-0 mt-1 opacity-80">{parsed.notes.join("; ")}.</p>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {err && <p className="mt-2 text-[0.78rem] text-neg">{err}</p>}

      {/* Optional key. Off by default; the page works fully without it. */}
      <button
        type="button"
        onClick={() => setKeyOpen((v) => !v)}
        className="mt-3 inline-flex items-center gap-1.5 text-[0.72rem] text-ink-2 hover:text-accent"
      >
        <KeyRound className="h-3 w-3" aria-hidden="true" />
        {key ? "Claude parsing on" : "Use Claude for parsing"}
      </button>

      {keyOpen && (
        <div className="mt-2 border-l-2 border-rule pl-2.5 text-[0.75rem] text-ink-2">
          <p className="m-0 mb-1.5">
            Optional. Paste your own Anthropic key and unusual phrasings parse better. It is
            kept in this browser and sent only to api.anthropic.com. GridShift works fully
            without it.
          </p>
          <input
            type="password"
            value={key}
            onChange={(e) => {
              setKey(e.target.value.trim());
              setStoredKey(e.target.value.trim());
            }}
            placeholder="sk-ant-..."
            autoComplete="off"
            className="w-full rounded-xs border border-rule bg-white px-2 py-1 text-[0.8rem] text-ink outline-none focus:border-accent"
          />
        </div>
      )}
    </div>
  );
}
