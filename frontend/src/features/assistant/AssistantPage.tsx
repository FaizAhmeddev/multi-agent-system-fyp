import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Bot, LoaderCircle, Paperclip, Plus, Send, X } from "../../components/icons";
import { Badge, Button, ErrorBox, Notice, SimulatedBadge, Textarea, cx } from "../../components/ui/primitives";
import { api, ApiError, streamEvents, uploadFile } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { fmtDateTime } from "../../lib/format";
import { Link, useRouter } from "../../lib/router";
import type { Card, TurnResult } from "../../lib/types";
import { CardView } from "./Cards";

interface ConvSummary {
  id: number;
  title: string;
  updated_at: string;
}

interface Turn {
  id: string;
  role: "user" | "assistant";
  text: string;
  cards: Card[];
  files?: string[];
}

interface Attachment {
  id: string;
  name: string;
  size: number;
  chars: number;
}

const NODE_LABEL: Record<string, string> = {
  understand: "Reading your request",
  gather: "Looking things up",
  propose: "Preparing the approval card",
};

const SUGGESTIONS: { text: string; roles?: string[] }[] = [
  { text: "Schedule a design review tomorrow at 3 pm for 45 minutes with a Google Meet link" },
  { text: "Am I free Friday afternoon?" },
  { text: "My laptop keeps disconnecting from the VPN, please raise a ticket" },
  { text: "Show my unread emails" },
  { text: "What is the total monthly payroll?", roles: ["finance"] },
  { text: "Screen the CVs for the Python Developer role", roles: ["hr"] },
  { text: "Summarize the leave policy", roles: ["hr", "it", "finance"] },
];

