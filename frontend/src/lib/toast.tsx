/* Polite status messages, announced to screen readers through an aria-live region. */
import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

type Tone = "info" | "success" | "error";
interface Toast {
  id: number;
  tone: Tone;
  text: string;
}

const Ctx = createContext<(text: string, tone?: Tone) => void>(() => undefined);
let seq = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((text: string, tone: Tone = "info") => {
    const id = ++seq;
    setItems((xs) => [...xs.slice(-3), { id, tone, text }]);
    window.setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), tone === "error" ? 8000 : 4500);
  }, []);
  const toneClass: Record<Tone, string> = {
    info: "border-border bg-surface text-fg",
    success: "border-success bg-success-soft text-fg",
    error: "border-danger bg-danger-soft text-fg",
  };
  return (
    <Ctx.Provider value={push}>
      {children}
      <div aria-live="polite" role="status" className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2">
        {items.map((t) => (
          <div key={t.id} data-testid="toast" className={`pointer-events-auto rounded-md border px-4 py-3 text-sm shadow-[var(--shadow)] ${toneClass[t.tone]}`}>
            {t.text}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export function useToast() {
  return useContext(Ctx);
}
