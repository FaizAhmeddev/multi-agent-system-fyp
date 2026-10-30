import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Plus, RefreshCw, Trash2 } from "../../components/icons";
import { Dialog } from "../../components/ui/overlays";
import { Badge, Button, ErrorBox, Field, Input, Notice, Panel, Select, Spinner, Textarea } from "../../components/ui/primitives";
import { api, ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useToast } from "../../lib/toast";

interface Tool { name: string; risk: "read" | "write" | "destructive"; description: string }
interface Conn {
  name: string; title: string; enabled: boolean; transport: "stdio" | "http"; command: string; args: string[]; cwd: string;
  url: string; roles: string[]; keywords: string[]; read_tools: string[]; write_tools: string[]; blocked_tools: string[];
  guess_read_by_name: boolean; description: string; timeout_seconds: number; env: Record<string, string>; headers: Record<string, string>;
  missing_secrets: string[]; state: "connected" | "error" | "disabled" | "not checked"; error: string; tools: Tool[];
}
interface Template {
  name: string; title: string; transport: "stdio" | "http"; command?: string; args?: string[]; url?: string;
  env?: Record<string, string>; headers?: Record<string, string>; keywords?: string[]; description?: string; secrets_help?: string;
}
interface Form {
  name: string; title: string; transport: "stdio" | "http"; command: string; args: string; url: string; env: string;
  headers: string; roles: string[]; keywords: string; description: string; blocked: string; secrets: string; help: string; enabled: boolean;
}

const ROLES = ["employee", "hr", "it", "finance"];
const empty: Form = { name: "", title: "", transport: "stdio", command: "", args: "", url: "", env: "", headers: "", roles: [...ROLES], keywords: "", description: "", blocked: "", secrets: "", help: "", enabled: true };

const pairs = (o?: Record<string, string>) => Object.entries(o ?? {}).map(([k, v]) => `${k}=${v}`).join("\n");
const parsePairs = (s: string) => Object.fromEntries(s.split("\n").map((l) => l.trim()).filter((l) => l.includes("=")).map((l) => [l.slice(0, l.indexOf("=")).trim(), l.slice(l.indexOf("=") + 1).trim()]));
const list = (s: string, sep: RegExp) => s.split(sep).map((x) => x.trim()).filter(Boolean);
const riskTone = (r: Tool["risk"]) => (r === "read" ? "success" : r === "destructive" ? "danger" : "warning");

