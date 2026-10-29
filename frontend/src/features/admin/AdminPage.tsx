import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { KeyRound, Plus, RefreshCw } from "../../components/icons";
import { Dialog, TabPanel, Tabs } from "../../components/ui/overlays";
import { Badge, Button, ErrorBox, Field, Input, PageHeader, Panel, SimulatedBadge, Spinner, Stat, Table } from "../../components/ui/primitives";
import { api, ApiError, type User } from "../../lib/api";
import { fmtDateTime, humanize } from "../../lib/format";
import { useToast } from "../../lib/toast";
import type { Page } from "../../lib/types";

const ROLES = ["admin", "hr", "it", "finance", "employee"];

function CreateUserDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [f, setF] = useState({ email: "", full_name: "", password: "", roles: ["employee"] as string[] });
  const [error, setError] = useState<string | null>(null);
  const m = useMutation({
    mutationFn: () => api<User>("/api/admin/users", { body: f }),
    onSuccess: (u) => { toast(`${u.email} was created.`, "success"); void qc.invalidateQueries({ queryKey: ["admin", "users"] }); onClose(); },
    onError: (e) => setError(e instanceof ApiError ? (e.fields.length ? e.fields.map((x) => `${x.field}: ${x.message}`).join("; ") : e.message) : String(e)),
  });
  const toggle = (r: string) => setF((s) => ({ ...s, roles: s.roles.includes(r) ? s.roles.filter((x) => x !== r) : [...s.roles, r] }));
  const submit = (e: FormEvent) => { e.preventDefault(); setError(null); if (!f.roles.length) { setError("Choose at least one role."); return; } m.mutate(); };
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()} title="Create a user" description="Share the password with the person through a separate, safe channel. They can change it in Settings."
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" type="submit" form="create-user" busy={m.isPending}>Create user</Button></>}>
      <form id="create-user" onSubmit={submit} className="flex flex-col gap-4">
        {error && <ErrorBox error={new Error(error)} />}
        <Field label="Full name" required>{(id) => <Input id={id} value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} required />}</Field>
        <Field label="Email" required>{(id) => <Input id={id} type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} required />}</Field>
        <Field label="Initial password" required hint="At least 12 characters, not containing the email name.">
          {(id, d) => <Input id={id} aria-describedby={d} type="password" autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} required />}
        </Field>
        <fieldset>
          <legend className="mb-1.5 text-sm font-medium">Roles</legend>
          <div className="flex flex-wrap gap-4">
            {ROLES.map((r) => (
              <label key={r} className="flex items-center gap-2 text-sm">
                <input type="checkbox" className="size-4 accent-[var(--primary)]" checked={f.roles.includes(r)} onChange={() => toggle(r)} />
                {humanize(r)}
              </label>
            ))}
          </div>
        </fieldset>
      </form>
    </Dialog>
  );
}

function UsersTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const [creating, setCreating] = useState(false);
  const q = useQuery({ queryKey: ["admin", "users"], queryFn: () => api<Page<User>>("/api/admin/users?page_size=100") });
  const unlock = useMutation({
    mutationFn: (id: number) => api<{ message: string }>(`/api/admin/users/${id}/unlock`, { method: "POST" }),
    onSuccess: (r) => { toast(r.message, "success"); void qc.invalidateQueries({ queryKey: ["admin", "users"] }); },
    onError: (e) => toast(e instanceof ApiError ? e.message : String(e), "error"),
  });
  return (
    <Panel title="Users" actions={<Button size="sm" variant="primary" icon={<Plus aria-hidden className="size-4" />} onClick={() => setCreating(true)}>Create user</Button>}>
      {q.isLoading && <Spinner />}
      {q.isError && <ErrorBox error={q.error} />}
      {q.data && (
        <Table
          caption="Users"
          columns={[
            { key: "full_name", header: "Name", render: (u: User) => <span><span className="font-medium">{u.full_name}</span><span className="block text-xs text-muted">{u.email}</span></span> },
            { key: "roles", header: "Roles", render: (u) => <span className="flex flex-wrap gap-1">{u.roles.map((r) => <Badge key={r}>{r}</Badge>)}</span> },
            { key: "last_login_at", header: "Last sign-in", render: (u) => (u.last_login_at ? fmtDateTime(u.last_login_at) : "Never") },
            { key: "state", header: "State", render: (u) => (u.locked ? <Badge tone="danger">Locked</Badge> : u.is_active ? <Badge tone="success">Active</Badge> : <Badge>Inactive</Badge>) },
            { key: "actions", header: "", className: "text-right", render: (u) => u.locked && (
              <Button size="sm" icon={<KeyRound aria-hidden className="size-4" />} busy={unlock.isPending && unlock.variables === u.id} onClick={() => unlock.mutate(u.id)}>Unlock</Button>
            ) },
          ]}
          rows={q.data.items}
          rowKey={(u) => u.id}
        />
      )}
      {creating && <CreateUserDialog onClose={() => setCreating(false)} />}
    </Panel>
  );
}

