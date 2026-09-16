/**
 * Ambient "blueprint scanner" backdrop: faint construction grid, a corner
 * bloom, a slow vertical sweep and 1px scanlines. Purely decorative, so it is
 * aria-hidden, sits behind everything (-z-10) and never intercepts clicks.
 */
export function BlueprintBackground() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      <div className="absolute inset-0 bg-blueprint bg-grid opacity-60" />
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_70%_45%_at_50%_-10%,hsl(var(--primary)/0.14),transparent_70%)]" />
      <div className="absolute inset-x-0 top-0 h-56 bg-scan-sweep animate-sweep" />
      <div className="absolute inset-0 opacity-[0.16] mix-blend-soft-light [background-image:repeating-linear-gradient(0deg,transparent_0_2px,hsl(var(--foreground)/0.09)_2px_3px)]" />
      <div className="absolute inset-0 bg-[linear-gradient(to_bottom,transparent_0%,hsl(var(--background)/0.55)_78%,hsl(var(--background)/0.9)_100%)]" />
      {/* corner registration marks, like a plotted sheet */}
      <div className="absolute inset-4 hidden rounded-md border border-dashed border-border/25 lg:block" />
    </div>
  );
}
