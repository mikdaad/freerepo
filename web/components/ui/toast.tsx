"use client";

import * as React from "react";
import { AnimatePresence, motion } from "framer-motion";
import { CircleCheck, CircleX, Info, TriangleAlert, X } from "lucide-react";
import { cn } from "@/lib/utils";

export type ToastTone = "info" | "success" | "warning" | "error";

export interface ToastItem {
  id: number;
  tone: ToastTone;
  title: string;
  message?: string;
  /** ms; 0 keeps it until dismissed */
  ttl?: number;
}

const TONES: Record<ToastTone, { ring: string; Icon: React.ComponentType<{ className?: string }> }> = {
  info: { ring: "border-neon-cyan/45", Icon: Info },
  success: { ring: "border-neon-green/45", Icon: CircleCheck },
  warning: { ring: "border-neon-amber/50", Icon: TriangleAlert },
  error: { ring: "border-neon-red/55", Icon: CircleX },
};

let nextId = 1;

/** Minimal toast stack (no portal library needed for four toasts). */
export function useToastStack(defaultTtl = 7000) {
  const [toasts, setToasts] = React.useState<ToastItem[]>([]);
  const timers = React.useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());

  const dismiss = React.useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
    const timer = timers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
  }, []);

  const push = React.useCallback(
    (toast: Omit<ToastItem, "id">) => {
      const id = nextId++;
      setToasts((current) => [...current.slice(-3), { ...toast, id }]);
      const ttl = toast.ttl ?? defaultTtl;
      if (ttl > 0) timers.current.set(id, setTimeout(() => dismiss(id), ttl));
      return id;
    },
    [defaultTtl, dismiss],
  );

  React.useEffect(() => {
    const map = timers.current;
    return () => {
      map.forEach((timer) => clearTimeout(timer));
      map.clear();
    };
  }, []);

  return { toasts, push, dismiss };
}

export function ToastViewport({ toasts, onDismiss }: { toasts: ToastItem[]; onDismiss: (id: number) => void }) {
  return (
    <div
      className="no-print pointer-events-none fixed bottom-4 right-4 z-50 flex w-[min(28rem,calc(100vw-2rem))] flex-col gap-2"
      role="region"
      aria-label="Notifications"
    >
      <AnimatePresence initial={false}>
        {toasts.map((toast) => {
          const tone = TONES[toast.tone];
          return (
            <motion.div
              key={toast.id}
              layout
              initial={{ opacity: 0, y: 18, scale: 0.97 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 8, scale: 0.98 }}
              transition={{ duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
              className={cn(
                "pointer-events-auto flex items-start gap-3 rounded-lg border bg-card/95 p-3 shadow-lg backdrop-blur",
                tone.ring,
              )}
              role={toast.tone === "error" ? "alert" : "status"}
            >
              <tone.Icon className="mt-0.5 size-4 shrink-0" />
              <div className="min-w-0 flex-1">
                <p className="text-[13px] font-semibold leading-tight text-foreground">{toast.title}</p>
                {toast.message ? (
                  <p className="mt-1 whitespace-pre-wrap break-words text-[12.5px] leading-snug text-muted-foreground">
                    {toast.message}
                  </p>
                ) : null}
              </div>
              <button
                type="button"
                onClick={() => onDismiss(toast.id)}
                className="rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                aria-label="Dismiss notification"
              >
                <X className="size-3.5" />
              </button>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