interface McpRow { server: string; configured: boolean; reachable: boolean; tools?: string[]; missing?: string[]; error?: string; latency_ms?: number }
interface TaskRow { id: number; queue: string; kind: string; status: string; attempts: number; max_attempts: number; last_error: string; available_at: string; finished_at: string | null }

function SystemTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const mcp = useQuery({ queryKey: ["admin", "mcp"], queryFn: () => api<{ servers: McpRow[] }>("/api/admin/mcp") });
  const queue = useQuery({ queryKey: ["admin", "queue"], queryFn: () => api<{ backend: string; queues: Record<string, Record<string, number>> }>("/api/admin/queue") });
  const dead = useQuery({ queryKey: ["admin", "dead"], queryFn: () => api<{ items: TaskRow[] }>("/api/admin/queue/tasks?status=dead&limit=50") });
  const retry = useMutation({
    mutationFn: (id: number) => api<{ message: string }>(`/api/admin/queue/tasks/${id}/retry`, { method: "POST" }),
    onSuccess: (r) => { toast(r.message, "success"); void qc.invalidateQueries({ queryKey: ["admin"] }); },
    onError: (e) => toast(e instanceof ApiError ? e.message : String(e), "error"),
  });
  const totals = Object.values(queue.data?.queues ?? {}).reduce<Record<string, number>>((acc, q) => {
    for (const [k, v] of Object.entries(q)) acc[k] = (acc[k] ?? 0) + v;
    return acc;
  }, {});
  return (
    <div className="flex flex-col gap-4">
      <Panel title="MCP servers" actions={<Button size="sm" icon={<RefreshCw aria-hidden className="size-4" />} onClick={() => void mcp.refetch()} busy={mcp.isFetching}>Check again</Button>}>
        {mcp.isLoading && <Spinner label="Contacting MCP servers" />}
        {mcp.isError && <ErrorBox error={mcp.error} />}
        {mcp.data && (
          <Table
            caption="MCP servers"
            columns={[
              { key: "server", header: "Server", render: (s: McpRow) => <span className="font-mono">{s.server}</span> },
              { key: "state", header: "State", render: (s) => (s.reachable ? <Badge tone="success">Reachable</Badge> : s.configured ? <Badge tone="danger">Not reachable</Badge> : <Badge tone="warning">Not configured</Badge>) },
              { key: "tools", header: "Tools", render: (s) => (s.tools ? `${s.tools.length}${s.missing?.length ? `, missing ${s.missing.join(", ")}` : ""}` : "") },
              { key: "latency_ms", header: "Latency", render: (s) => (s.latency_ms !== undefined ? `${s.latency_ms} ms` : "") },
              { key: "error", header: "Detail", render: (s) => <span className="text-muted">{s.error ?? ""}</span> },
            ]}
            rows={mcp.data.servers}
            rowKey={(s) => s.server}
          />
        )}
      </Panel>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {["pending", "leased", "done", "dead"].map((k) => <Stat key={k} label={`Queue: ${k}`} value={totals[k] ?? 0} hint={k === "dead" ? "Failed after all retries" : undefined} />)}
      </div>
      <Panel title="Dead tasks">
        {dead.data && (
          <Table
            caption="Dead tasks"
            columns={[
              { key: "id", header: "Task" },
              { key: "kind", header: "Kind" },
              { key: "attempts", header: "Attempts", render: (t: TaskRow) => `${t.attempts} of ${t.max_attempts}` },
              { key: "last_error", header: "Last error", render: (t) => <span className="text-muted">{t.last_error}</span> },
              { key: "actions", header: "", className: "text-right", render: (t) => <Button size="sm" busy={retry.isPending && retry.variables === t.id} onClick={() => retry.mutate(t.id)}>Retry</Button> },
            ]}
            rows={dead.data.items}
            rowKey={(t) => t.id}
            empty="No dead tasks."
          />
        )}
      </Panel>
    </div>
  );
}

interface CallRow { id: number; at: string; agent: string; tool: string; server: string; status: string; error: string; latency_ms: number; approval_id: number | null }

