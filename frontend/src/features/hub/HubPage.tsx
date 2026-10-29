import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Bot, Briefcase, Calendar, ChevronRight, ClipboardCheck, FileText, Lock, Server, Ticket, Wallet } from "../../components/icons";
import { Badge, ErrorBox, Panel, PageHeader, SimulatedBadge, Spinner, Stat } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { fmtDateTime } from "../../lib/format";
import { Link } from "../../lib/router";
import type { Approval, Department, Page } from "../../lib/types";

const DEPT_LINK: Record<string, { to: string; icon: ReactNode }> = {
  hr: { to: "/hr", icon: <Briefcase aria-hidden className="size-5" /> },
  it: { to: "/it", icon: <Ticket aria-hidden className="size-5" /> },
  finance: { to: "/finance", icon: <Wallet aria-hidden className="size-5" /> },
  documents: { to: "/documents", icon: <FileText aria-hidden className="size-5" /> },
  communications: { to: "/communications", icon: <Calendar aria-hidden className="size-5" /> },
};

interface McpRow {
  server: string;
  configured: boolean;
  reachable: boolean;
  tools?: string[];
  error?: string;
  latency_ms?: number;
}

function SystemPanel() {
  const mcp = useQuery({ queryKey: ["admin", "mcp"], queryFn: () => api<{ servers: McpRow[] }>("/api/admin/mcp"), staleTime: 60_000 });
  const queue = useQuery({ queryKey: ["admin", "queue"], queryFn: () => api<{ backend: string; queues: Record<string, Record<string, number>> }>("/api/admin/queue") });
  const dead = Object.values(queue.data?.queues ?? {}).reduce((n, q) => n + (q.dead ?? 0), 0);
  return (
    <Panel title="System" actions={<Link to="/admin" className="text-sm text-primary hover:underline">Open admin</Link>}>
      {mcp.isLoading && <Spinner label="Checking MCP servers" />}
      {mcp.isError && <ErrorBox error={mcp.error} />}
      <ul className="flex flex-col gap-2 text-sm">
        {mcp.data?.servers.map((s) => (
          <li key={s.server} className="flex items-center justify-between gap-3">
            <span className="flex items-center gap-2">
              <Server aria-hidden className="size-4 text-muted" />
              {s.server}
            </span>
            {s.reachable ? (
              <Badge tone="success">Up, {s.tools?.length ?? 0} tools</Badge>
            ) : s.configured ? (
              <Badge tone="danger">Not reachable</Badge>
            ) : (
              <Badge tone="warning">Not configured</Badge>
            )}
          </li>
        ))}
      </ul>
      {queue.data && (
        <p className="mt-3 text-sm text-muted">
          Queue ({queue.data.backend}): {dead ? <span className="font-medium text-danger">{dead} dead task(s)</span> : "no dead tasks"}.
        </p>
      )}
    </Panel>
  );
}

export function HubPage() {
  const { user, has } = useAuth();
  const deps = useQuery({ queryKey: ["departments"], queryFn: () => api<{ items: Department[] }>("/api/departments") });
  const pending = useQuery({ queryKey: ["approvals", "pending"], queryFn: () => api<Page<Approval>>("/api/approvals?status=pending&page_size=5") });
  const convs = useQuery({
    queryKey: ["conversations"],
    queryFn: () => api<{ items: { id: number; title: string; updated_at: string }[] }>("/api/assistant/conversations?page_size=30"),
  });
  const first = user?.full_name.split(/\s+/)[0] ?? "";

  return (
    <div>
      <PageHeader title={`Welcome, ${first}`} description="One workspace. Every department. Handled." />
      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat label="Waiting for your approval" value={pending.data?.total ?? "-"} />
        <Stat label="Your departments" value={deps.data ? deps.data.items.filter((d) => d.accessible).length : "-"} />
        <Stat label="Conversations" value={convs.data?.items.length ?? "-"} />
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <div className="flex flex-col gap-6 xl:col-span-2">
          <Panel title="Departments">
            {deps.isLoading && <Spinner />}
            {deps.isError && <ErrorBox error={deps.error} onRetry={() => void deps.refetch()} />}
            <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2" data-testid="departments">
              {deps.data?.items.map((d) => {
                const link = DEPT_LINK[d.slug];
                const to = d.slug === "it" && !d.accessible ? "/it" : link?.to ?? "/";
                const open = d.accessible || d.slug === "it";
                return (
                  <li key={d.slug}>
                    {open ? (
                      <Link to={to} className="flex h-full items-start gap-3 rounded-md border border-border p-3 hover:bg-surface-2">
                        <span className="text-primary">{link?.icon}</span>
                        <span className="flex-1">
                          <span className="block font-medium">{d.name}</span>
                          <span className="block text-sm text-muted">{d.accessible ? d.description : "Raise and follow your own IT tickets."}</span>
                        </span>
                        <ChevronRight aria-hidden className="mt-1 size-4 text-muted" />
                      </Link>
                    ) : (
                      <div className="flex h-full items-start gap-3 rounded-md border border-dashed border-border p-3" aria-disabled="true">
                        <Lock aria-hidden className="mt-0.5 size-5 text-muted" />
                        <span>
                          <span className="block font-medium text-muted">{d.name}</span>
                          <span className="block text-sm text-muted">{d.reason}</span>
                        </span>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </Panel>

          <Panel title="Ask the assistant" actions={<Link to="/assistant" className="text-sm text-primary hover:underline">Open</Link>}>
            <Link to="/assistant" className="flex items-center gap-3 rounded-md border border-border px-3 py-3 text-sm text-muted hover:bg-surface-2">
              <Bot aria-hidden className="size-5 text-primary" />
              Schedule meetings, raise tickets, answer email, search documents, screen CVs.
            </Link>
            {!!convs.data?.items.length && (
              <ul className="mt-3 flex flex-col gap-1 text-sm">
                {convs.data.items.slice(0, 4).map((c) => (
                  <li key={c.id}>
                    <Link to={`/assistant/${c.id}`} className="flex justify-between gap-3 rounded px-2 py-1 hover:bg-surface-2">
                      <span className="truncate">{c.title}</span>
                      <span className="shrink-0 text-xs text-muted">{fmtDateTime(c.updated_at)}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>

        <div className="flex flex-col gap-6">
          <Panel title="Needs your approval" actions={<Link to="/approvals" className="text-sm text-primary hover:underline">All approvals</Link>}>
            {pending.isLoading && <Spinner />}
            {pending.data && !pending.data.items.length && <p className="text-sm text-muted">Nothing is waiting for you.</p>}
            <ul className="flex flex-col gap-2">
              {pending.data?.items.map((a) => (
                <li key={a.id}>
                  <Link to="/approvals" className="flex items-start gap-2 rounded-md border border-border p-2 text-sm hover:bg-surface-2">
                    <ClipboardCheck aria-hidden className="mt-0.5 size-4 text-primary" />
                    <span className="flex-1">
                      <span className="block">{a.summary}</span>
                      <span className="block text-xs text-muted">{fmtDateTime(a.created_at)}</span>
                    </span>
                    {a.risk === "destructive" && <Badge tone="danger">Destructive</Badge>}
                  </Link>
                </li>
              ))}
            </ul>
          </Panel>
          {has("admin") && <SystemPanel />}
          <Panel title="About sandbox data">
            <p className="text-sm text-muted">
              Until Google and OpenAI are connected, calendar, mail, files and model answers come from a sandbox and are marked{" "}
              <SimulatedBadge />. Nothing in the sandbox reaches real people.
            </p>
          </Panel>
        </div>
      </div>
    </div>
  );
}
