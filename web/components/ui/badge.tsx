import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

/**
 * shadcn/ui `badge` (vendored). Refresh with: `npx shadcn@latest add badge`
 * Extended with the severity/verdict variants this dashboard needs.
 */
const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-[0.14em] transition-colors focus:outline-none",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground",
        secondary: "border-border/60 bg-secondary/60 text-secondary-foreground",
        outline: "border-border/70 bg-transparent text-muted-foreground",
        destructive: "border-destructive/40 bg-destructive/15 text-destructive",
        high: "border-neon-red/50 bg-neon-red/12 text-neon-red",
        medium: "border-neon-amber/50 bg-neon-amber/12 text-neon-amber",
        low: "border-neon-cyan/50 bg-neon-cyan/12 text-neon-cyan",
        ok: "border-neon-green/50 bg-neon-green/12 text-neon-green",
        ghost: "border-transparent bg-transparent text-muted-foreground",
      },
      glow: {
        true: "shadow-[0_0_18px_-4px_currentColor]",
        false: "",
      },
    },
    defaultVariants: { variant: "default", glow: false },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, glow, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant, glow }), className)} {...props} />;
}

export { Badge, badgeVariants };
