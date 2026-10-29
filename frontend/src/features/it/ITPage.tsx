import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";
import { ExternalLink, Plus, RefreshCw } from "../../components/icons";
import { Dialog } from "../../components/ui/overlays";
import { Badge, Button, ErrorBox, Field, Input, Notice, PageHeader, Panel, Select, Spinner, Table, Textarea } from "../../components/ui/primitives";
import { api, ApiError, newKey } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { fmtDateTime, humanize } from "../../lib/format";
import { useToast } from "../../lib/toast";
import type { Page, Ticket, ToolResult } from "../../lib/types";

const DEPARTMENTS = ["Finance", "HR", "IT", "Operations", "Sales", "Marketing", "Engineering", "Administration"];
const CATEGORIES = ["network", "hardware", "software", "account", "email", "printer", "other"];
const PRIORITIES = ["low", "medium", "high", "urgent"];
const STATUSES = ["open", "in_progress", "resolved", "closed"];
const NEXT: Record<string, string[]> = { open: ["in_progress", "resolved"], in_progress: ["resolved", "open"], resolved: ["closed", "open"], closed: [] };
const PRIORITY_TONE: Record<string, "neutral" | "warning" | "danger" | "primary"> = { low: "neutral", medium: "primary", high: "warning", urgent: "danger" };

export function StatusPill({ status }: { status: string }) {
  const tone = status === "resolved" || status === "closed" ? "success" : status === "in_progress" ? "primary" : "neutral";
  return <Badge tone={tone}>{humanize(status)}</Badge>;
}

interface Created {
  created: boolean;
  ticket: Ticket;
  confirmation_url: string | null;
  tracking_url: string | null;
}

function NewTicketDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { user } = useAuth();
  const qc = useQueryClient();
  const key = useRef(newKey("it"));
  const [f, setF] = useState({ department: "", category: "network", priority: "medium", summary: "", description: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [done, setDone] = useState<Created | null>(null);
  const m = useMutation({
    mutationFn: () => api<ToolResult<Created>>("/api/it/tickets", { body: f, idempotencyKey: key.current }),
    onSuccess: (r) => {
      setDone(r.result);
      void qc.invalidateQueries({ queryKey: ["it"] });
    },
    onError: (e) => {
      if (e instanceof ApiError && e.fields.length) setErrors(Object.fromEntries(e.fields.map((x) => [x.field, x.message])));
    },
  });
  const set = (k: keyof typeof f, v: string) => setF((s) => ({ ...s, [k]: v }));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (!f.department) errs.department = "Choose your department.";
    if (f.description.trim().length < 10) errs.description = "Describe the problem in at least 10 characters.";
    setErrors(errs);
    if (!Object.keys(errs).length) m.mutate();
  };
  const close = () => {
    onClose();
    setDone(null);
    setF({ department: "", category: "network", priority: "medium", summary: "", description: "" });
    key.current = newKey("it");
  };
  return (
    <Dialog open={open} onOpenChange={(v) => !v && close()} title={done ? "Complaint submitted" : "Raise an IT complaint"}
      description={done ? undefined : `Requested by ${user?.full_name} (${user?.email}).`}
      footer={done ? <Button variant="primary" onClick={close}>Done</Button> : (
        <>
          <Button onClick={close}>Cancel</Button>
          <Button variant="primary" type="submit" form="new-ticket" busy={m.isPending}>Submit complaint</Button>
        </>
      )}>
      {done ? (
        <div className="flex flex-col gap-3" data-testid="ticket-created">
          <p className="text-sm text-muted">Ticket number</p>
          <p className="font-mono text-2xl font-semibold">{done.ticket.number}</p>
          <p className="text-sm">{done.ticket.expected_response}</p>
          {!done.created && <Notice>This complaint was already submitted; this is the same ticket.</Notice>}
          <div className="flex flex-wrap gap-3">
            {done.confirmation_url && (
              <a href={done.confirmation_url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-sm text-primary hover:underline">
                Open the IT Helpdesk confirmation <ExternalLink aria-hidden className="size-3.5" />
              </a>
            )}
            {done.tracking_url && (
              <a href={done.tracking_url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-sm text-primary hover:underline">
                Track this ticket <ExternalLink aria-hidden className="size-3.5" />
              </a>
            )}
          </div>
        </div>
      ) : (
        <form id="new-ticket" onSubmit={submit} className="grid grid-cols-1 gap-4 sm:grid-cols-2" noValidate>
          {m.isError && !Object.keys(errors).length && <div className="sm:col-span-2"><ErrorBox error={m.error} /></div>}
          <Field label="Department" required error={errors.department}>
            {(id, d, inv) => (
              <Select id={id} aria-describedby={d} aria-invalid={inv} value={f.department} onChange={(e) => set("department", e.target.value)}>
                <option value="">Choose...</option>
                {DEPARTMENTS.map((x) => <option key={x}>{x}</option>)}
              </Select>
            )}
          </Field>
          <Field label="Category" required>
            {(id) => (
              <Select id={id} value={f.category} onChange={(e) => set("category", e.target.value)}>
                {CATEGORIES.map((x) => <option key={x} value={x}>{humanize(x)}</option>)}
              </Select>
            )}
          </Field>
          <Field label="Priority" hint="Urgent: you cannot work at all.">
            {(id, d) => (
              <Select id={id} aria-describedby={d} value={f.priority} onChange={(e) => set("priority", e.target.value)}>
                {PRIORITIES.map((x) => <option key={x} value={x}>{humanize(x)}</option>)}
              </Select>
            )}
          </Field>
          <Field label="Summary" hint="Optional, one line.">
            {(id, d) => <Input id={id} aria-describedby={d} value={f.summary} maxLength={200} onChange={(e) => set("summary", e.target.value)} />}
          </Field>
          <div className="sm:col-span-2">
            <Field label="What is wrong?" required error={errors.description}>
              {(id, d, inv) => (
                <Textarea id={id} aria-describedby={d} aria-invalid={inv} value={f.description} maxLength={5000} onChange={(e) => set("description", e.target.value)} />
              )}
            </Field>
          </div>
        </form>
      )}
    </Dialog>
  );
}

function TicketDialog({ number, onClose }: { number: string; onClose: () => void }) {
  const { has } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const [comment, setComment] = useState("");
  const q = useQuery({ queryKey: ["it", "ticket", number], queryFn: () => api<ToolResult<Ticket>>(`/api/it/tickets/${number}`) });
  const refresh = () => void qc.invalidateQueries({ queryKey: ["it"] });
  const status = useMutation({
    mutationFn: (s: string) => api(`/api/it/tickets/${number}/status`, { method: "PATCH", body: { status: s }, idempotencyKey: newKey("st") }),
    onSuccess: () => { toast("Status updated.", "success"); refresh(); },
    onError: (e) => toast(e instanceof ApiError ? e.message : String(e), "error"),
  });
  const add = useMutation({
    mutationFn: () => api(`/api/it/tickets/${number}/comments`, { body: { body: comment }, idempotencyKey: newKey("cm") }),
    onSuccess: () => { setComment(""); toast("Comment added.", "success"); refresh(); },
    onError: (e) => toast(e instanceof ApiError ? e.message : String(e), "error"),
  });
  const t = q.data?.result;
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()} title={t ? `${t.number}: ${t.summary}` : number} wide>
      {q.isLoading && <Spinner />}
      {q.isError && <ErrorBox error={q.error} />}
      {t && (
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill status={t.status} />
            <Badge tone={PRIORITY_TONE[t.priority]}>{humanize(t.priority)} priority</Badge>
            <Badge>{humanize(t.category)}</Badge>
            {t.sla_breached && <Badge tone="danger">Response target missed</Badge>}
          </div>
          <dl className="grid grid-cols-1 gap-x-4 gap-y-1 text-sm sm:grid-cols-[9rem_1fr]">
            <dt className="text-muted">Requester</dt><dd>{t.requester_name} ({t.requester_email})</dd>
            <dt className="text-muted">Department</dt><dd>{t.department}</dd>
            <dt className="text-muted">Created</dt><dd>{fmtDateTime(t.created_at)}</dd>
            <dt className="text-muted">Respond by</dt><dd>{fmtDateTime(t.sla_due_at)}</dd>
            <dt className="text-muted">Assignee</dt><dd>{t.assignee || "Not assigned"}</dd>
          </dl>
          <p className="whitespace-pre-wrap rounded-md border border-border bg-surface-2 p-3 text-sm">{t.description}</p>
          {has("it") && NEXT[t.status]?.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm text-muted">Move to:</span>
              {NEXT[t.status].map((s) => (
                <Button key={s} size="sm" busy={status.isPending && status.variables === s} onClick={() => status.mutate(s)}>
                  {humanize(s)}
                </Button>
              ))}
            </div>
          )}
          <div>
            <h3 className="mb-2 text-sm font-semibold">Comments</h3>
            {!t.comments.length && <p className="text-sm text-muted">No comments yet.</p>}
            <ul className="flex flex-col gap-2">
              {t.comments.filter((c) => !c.internal || has("it")).map((c, i) => (
                <li key={i} className="rounded-md border border-border p-2 text-sm">
                  <p className="text-xs text-muted">{c.author} . {fmtDateTime(c.created_at)} {c.internal && <Badge>Internal</Badge>}</p>
                  <p className="mt-1 whitespace-pre-wrap">{c.body}</p>
                </li>
              ))}
            </ul>
            {t.status !== "closed" && (
              <form className="mt-3 flex flex-col gap-2" onSubmit={(e) => { e.preventDefault(); if (comment.trim()) add.mutate(); }}>
                <label htmlFor="ticket-comment" className="text-sm font-medium">Add a comment</label>
                <Textarea id="ticket-comment" value={comment} onChange={(e) => setComment(e.target.value)} maxLength={5000} />
                <div><Button type="submit" busy={add.isPending} disabled={!comment.trim()}>Post comment</Button></div>
              </form>
            )}
          </div>
        </div>
      )}
    </Dialog>
  );
}

