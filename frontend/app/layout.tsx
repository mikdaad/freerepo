import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "Hybrid CAD Compliance System",
  description:
    "Municipal setback verification from raw .dwg files — deterministic geometry engines for the math, DeepSeek strictly for semantics and prose.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-background font-sans antialiased">
        {children}
      </body>
    </html>
  );
}
