import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** `1200` -> `1,200`; keeps the HUD readable at a glance. */
export function thousands(value: number): string {
  return new Intl.NumberFormat("en-US").format(Math.round(value));
}

/** `0.82` -> `82%` (clamped, so a bad model answer cannot print 140%). */
export function percent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "n/a";
  const clamped = Math.max(0, Math.min(1, value));
  return `${(clamped * 100).toFixed(digits)}%`;
}

/** Truncate on a word boundary where possible, for collapsed accordion rows. */
export function truncate(value: string, max = 132): string {
  const text = value.replace(/\s+/g, " ").trim();
  if (text.length <= max) return text;
  const cut = text.slice(0, max);
  const lastSpace = cut.lastIndexOf(" ");
  return `${(lastSpace > max - 40 ? cut.slice(0, lastSpace) : cut).trimEnd()}…`;
}
