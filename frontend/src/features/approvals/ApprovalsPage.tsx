import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Dialog, TabPanel, Tabs } from "../../components/ui/overlays";
import { Badge, Button, ErrorBox, Input, Notice, PageHeader, Spinner, Table } from "../../components/ui/primitives";
import { api, ApiError } from "../../lib/api";
import { fmtDateTime, humanize } from "../../lib/format";
import { useToast } from "../../lib/toast";
import type { Approval, ApproveResponse, Page } from "../../lib/types";

const STATUS_TONE: Record<string, "neutral" | "primary" | "success" | "warning" | "danger"> = {
  pending: "primary", approved: "neutral", executed: "success", rejected: "neutral", failed: "danger",
};

export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={STATUS_TONE[status] ?? "neutral"}>{humanize(status)}</Badge>;
}

function ApprovalDialog({ a, onClose }: { a: Approval; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [confirmed, setConfirmed] = useState("");
  const [outcome, setOutcome] = useState<ApproveResponse["outcome"] | null>(null);
  const destructive = a.risk === "destructive";
  const decide = useMutation({
    mutationFn: (kind: "approve" | "reject") =>
      api<ApproveResponse | { approval: Approval }>(`/api/approvals/${a.id}/${kind}`, {
        body: kind === "approve" ? { confirm: destructive } : { reason: "Rejected from the approvals list" },
      }),
    onSuccess: (r, kind) => {
      void qc.invalidateQueries({ queryKey: ["approvals"] });
      if (kind === "reject") {
        toast("Rejected. Nothing was changed.");
        onClose();
      } else if ("outcome" in r) {
        setOutcome(r.outcome);
        toast(r.outcome.status === "ok" ? "Approved and done." : `Approved, but it failed: ${r.outcome.error}`, r.outcome.status === "ok" ? "success" : "error");
      }
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : String(e), "error"),
  });
  return (
    <Dialog
      open
      onOpenChange={(v) => !v && onClose()}
      title={a.summary}
      description={`${humanize(a.agent)} agent, tool ${a.tool}. Requested ${fmtDateTime(a.created_at)}.`}
      wide
      footer={
        a.status === "pending" && !outcome ? (
          <>
            <Button onClick={() => decide.mutate("reject")} busy={decide.isPending && decide.variables === "reject"}>
              Reject
            </Button>
            <Button
              variant={destructive ? "danger" : "primary"}
              disabled={destructive && confirmed.trim().toLowerCase() !== "confirm"}
              busy={decide.isPending && decide.variables === "approve"}
              onClick={() => decide.mutate("approve")}
            >
              Approve
            </Button>
          </>
        ) : (
          <Button onClick={onClose}>Close</Button>
        )
      }
    >
      <div className="flex flex-col gap-4">
        <div className="flex items-center gap-2">
          <StatusBadge status={outcome ? (outcome.status === "ok" ? "executed" : "failed") : a.status} />
          {destructive && <Badge tone="danger">Destructive</Badge>}
        </div>
        <div>
          <p className="mb-1 text-sm font-medium">Exactly what will run</p>
          <pre className="max-h-72 overflow-auto rounded-md border border-border bg-surface-2 p-3 font-mono text-xs">
            {JSON.stringify(a.arguments, null, 2)}
          </pre>
        </div>
        {a.status !== "pending" && Object.keys(a.result ?? {}).length > 0 && (
          <div>
            <p className="mb-1 text-sm font-medium">Result</p>
            <pre className="max-h-60 overflow-auto rounded-md border border-border bg-surface-2 p-3 font-mono text-xs">
              {JSON.stringify(a.result, null, 2)}
            </pre>
          </div>
        )}
        {outcome?.result && <Notice>{outcome.result.body}</Notice>}
        {a.status === "pending" && destructive && !outcome && (
          <div className="flex flex-col gap-1.5">
            <label htmlFor="confirm-word" className="text-sm">
              This permanently changes data. Type <span className="font-semibold">confirm</span> to enable Approve.
            </label>
            <Input id="confirm-word" value={confirmed} onChange={(e) => setConfirmed(e.target.value)} className="max-w-xs" autoComplete="off" />
          </div>
        )}
      </div>
    </Dialog>
  );
}

export function ApprovalsPage() {
  const [status, setStatus] = useState("pending");
  const [open, setOpen] = useState<Approval | null>(null);
  const q = useQuery({
    queryKey: ["approvals", status],
    queryFn: () => api<Page<Approval>>(`/api/approvals?page_size=100${status !== "all" ? `&status=${status}` : ""}`),
  });
  const tabs = ["pending", "executed", "rejected", "failed", "all"].map((s) => ({ value: s, label: humanize(s) }));
  return (
    <div>
      <PageHeader
        title="Approvals"
        description="Every email, booking, ticket and record change waits here until a person approves it. Form submissions you make yourself are recorded as approved by you."
      />
      <Tabs value={status} onValueChange={setStatus} tabs={tabs} label="Approval status">
        <TabPanel value={status}>
          {q.isLoading && <Spinner />}
          {q.isError && <ErrorBox error={q.error} onRetry={() => void q.refetch()} />}
          {q.data && (
            <Table
              caption="Approvals"
              columns={[
                { key: "summary", header: "Action", render: (a: Approval) => <span className="font-medium">{a.summary}</span> },
                { key: "agent", header: "Agent", render: (a) => humanize(a.agent) },
                { key: "risk", header: "Risk", render: (a) => (a.risk === "destructive" ? <Badge tone="danger">Destructive</Badge> : <Badge>Write</Badge>) },
                { key: "status", header: "Status", render: (a) => <StatusBadge status={a.status} /> },
                { key: "created_at", header: "Requested", render: (a) => fmtDateTime(a.created_at) },
              ]}
              rows={q.data.items}
              rowKey={(a) => a.id}
              onRowClick={setOpen}
              empty={status === "pending" ? "Nothing is waiting for your approval." : "No approvals here."}
            />
          )}
        </TabPanel>
      </Tabs>
      {open && <ApprovalDialog a={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
