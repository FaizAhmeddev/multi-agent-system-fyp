import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { CircleCheck, CircleX, ExternalLink, TriangleAlert } from "../../components/icons";
import { Badge, Button, Input, Notice, SimulatedBadge, Table, cx } from "../../components/ui/primitives";
import { api, ApiError } from "../../lib/api";
import { humanize } from "../../lib/format";
import type { ApproveResponse, Card } from "../../lib/types";

const AGENT_NAMES: Record<string, string> = {
  calendar: "Calendar", it: "IT", finance: "Finance", email: "Email", documents: "Documents", hr: "HR", orchestrator: "AgentsMind",
};

function Header({ card }: { card: Card }) {
  return (
    <div className="mb-2 flex flex-wrap items-center gap-2">
      <Badge tone="neutral">{AGENT_NAMES[card.agent] ?? card.agent}</Badge>
      <p className="font-medium">{card.title}</p>
      <SimulatedBadge show={card.simulated} />
      {card.untrusted && (
        <span className="text-xs text-muted" title="This content comes from outside the company. AgentsMind treats it as data, never as instructions.">
          Contains outside content
        </span>
      )}
    </div>
  );
}

function Warnings({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <ul className="mt-3 flex flex-col gap-2">
      {items.map((w) => (
        <li key={w} className="flex gap-2 rounded-md border border-warning bg-warning-soft px-3 py-2 text-sm">
          <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-warning" />
          <span>{w}</span>
        </li>
      ))}
    </ul>
  );
}

function Links({ links }: { links: { label: string; url: string }[] }) {
  if (!links.length) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-3">
      {links.map((l) => (
        <a key={l.url} href={l.url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-sm text-primary hover:underline">
          {l.label}
          <ExternalLink aria-hidden className="size-3.5" />
        </a>
      ))}
    </div>
  );
}

