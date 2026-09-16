import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "cad2ai · Sheet Review Console",
  description:
    "Automated AutoCAD sheet-review findings from the cad2ai pipeline: release gate, severity HUD, layer and dimension analysis.",
  applicationName: "cad2ai review dashboard",
};

export const viewport: Viewport = {
  themeColor: "#05070d",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // Dark is the default; the class lives here so every surface (including the
    // overscroll area) is painted before hydration.
    <html lang="en" className="dark" suppressHydrationWarning>
      <body className="min-h-screen bg-background font-sans text-foreground antialiased">
        {children}
      </body>
    </html>
  );
}
