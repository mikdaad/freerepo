"use client";

import * as React from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";

/**
 * shadcn/ui `tabs` (vendored). Refresh with: `npx shadcn@latest add tabs`
 */
const Tabs = TabsPrimitive.Root;

const TabsList = React.forwardRef<
  React.ComponentRef<typeof TabsPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.List
    ref={ref}
    className={cn(
      "inline-flex h-11 items-center justify-start gap-1 rounded-lg border border-border/60 bg-muted/40 p-1 text-muted-foreground backdrop-blur",
      className,
    )}
    {...props}
  />
));
TabsList.displayName = TabsPrimitive.List.displayName;

interface TabsTriggerProps extends React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger> {
  /** Count of items behind this tab; rendered as a small mono bubble. */
  count?: number;
  /** Highlights a tab that contains blocking items, so it is visible with the panel closed. */
  tone?: "high" | "neutral";
}

const TabsTrigger = React.forwardRef<React.ComponentRef<typeof TabsPrimitive.Trigger>, TabsTriggerProps>(
  ({ className, count, tone = "neutral", children, ...props }, ref) => (
    <TabsPrimitive.Trigger
      ref={ref}
      className={cn(
        "inline-flex items-center gap-2 whitespace-nowrap rounded-md px-3 py-1.5 text-[13px] font-medium tracking-wide transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70 disabled:pointer-events-none disabled:opacity-50 data-[state=active]:bg-primary/15 data-[state=active]:text-foreground data-[state=active]:shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.45),0_0_20px_-8px_hsl(var(--primary)/0.7)]",
        tone === "high" && count && count > 0 ? "text-neon-red" : "",
        className,
      )}
      {...props}
    >
      {children}
      {typeof count === "number" ? (
        <span
          className={cn(
            "rounded-full border px-1.5 py-px font-mono text-[10px] tabular-nums",
            tone === "high" && count > 0
              ? "border-neon-red/50 bg-neon-red/12 text-neon-red"
              : "border-border/70 bg-muted/50 text-muted-foreground",
          )}
        >
          {count}
        </span>
      ) : null}
    </TabsPrimitive.Trigger>
  ),
);
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName;


const TabsContent = React.forwardRef<
  React.ComponentRef<typeof TabsPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    className={cn(
      "mt-4 focus-visible:outline-none data-[state=active]:animate-in data-[state=active]:fade-in-0 data-[state=active]:slide-in-from-bottom-1 data-[state=active]:duration-300",
      className,
    )}
    {...props}
  />
));
TabsContent.displayName = TabsPrimitive.Content.displayName;

export { Tabs, TabsList, TabsTrigger, TabsContent };
