import { useEffect, useRef } from "react";
import { animate, useReducedMotion } from "motion/react";

/* A figure that tweens when it changes.
 *
 * This is motion doing work rather than decoration. When you drag the deadline
 * slider the schedule can jump to a different part of the day, and a number
 * that slides from 195 to 178 tells you it moved and in which direction. A
 * number that simply swaps leaves you unsure whether anything happened at all.
 *
 * Honours prefers-reduced-motion by writing the value straight out.
 */
export default function AnimatedNumber({ value, decimals = 0, className = "" }) {
  const ref = useRef(null);
  const prev = useRef(value);
  const reduce = useReducedMotion();

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    const from = prev.current;
    prev.current = value;

    if (reduce || !Number.isFinite(from) || from === value) {
      node.textContent = value.toFixed(decimals);
      return;
    }
    const controls = animate(from, value, {
      duration: 0.42,
      ease: [0.22, 1, 0.36, 1],
      onUpdate: (v) => {
        node.textContent = v.toFixed(decimals);
      },
    });
    return () => controls.stop();
  }, [value, decimals, reduce]);

  return <span ref={ref} className={`tnum ${className}`}>{value.toFixed(decimals)}</span>;
}
