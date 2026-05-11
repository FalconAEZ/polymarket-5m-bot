import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

/**
 * cn — tailwind class composition helper.
 * Combines clsx (conditional class names) with tailwind-merge (resolves
 * conflicts like `p-4 p-2` → `p-2`). Used by every panel.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}