/* Settings > Connectors (admin): plug in any MCP server; its tools appear in the assistant. */
export function ConnectorsHubPanel() {
  const { has } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["connectors"], queryFn: () => api<{ items: Conn[]; templates: Template[]; file: string }>("/api/connectors"), enabled: has("admin") });
  const [form, setForm] = useState<Form | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const done = (msg: string) => { toast(msg, "success"); void qc.invalidateQueries({ queryKey: ["connectors"] }); };
  const fail = (e: unknown) => toast(e instanceof ApiError ? e.message : String(e), "error");
  const save = useMutation({
    mutationFn: (f: Form) => {
      const body = {
        name: f.name.trim().toLowerCase(), title: f.title, enabled: f.enabled, transport: f.transport, command: f.command,
        args: list(f.args, /\n/), url: f.url, env: parsePairs(f.env), headers: parsePairs(f.headers), roles: f.roles,
        keywords: list(f.keywords, /,/).map((k) => k.toLowerCase()), description: f.description, blocked_tools: list(f.blocked, /,/),
        secrets: parsePairs(f.secrets),
      };
      return editing ? api<Conn>(`/api/connectors/${editing}`, { method: "PUT", body }) : api<Conn>("/api/connectors", { body });
    },
    onSuccess: (c) => { setForm(null); setEditing(null); done(c.state === "connected" ? `${c.title} connected: ${c.tools.length} tool(s).` : `${c.title} saved. ${c.error}`); },
    onError: fail,
  });
  const refresh = useMutation({ mutationFn: (n: string) => api<Conn>(`/api/connectors/${n}/refresh`, { body: {} }), onSuccess: (c) => done(c.state === "connected" ? `${c.title}: ${c.tools.length} tool(s).` : `${c.title}: ${c.error}`), onError: fail });
  const remove = useMutation({ mutationFn: (n: string) => api(`/api/connectors/${n}`, { method: "DELETE" }), onSuccess: () => done("Connector removed."), onError: fail });

  if (!has("admin")) return null;
  const start = (t?: Template) => {
    setEditing(null);
    const needed = t ? Array.from(new Set(JSON.stringify([t.env, t.headers, t.args, t.url]).match(/\$\{([A-Z][A-Z0-9_]*)\}/g) ?? [])).map((m) => `${m.slice(2, -1)}=`) : [];
    setForm(t ? { ...empty, name: t.name, title: t.title, transport: t.transport, command: t.command ?? "", args: (t.args ?? []).join("\n"), url: t.url ?? "", env: pairs(t.env), headers: pairs(t.headers), keywords: (t.keywords ?? []).join(", "), description: t.description ?? "", help: t.secrets_help ?? "", secrets: needed.join("\n") } : { ...empty });
  };
  const edit = (c: Conn) => {
    setEditing(c.name);
    setForm({ ...empty, name: c.name, title: c.title, transport: c.transport, command: c.command, args: c.args.join("\n"), url: c.url,
      env: pairs(c.env), headers: pairs(c.headers), roles: c.roles,
      keywords: c.keywords.join(", "), description: c.description, blocked: c.blocked_tools.join(", "), enabled: c.enabled,
      help: "Secret values stay in .env; \"(hidden)\" keeps a saved value. Add new secrets below." });
  };
  const f = form;
  return (
    <Panel title="Connectors (MCP)" actions={<Button size="sm" variant="primary" icon={<Plus aria-hidden className="size-4" />} onClick={() => start()}>Add connector</Button>}>
      <p className="mb-3 text-sm text-muted">
        Plug in any MCP server (Slack, WhatsApp, GitHub, a job board, ...). Its tools are discovered automatically and used by the
        assistant: say for example "post in Slack ..." or "on WhatsApp ...". Read tools run directly; every other action waits for approval.
      </p>
      {q.isLoading && <Spinner />}
      {q.isError && <ErrorBox error={q.error} />}
      {q.data && (
        <>
          <div className="mb-3 flex flex-wrap gap-2" aria-label="Templates">
            {q.data.templates.map((t) => <Button key={t.name} size="sm" onClick={() => start(t)}>{t.title}</Button>)}
          </div>
          {q.data.items.length === 0 && <p className="text-sm text-muted">No connectors yet. Pick a template above or "Add connector".</p>}
          <ul className="flex flex-col gap-3">
            {q.data.items.map((c) => (
              <li key={c.name} className="rounded-lg border border-border p-3" data-testid={`connector-${c.name}`}>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{c.title}</span>
                  <Badge tone={c.state === "connected" ? "success" : c.state === "error" ? "danger" : "neutral"}>{c.state}</Badge>
                  <span className="text-xs text-muted">{c.transport === "http" ? c.url : `${c.command} ${c.args.join(" ")}`}</span>
                  <span className="ml-auto flex gap-1">
                    <Button size="sm" busy={refresh.isPending && refresh.variables === c.name} icon={<RefreshCw aria-hidden className="size-4" />} onClick={() => refresh.mutate(c.name)}>Test</Button>
                    <Button size="sm" onClick={() => edit(c)}>Edit</Button>
                    <Button size="sm" aria-label={`Remove ${c.title}`} icon={<Trash2 aria-hidden className="size-4" />} onClick={() => remove.mutate(c.name)} />
                  </span>
                </div>
                {c.error && <Notice tone="warning">{c.error}</Notice>}
                {c.missing_secrets.length > 0 && <p className="mt-1 text-xs text-muted">Needs in .env: {c.missing_secrets.join(", ")}</p>}
                {c.tools.length > 0 && (
                  <ul className="mt-2 flex flex-wrap gap-1" aria-label={`${c.title} tools`}>
                    {c.tools.map((t) => (
                      <li key={t.name} title={t.description}><Badge tone={riskTone(t.risk)}>{t.name}{t.risk === "read" ? "" : " (approval)"}</Badge></li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-muted">Saved in {q.data.file}. Secrets go to .env, never into that file.</p>
        </>
      )}
      {f && (
        <Dialog open wide title={editing ? `Edit ${f.title || f.name}` : "Add a connector"} onOpenChange={(v) => { if (!v) setForm(null); }}
          footer={<><Button onClick={() => setForm(null)}>Cancel</Button><Button variant="primary" type="submit" form="connector-form" busy={save.isPending}>Save and connect</Button></>}>
          <form id="connector-form" className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); save.mutate(f); }}>
            {f.help && <Notice tone="info">{f.help}</Notice>}
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Short name" hint="Lowercase, e.g. slack">{(id, d) => <Input id={id} aria-describedby={d} value={f.name} required onChange={(e) => setForm({ ...f, name: e.target.value })} />}</Field>
              <Field label="Title">{(id) => <Input id={id} value={f.title} onChange={(e) => setForm({ ...f, title: e.target.value })} />}</Field>
            </div>
            <Field label="How it runs">{(id) => (
              <Select id={id} value={f.transport} onChange={(e) => setForm({ ...f, transport: e.target.value as Form["transport"] })}>
                <option value="stdio">A program on this computer (stdio: npx, uvx, python ...)</option>
                <option value="http">A server URL (Streamable HTTP)</option>
              </Select>
            )}</Field>
            {f.transport === "stdio" ? (
              <>
                <Field label="Command">{(id) => <Input id={id} value={f.command} onChange={(e) => setForm({ ...f, command: e.target.value })} placeholder="npx" />}</Field>
                <Field label="Arguments" hint="One per line">{(id, d) => <Textarea id={id} aria-describedby={d} rows={3} value={f.args} onChange={(e) => setForm({ ...f, args: e.target.value })} />}</Field>
                <Field label="Environment" hint="NAME=value per line; write secrets as ${NAME}">{(id, d) => <Textarea id={id} aria-describedby={d} rows={3} value={f.env} onChange={(e) => setForm({ ...f, env: e.target.value })} />}</Field>
              </>
            ) : (
              <>
                <Field label="URL">{(id) => <Input id={id} value={f.url} onChange={(e) => setForm({ ...f, url: e.target.value })} placeholder="https://.../mcp" />}</Field>
                <Field label="Headers" hint="Name=value per line, e.g. Authorization=Bearer ${MY_TOKEN}">{(id, d) => <Textarea id={id} aria-describedby={d} rows={2} value={f.headers} onChange={(e) => setForm({ ...f, headers: e.target.value })} />}</Field>
              </>
            )}
            <Field label="Secret values" hint="NAME=value per line. Saved to .env only (e.g. SLACK_BOT_TOKEN=xoxb-...). Leave empty to keep existing values.">
              {(id, d) => <Textarea id={id} aria-describedby={d} rows={2} value={f.secrets} autoComplete="off" spellCheck={false} onChange={(e) => setForm({ ...f, secrets: e.target.value })} />}
            </Field>
            <Field label="Words that send a request here" hint="Comma separated, e.g. slack, channel">{(id, d) => <Input id={id} aria-describedby={d} value={f.keywords} onChange={(e) => setForm({ ...f, keywords: e.target.value })} />}</Field>
            <Field label="What it is for">{(id) => <Input id={id} value={f.description} onChange={(e) => setForm({ ...f, description: e.target.value })} />}</Field>
            <fieldset className="flex flex-wrap gap-3 text-sm">
              <legend className="mb-1 text-sm font-medium">Who may use it (admin always)</legend>
              {ROLES.map((r) => (
                <label key={r} className="flex items-center gap-1">
                  <input type="checkbox" checked={f.roles.includes(r)} onChange={(e) => setForm({ ...f, roles: e.target.checked ? [...f.roles, r] : f.roles.filter((x) => x !== r) })} />{r}
                </label>
              ))}
            </fieldset>
            <Field label="Tools to hide (optional)" hint="Comma separated tool names">{(id, d) => <Input id={id} aria-describedby={d} value={f.blocked} onChange={(e) => setForm({ ...f, blocked: e.target.value })} />}</Field>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.enabled} onChange={(e) => setForm({ ...f, enabled: e.target.checked })} /> Enabled</label>
          </form>
        </Dialog>
      )}
    </Panel>
  );
}