export function ITPage() {
  const { has } = useAuth();
  const [filters, setFilters] = useState({ status: "", priority: "", q: "" });
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const params = new URLSearchParams({ page: String(page), page_size: "25", ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v)) });
  const q = useQuery({ queryKey: ["it", "tickets", params.toString()], queryFn: () => api<ToolResult<Page<Ticket>>>(`/api/it/tickets?${params}`) });
  const data = q.data?.result;
  const staff = has("it");
  return (
    <div>
      <PageHeader
        title={staff ? "IT tickets" : "My IT tickets"}
        description={staff ? "Every complaint raised in the IT Helpdesk, with response targets." : "Raise a complaint and follow its progress. You only see your own tickets."}
        actions={
          <>
            <Button icon={<RefreshCw aria-hidden className="size-4" />} onClick={() => void q.refetch()}>Refresh</Button>
            <Button variant="primary" icon={<Plus aria-hidden className="size-4" />} onClick={() => setCreating(true)}>New complaint</Button>
          </>
        }
      />
      <Panel>
        <form className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-4" onSubmit={(e) => { e.preventDefault(); setPage(1); void q.refetch(); }}>
          <Field label="Search">
            {(id) => <Input id={id} value={filters.q} placeholder="Text or ITK number" onChange={(e) => setFilters((f) => ({ ...f, q: e.target.value }))} />}
          </Field>
          <Field label="Status">
            {(id) => (
              <Select id={id} value={filters.status} onChange={(e) => { setPage(1); setFilters((f) => ({ ...f, status: e.target.value })); }}>
                <option value="">Any</option>
                {STATUSES.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
              </Select>
            )}
          </Field>
          <Field label="Priority">
            {(id) => (
              <Select id={id} value={filters.priority} onChange={(e) => { setPage(1); setFilters((f) => ({ ...f, priority: e.target.value })); }}>
                <option value="">Any</option>
                {PRIORITIES.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
              </Select>
            )}
          </Field>
        </form>
        {q.isLoading && <Spinner />}
        {q.isError && <ErrorBox error={q.error} onRetry={() => void q.refetch()} />}
        {data && (
          <>
            <Table
              caption="IT tickets"
              columns={[
                { key: "number", header: "Ticket", render: (t: Ticket) => <span className="font-mono">{t.number}</span> },
                { key: "summary", header: "Summary" },
                ...(staff ? [{ key: "requester_email", header: "Requester" }] : []),
                { key: "priority", header: "Priority", render: (t: Ticket) => <Badge tone={PRIORITY_TONE[t.priority]}>{humanize(t.priority)}</Badge> },
                { key: "status", header: "Status", render: (t: Ticket) => <StatusPill status={t.status} /> },
                { key: "sla_due_at", header: "Respond by", render: (t: Ticket) => (t.sla_breached ? <span className="text-danger">{fmtDateTime(t.sla_due_at)}</span> : fmtDateTime(t.sla_due_at)) },
              ]}
              rows={data.items}
              rowKey={(t) => t.number}
              onRowClick={(t) => setOpen(t.number)}
              empty="No tickets match. Use New complaint to raise one."
            />
            {(data.pages ?? 1) > 1 && (
              <div className="mt-3 flex items-center justify-end gap-2 text-sm">
                <Button size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</Button>
                <span>Page {data.page} of {data.pages}</span>
                <Button size="sm" disabled={page >= (data.pages ?? 1)} onClick={() => setPage((p) => p + 1)}>Next</Button>
              </div>
            )}
          </>
        )}
      </Panel>
      <NewTicketDialog open={creating} onClose={() => setCreating(false)} />
      {open && <TicketDialog number={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
