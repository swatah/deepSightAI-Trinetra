import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * dsai_cn — merges Tailwind CSS class names safely, resolving conflicts.
 * Utility used by all ShadCN/ui component primitives.
 */
export function cn(...dsai_inputs: ClassValue[]) {
  return twMerge(clsx(dsai_inputs));
}
