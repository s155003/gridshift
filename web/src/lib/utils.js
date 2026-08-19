import clsx from "clsx";
import { twMerge } from "tailwind-merge";

/** shadcn's class merge helper. Registry components import this from @/lib/utils. */
export function cn(...inputs) {
  return twMerge(clsx(inputs));
}