function ToolCallsTab() {
  const [status, setStatus] = useState("");
  const q = useQuery({ queryKey: ["admin", "calls", status], queryFn: () => api<{ items: CallRow[] }>(`/api/admin/tool-calls?limit=200${status ? `&status=${status}` : ""}`) });
  return (
    <Panel title="Tool calls" actions={
      <label className="flex items-center gap-2 text-sm">Status
        <select className="h-8 rounded-md border border-border-strong bg-surface px-2 text-sm" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All</option>
          {["ok", "error", "denied", "approval_required"].map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
        </select>
      </label>
    }>
      {q.isLoading && <Spinner />}
      {q.isError && <ErrorBox error={q.error} />}
      {q.data && (
        <Table
          caption="Tool calls"
          columns={[
            { key: "at", header: "Time", render: (c: CallRow) => fmtDateTime(c.at) },
            { key: "agent", header: "Agent" },
            { key: "tool", header: "Tool", render: (c) => <span className="font-mono text-xs">{c.tool}</span> },
            { key: "status", header: "Status", render: (c) => <Badge tone={c.status === "ok" ? "success" : c.status === "denied" || c.status === "error" ? "danger" : "primary"}>{humanize(c.status)}</Badge> },
            { key: "latency_ms", header: "Latency", render: (c) => `${c.latency_ms} ms` },
            { key: "error", header: "Detail", render: (c) => <span className="text-muted">{c.error}</span> },
          ]}
          rows={q.data.items}
          rowKey={(c) => c.id}
        />
      )}
    </Panel>
  );
}

interface AuditRow { id: number; at: string; actor: string; action: string; target: string; outcome: string; ip: string }

function AuditTab() {
  const [action, setAction] = useState("");
  const q = useQuery({ queryKey: ["admin", "audit", action], queryFn: () => api<Page<AuditRow>>(`/api/admin/audit?page_size=200${action ? `&action=${encodeURIComponent(action)}` : ""}`) });
  return (
    <Panel title="Audit log" actions={
      <span className="w-56"><label htmlFor="audit-filter" className="sr-only">Filter by action</label>
        <Input id="audit-filter" placeholder="Filter, e.g. access.denied" value={action} onChange={(e) => setAction(e.target.value)} className="h-8" /></span>
    }>
      {q.isLoading && <Spinner />}
      {q.isError && <ErrorBox error={q.error} />}
      {q.data && (
        <Table
          caption="Audit log"
          columns={[
            { key: "at", header: "Time", render: (a: AuditRow) => fmtDateTime(a.at) },
            { key: "actor", header: "Who" },
            { key: "action", header: "Action", render: (a) => <span className="font-mono text-xs">{a.action}</span> },
            { key: "target", header: "Target" },
            { key: "outcome", header: "Outcome", render: (a) => <Badge tone={a.outcome === "success" ? "success" : "danger"}>{humanize(a.outcome)}</Badge> },
          ]}
          rows={q.data.items}
          rowKey={(a) => a.id}
        />
      )}
    </Panel>
  );
}

interface OutboxRow { id: number; to: string; subject: string; body: string; purpose: string; simulated: boolean; status: string; created_at: string }

function OutboxTab() {
  const q = useQuery({ queryKey: ["admin", "outbox"], queryFn: () => api<{ items: OutboxRow[] }>("/api/admin/outbox?limit=50") });
  return (
    <Panel title={<span className="flex items-center gap-2 text-sm font-semibold">System email outbox <SimulatedBadge /></span>}>
      <p className="mb-3 text-sm text-muted">Password reset codes and other system emails land here while no mail server is configured. Nothing was sent.</p>
      {q.data && (
        <Table
          caption="Outbox"
          columns={[
            { key: "created_at", header: "Time", render: (o: OutboxRow) => fmtDateTime(o.created_at) },
            { key: "to", header: "To" },
            { key: "subject", header: "Subject" },
            { key: "body", header: "Message", render: (o) => <span className="whitespace-pre-wrap text-muted">{o.body}</span> },
          ]}
          rows={q.data.items}
          rowKey={(o) => o.id}
          empty="The outbox is empty."
        />
      )}
    </Panel>
  );
}

export function AdminPage() {
  const [tab, setTab] = useState("users");
  return (
    <div>
      <PageHeader title="Admin" description="Users, system health, tool calls and the audit log." />
      <Tabs value={tab} onValueChange={setTab} label="Admin sections" tabs={[
        { value: "users", label: "Users" }, { value: "system", label: "System" }, { value: "calls", label: "Tool calls" },
        { value: "audit", label: "Audit log" }, { value: "outbox", label: "Outbox" },
      ]}>
        <TabPanel value="users"><UsersTab /></TabPanel>
        <TabPanel value="system"><SystemTab /></TabPanel>
        <TabPanel value="calls"><ToolCallsTab /></TabPanel>
        <TabPanel value="audit"><AuditTab /></TabPanel>
        <TabPanel value="outbox"><OutboxTab /></TabPanel>
      </Tabs>
    </div>
  );
}
