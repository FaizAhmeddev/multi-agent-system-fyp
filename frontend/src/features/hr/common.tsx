import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Badge, ErrorBox } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import { humanize } from "../../lib/format";
import type { Card, Progress, TurnResult } from "../../lib/types";
import { CardView } from "../assistant/Cards";

/* Send one request to the assistant and show its cards here (approval cards work as in the Assistant). */
export function useAsk() {
  const qc = useQueryClient();
  const [cards, setCards] = useState<Card[]>([]);
  const m = useMutation({
    mutationFn: (text: string) => api<TurnResult>("/api/assistant/messages", { body: { text } }),
    onSuccess: (r) => {
      setCards(r.cards);
      void qc.invalidateQueries({ queryKey: ["hr"] });
    },
  });
  const view: ReactNode = (
    <div className="mt-4 flex flex-col gap-3" aria-live="polite">
      {m.isError && <ErrorBox error={m.error} />}
      {cards.map((c, i) => (
        <CardView key={`${c.title}-${i}`} card={c} onOption={(o) => m.mutate(o)} />
      ))}
    </div>
  );
  return { ask: (t: string) => m.mutate(t), busy: m.isPending, view, clear: () => setCards([]) };
}

const STATUS_TONE: Record<string, "neutral" | "primary" | "success" | "warning" | "danger"> = {
  offered: "primary", onboarding: "primary", active: "success", notice: "warning", separated: "neutral", withdrawn: "neutral",
  pending: "neutral", in_progress: "primary", done: "success", skipped: "neutral", failed: "danger",
  approved: "success", rejected: "danger", cancelled: "neutral", draft: "neutral", issued: "primary", sent: "success",
  present: "success", late: "warning", absent: "danger", half_day: "warning", leave: "primary", wfh: "primary", holiday: "neutral",
};

export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={STATUS_TONE[status] ?? "neutral"}>{humanize(status)}</Badge>;
}

export function ProgressBar({ p, label }: { p: Progress | undefined; label: string }) {
  if (!p || !p.total) return <span className="text-xs text-muted">-</span>;
  return (
    <span className="flex min-w-28 flex-col gap-1" title={p.overdue.length ? `Overdue: ${p.overdue.join("; ")}` : undefined}>
      <span className="text-xs text-muted">{label} {p.done}/{p.total}{p.overdue.length ? `, ${p.overdue.length} overdue` : ""}</span>
      <span className="h-1.5 w-full overflow-hidden rounded bg-surface-2" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={p.percent}>
        <span className={p.overdue.length ? "block h-full bg-warning" : "block h-full bg-primary"} style={{ width: `${p.percent}%` }} />
      </span>
    </span>
  );
}

export const DEPARTMENTS = ["Engineering", "Finance", "HR", "IT", "Operations", "Sales", "Marketing", "Administration"];

export function money(n: number | null | undefined, cur = "PKR"): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "-";
  return `${cur} ${Number(n).toLocaleString("en-PK", { maximumFractionDigits: 2 })}`;
}
