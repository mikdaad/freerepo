"use client";

import * as React from "react";
import { motion } from "framer-motion";
import { cn, percent } from "@/lib/utils";

interface ConfidenceRingProps {
  /** 0-1, or null when the model did not report one. */
  value: number | null;
  size?: number;
  className?: string;
}

/**
 * The model's self-reported confidence as a radial gauge.
 *
 * The arc animates in on mount (the "data ingestion" feel), and the colour
 * encodes how much that number is worth: a 60 % read on a sheet review is a
 * warning, not a statistic.
 */
export function ConfidenceRing({ value, size = 104, className }: ConfidenceRingProps) {
  const stroke = 8;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const clamped = value === null ? 0 : Math.max(0, Math.min(1, value));
  const tone =
    value === null
      ? "hsl(var(--muted-foreground))"
      : clamped >= 0.85
        ? "hsl(var(--neon-green))"
        : clamped >= 0.6
          ? "hsl(var(--neon-cyan))"
          : clamped >= 0.4
            ? "hsl(var(--neon-amber))"
            : "hsl(var(--neon-red))";

  return (
    <div className={cn("relative shrink-0", className)} style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90" aria-hidden>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="hsl(var(--border) / 0.55)"
          strokeWidth={stroke}
        />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={tone}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: circumference, opacity: 0.35 }}
          animate={{ strokeDashoffset: circumference * (1 - clamped), opacity: 1 }}
          transition={{ duration: 1.15, ease: [0.22, 1, 0.36, 1], delay: 0.15 }}
          style={{ filter: `drop-shadow(0 0 6px ${tone})` }}
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center">
        <span className="font-mono text-lg font-semibold tabular-nums leading-none">{percent(value)}</span>
        <span className="mt-1 font-mono text-[9px] uppercase tracking-[0.2em] text-muted-foreground">conf</span>
      </div>
      <span className="sr-only">Model confidence {percent(value, 1)}</span>
    </div>
  );
}