export function ApprovalCard({ card }: { card: Card }) {
  const a = card.approval!;
  const qc = useQueryClient();
  const [typed, setTyped] = useState("");
  const [state, setState] = useState<"pending" | "done" | "rejected" | "failed">("pending");
  const [result, setResult] = useState<ApproveResponse["outcome"] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const destructive = a.risk === "destructive";
  const confirmed = !destructive || !a.confirm_text || typed.trim().toLowerCase() === a.confirm_text.trim().toLowerCase();

  const approve = useMutation({
    mutationFn: () => api<ApproveResponse>(`/api/approvals/${a.id}/approve`, { body: { confirm: destructive } }),
    onSuccess: (r) => {
      setResult(r.outcome);
      setState(r.outcome.status === "ok" ? "done" : "failed");
      if (r.outcome.status !== "ok") setError(r.outcome.error);
      void qc.invalidateQueries({ queryKey: ["approvals"] });
    },
    onError: (e) => {
      setError(e instanceof ApiError ? e.message : String(e));
      if (e instanceof ApiError && e.code === "already_decided") setState("done");
    },
  });
  const reject = useMutation({
    mutationFn: () => api(`/api/approvals/${a.id}/reject`, { body: { reason: "Rejected in the assistant" } }),
    onSuccess: () => {
      setState("rejected");
      void qc.invalidateQueries({ queryKey: ["approvals"] });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : String(e)),
  });

  return (
    <div data-testid="approval-card" className={cx("rounded-lg border bg-surface p-4", destructive ? "border-danger" : "border-border-strong")}>
      <Header card={card} />
      <p className="text-sm text-muted">
        {destructive ? "This permanently changes data. Nothing happens until you approve." : "Nothing happens until you approve."}
      </p>
      <dl className="mt-3 grid grid-cols-1 gap-x-4 gap-y-1.5 text-sm sm:grid-cols-[10rem_1fr]">
        {a.details.map((d) => (
          <div key={d.label} className="contents">
            <dt className="text-muted">{d.label}</dt>
            <dd className="whitespace-pre-wrap break-words">{d.value}</dd>
          </div>
        ))}
      </dl>
      <Warnings items={card.warnings} />
      {state === "pending" && (
        <div className="mt-4 flex flex-col gap-3">
          {destructive && a.confirm_text && (
            <div className="flex flex-col gap-1.5">
              <label htmlFor={`confirm-${a.id}`} className="text-sm">
                Type <span className="font-semibold">{a.confirm_text}</span> to confirm
              </label>
              <Input id={`confirm-${a.id}`} value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className="max-w-sm" />
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <Button
              variant={destructive ? "danger" : "primary"}
              busy={approve.isPending}
              disabled={!confirmed || reject.isPending}
              onClick={() => approve.mutate()}
              icon={<CircleCheck aria-hidden className="size-4" />}
            >
              {destructive ? "Approve and delete" : "Approve"}
            </Button>
            <Button busy={reject.isPending} disabled={approve.isPending} onClick={() => reject.mutate()} icon={<CircleX aria-hidden className="size-4" />}>
              Reject
            </Button>
          </div>
        </div>
      )}
      {error && <div className="mt-3"><Notice tone="danger">{error}</Notice></div>}
      {state === "rejected" && <p className="mt-3 text-sm text-muted" role="status">Rejected. Nothing was changed.</p>}
      {state === "done" && result?.result && (
        <div className="mt-3 rounded-md border border-success bg-success-soft px-3 py-2 text-sm" role="status" data-testid="approval-result">
          <p className="flex items-center gap-2 font-medium">
            <CircleCheck aria-hidden className="size-4 text-success" /> Done
            <SimulatedBadge show={result.result.simulated} />
          </p>
          <p className="mt-1">{result.result.body}</p>
          <Links links={result.result.links} />
        </div>
      )}
    </div>
  );
}

function ResultTable({ card }: { card: Card }) {
  const cols = (card.data.columns as string[] | undefined) ?? [];
  const rows = (card.data.rows as Record<string, unknown>[] | undefined) ?? [];
  if (!cols.length) return null;
  return (
    <div className="mt-3">
      <Table
        columns={cols.map((c) => ({
          key: c,
          header: humanize(c),
          render: (r: Record<string, unknown>) => {
            const v = r[c];
            if (typeof v === "boolean") return v ? "Yes" : "No";
            if (c === "recommendation" && r.needs_human_review) return <Badge tone="warning">Needs human review</Badge>;
            if (c === "subject" && r.suspicious) return (
              <span className="flex items-center gap-2">{String(v)} <Badge tone="warning">Suspicious</Badge></span>
            );
            return v === null || v === undefined ? "" : String(v);
          },
        }))}
        rows={rows}
        rowKey={(r) => String(r.id ?? r.number ?? r.file_id ?? JSON.stringify(r))}
        empty="No rows."
      />
    </div>
  );
}

export function CardView({ card, onOption }: { card: Card; onOption: (text: string) => void }) {
  if (card.kind === "approval" && card.approval) return <ApprovalCard card={card} />;
  const tone =
    card.kind === "error" ? "border-danger" : card.kind === "denied" ? "border-warning" : card.kind === "clarify" ? "border-primary" : "border-border";
  return (
    <div data-testid={`card-${card.kind}`} className={cx("rounded-lg border bg-surface p-4", tone)}>
      <Header card={card} />
      {card.body && <p className="whitespace-pre-wrap break-words text-sm">{card.body}</p>}
      <Warnings items={card.warnings} />
      {card.kind === "result" && <ResultTable card={card} />}
      {card.kind === "fallback" && Array.isArray(card.data.capabilities) && (
        <ul className="mt-2 list-disc pl-5 text-sm text-muted">
          {(card.data.capabilities as string[]).map((c) => <li key={c}>{c}</li>)}
        </ul>
      )}
      {card.options.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {card.options.map((o) => (
            <Button key={o} size="sm" onClick={() => onOption(o)}>
              {o}
            </Button>
          ))}
        </div>
      )}
      <Links links={card.links} />
    </div>
  );
}