export function AssistantPage({ conversationId }: { conversationId?: number }) {
  const { has } = useAuth();
  const { navigate } = useRouter();
  const qc = useQueryClient();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [convId, setConvId] = useState<number | undefined>(conversationId);
  const [meta, setMeta] = useState<{ llm: string; planner: string } | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState(false);

  const attach = async (list: FileList | null) => {
    if (!list?.length) return;
    setError(null);
    setUploading(true);
    try {
      for (const f of Array.from(list).slice(0, 5 - files.length)) {
        const a = await uploadFile<Attachment>("/api/assistant/attachments", f);
        setFiles((cur) => [...cur, a]);
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const convs = useQuery({ queryKey: ["conversations"], queryFn: () => api<{ items: ConvSummary[] }>("/api/assistant/conversations?page_size=30") });
  const history = useQuery({
    queryKey: ["conversation", conversationId],
    enabled: !!conversationId,
    queryFn: () =>
      api<{ id: number; title: string; messages: { id: number; role: "user" | "assistant"; content: string; cards: Card[] }[] }>(
        `/api/assistant/conversations/${conversationId}`,
      ),
  });

  useEffect(() => {
    setConvId(conversationId);
    if (!conversationId) setTurns([]);
  }, [conversationId]);

  useEffect(() => {
    if (history.data) {
      setTurns(history.data.messages.map((m) => ({ id: `m${m.id}`, role: m.role, text: m.content, cards: m.cards ?? [] })));
    }
  }, [history.data]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [turns, progress]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const send = async (message: string) => {
    const msg = message.trim();
    if (!msg || busy) return;
    setError(null);
    setBusy(true);
    setProgress(["Planning"]);
    setText("");
    const sent = files;
    setFiles([]);
    setTurns((t) => [...t, { id: `u${Date.now()}`, role: "user", text: msg, cards: [], files: sent.map((f) => f.name) }]);
    const ctl = new AbortController();
    abortRef.current = ctl;
    let result: TurnResult | null = null;
    try {
      await streamEvents(
        "/api/assistant/messages/stream",
        { text: msg, conversation_id: convId ?? null, attachments: sent.map((f) => f.id) },
        (ev, data) => {
          const d = data as Record<string, unknown>;
          if (ev === "plan") {
            const steps = (d.steps as { agent: string }[]) ?? [];
            setProgress(steps.length ? [`Plan: ${steps.map((s) => s.agent).join(", then ")}`] : ["No matching department"]);
          } else if (ev === "step") {
            const label = `${String(d.agent)}: ${NODE_LABEL[String(d.node)] ?? String(d.node)}${d.detail ? ` (${String(d.detail)})` : ""}`;
            setProgress((p) => (p[p.length - 1] === label ? p : [...p, label]));
          } else if (ev === "result") {
            result = d as unknown as TurnResult;
          } else if (ev === "error") {
            setError(String(d.message ?? "The assistant failed."));
          }
        },
        ctl.signal,
      );
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
      setProgress([]);
    }
    const res = result as TurnResult | null;
    if (res) {
      setTurns((t) => [...t, { id: `a${res.message_id}`, role: "assistant", text: "", cards: res.cards }]);
      setMeta({ llm: res.llm, planner: res.planner });
      if (!convId) {
        setConvId(res.conversation_id);
        window.history.replaceState(null, "", `/assistant/${res.conversation_id}`);
      }
      void qc.invalidateQueries({ queryKey: ["conversations"] });
      void qc.invalidateQueries({ queryKey: ["approvals"] });
    }
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void send(text);
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send(text);
    }
  };

  const suggestions = SUGGESTIONS.filter((s) => !s.roles || has(...s.roles));

  return (
    <div className="grid h-[calc(100vh-8.5rem)] min-h-[32rem] grid-cols-1 gap-4 lg:grid-cols-[16rem_1fr]">
      <aside className="hidden flex-col rounded-lg border border-border bg-surface lg:flex" aria-label="Conversations">
        <div className="flex items-center justify-between border-b border-border px-3 py-2">
          <h2 className="text-sm font-semibold">Conversations</h2>
          <Button size="sm" variant="ghost" icon={<Plus aria-hidden className="size-4" />} onClick={() => navigate("/assistant")}>
            New
          </Button>
        </div>
        <ul className="flex-1 overflow-y-auto p-1">
          {convs.data?.items.map((c) => (
            <li key={c.id}>
              <Link
                to={`/assistant/${c.id}`}
                aria-current={c.id === convId ? "page" : undefined}
                className={cx("block rounded px-2 py-1.5 text-sm hover:bg-surface-2", c.id === convId && "bg-primary-soft text-primary")}
              >
                <span className="block truncate">{c.title}</span>
                <span className="block text-xs text-muted">{fmtDateTime(c.updated_at)}</span>
              </Link>
            </li>
          ))}
          {convs.data && !convs.data.items.length && <li className="px-2 py-3 text-sm text-muted">No conversations yet.</li>}
        </ul>
      </aside>

      <section className="flex min-h-0 flex-col rounded-lg border border-border bg-surface" aria-label="Assistant">
        <div className="flex items-center justify-between border-b border-border px-4 py-2">
          <h1 className="flex items-center gap-2 text-sm font-semibold">
            <Bot aria-hidden className="size-4" /> Assistant
          </h1>
          {meta && (
            <span className="flex items-center gap-2 text-xs text-muted">
              Model: {meta.llm === "sandbox" ? "none" : meta.llm}
              <SimulatedBadge show={meta.llm === "sandbox"} />
            </span>
          )}
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-4" aria-live="polite">
          {history.isError && <ErrorBox error={history.error} />}
          {!turns.length && !history.isLoading && (
            <div className="mx-auto max-w-2xl py-6">
              <p className="text-lg font-semibold">What do you need done?</p>
              <p className="mt-1 text-sm text-muted">
                Ask in plain language. Anything that changes data, sends email or books time shows an approval card first.
              </p>
              <div className="mt-4 flex flex-col gap-2">
                {suggestions.map((s) => (
                  <button
                    key={s.text}
                    type="button"
                    onClick={() => void send(s.text)}
                    className="rounded-md border border-border px-3 py-2 text-left text-sm hover:bg-surface-2"
                  >
                    {s.text}
                  </button>
                ))}
              </div>
            </div>
          )}
          <ol className="mx-auto flex max-w-3xl flex-col gap-4">
            {turns.map((t) =>
              t.role === "user" ? (
                <li key={t.id} className="self-end rounded-lg bg-primary-soft px-3 py-2 text-sm" data-testid="user-message">
                  {t.text}
                  {t.files?.length ? (
                    <span className="mt-1 flex flex-wrap gap-1 text-xs text-muted">
                      {t.files.map((n) => (
                        <span key={n} className="inline-flex items-center gap-1"><Paperclip aria-hidden className="size-3" />{n}</span>
                      ))}
                    </span>
                  ) : null}
                </li>
              ) : (
                <li key={t.id} className="flex flex-col gap-3" data-testid="assistant-message">
                  {t.cards.length ? t.cards.map((c, i) => <CardView key={i} card={c} onOption={(o) => void send(o)} />) : <p className="text-sm">{t.text}</p>}
                </li>
              ),
            )}
            {busy && (
              <li className="flex flex-col gap-1 text-sm text-muted" role="status" data-testid="progress">
                {progress.map((p, i) => (
                  <span key={i} className="flex items-center gap-2">
                    {i === progress.length - 1 ? <LoaderCircle aria-hidden className="size-4 animate-spin" /> : <span className="size-4" />}
                    {p}
                  </span>
                ))}
              </li>
            )}
          </ol>
          <div ref={endRef} />
        </div>

        {error && (
          <div className="px-4 pb-2">
            <Notice tone="danger">{error}</Notice>
          </div>
        )}
        {files.length > 0 && (
          <ul className="flex flex-wrap gap-2 border-t border-border px-3 pt-2" aria-label="Attached files">
            {files.map((f) => (
              <li key={f.id} className="flex items-center gap-1 rounded-md border border-border bg-surface px-2 py-1 text-xs">
                <Paperclip aria-hidden className="size-3" />
                <span className="max-w-48 truncate">{f.name}</span>
                <button type="button" className="rounded p-0.5 text-muted hover:text-fg" aria-label={`Remove ${f.name}`} onClick={() => setFiles((c) => c.filter((x) => x.id !== f.id))}>
                  <X aria-hidden className="size-3" />
                </button>
              </li>
            ))}
          </ul>
        )}
        <form onSubmit={onSubmit} className="flex items-end gap-2 border-t border-border p-3">
          <input
            ref={fileRef}
            type="file"
            className="sr-only"
            multiple
            accept=".pdf,.docx,.xlsx,.xlsm,.csv,.txt,.md,.json,.tsv"
            aria-label="Attach files"
            onChange={(e) => void attach(e.target.files)}
          />
          <Button type="button" busy={uploading} disabled={busy || files.length >= 5} onClick={() => fileRef.current?.click()} icon={<Paperclip aria-hidden className="size-4" />} aria-label="Attach a file">
            <span className="sr-only">Attach</span>
          </Button>
          <label htmlFor="assistant-input" className="sr-only">
            Message
          </label>
          <Textarea
            id="assistant-input"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKey}
            placeholder="For example: cancel Monday's review meeting"
            rows={2}
            maxLength={4000}
            className="min-h-12 resize-none"
          />
          <Button type="submit" variant="primary" busy={busy} disabled={!text.trim()} icon={<Send aria-hidden className="size-4" />}>
            Send
          </Button>
        </form>
        <p className="px-4 pb-2 text-xs text-muted">
          Enter to send, Shift+Enter for a new line. <Badge tone="neutral">Approval first</Badge> for every change.
        </p>
      </section>
    </div>
  );
}
