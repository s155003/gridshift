import { motion, useReducedMotion } from "motion/react";

/* A page section that announces its own arrival.
 *
 * On a page with distinct sections a reader needs to know one has started.
 * This fades and rises a few pixels, once, on first view. That is orientation,
 * which is work. It is not a parallax field and it does not loop.
 * See DESIGN-EXCEPTIONS.md section 4.
 */
export default function Section({ id, label, title, lede, children, className = "" }) {
  const reduce = useReducedMotion();

  return (
    <motion.section
      id={id}
      /* Never animate from fully transparent. If the viewport callback does not
         fire (below the fold in a screenshot, a stalled observer, motion
         failing to load) the section must still be readable rather than
         invisible. 0.35 is enough to register as an arrival. */
      initial={reduce ? false : { opacity: 0.35, y: 14 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0 }}
      transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
      className={`border-t border-rule pt-8 mt-14 ${className}`}
    >
      {label && <p className="label mb-2">{label}</p>}
      {title && <h2 className="display text-[1.7rem] md:text-[2.1rem] m-0 mb-3 max-w-[22ch]">{title}</h2>}
      {lede && <p className="text-ink-2 max-w-[62ch] mb-6">{lede}</p>}
      {children}
    </motion.section>
  );
}
