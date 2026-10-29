import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useRef, useState, type FormEvent } from "react";
import { Calendar, ExternalLink, Inbox, Plus, Send, Trash2 } from "../../components/icons";
import { Dialog, TabPanel, Tabs } from "../../components/ui/overlays";
import { Badge, Button, ErrorBox, Field, IconButton, Input, Notice, PageHeader, Panel, SimulatedBadge, Spinner, Textarea, cx } from "../../components/ui/primitives";
import { api, ApiError, newKey } from "../../lib/api";
import { emailOf, fmtDate, fmtDateTime, fmtTime, zonedIso } from "../../lib/format";
import { useToast } from "../../lib/toast";
import type { CalEvent, Email, Mode, ToolResult } from "../../lib/types";

interface Draft {
  to: string;
  cc: string;
  subject: string;
  body: string;
  thread_id?: string;
}

const splitAddrs = (s: string) => s.split(/[,;\s]+/).map((x) => x.trim()).filter(Boolean);
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function InboxTab({ onReply }: { onReply: (d: Draft) => void }) {
  const [unread, setUnread] = useState(false);
  const [open, setOpen] = useState<Email | null>(null);
  const q = useQuery({
    queryKey: ["inbox", unread],
    queryFn: () => api<ToolResult<{ items: Email[]; next_page_token: string | null } & Mode>>(`/api/communications/inbox?unread_only=${unread}`),
  });
  const items = q.data?.result.items ?? [];
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[24rem_1fr]">
      <Panel
        title={<span className="flex items-center gap-2 text-sm font-semibold">Inbox <SimulatedBadge show={!!q.data?.result.simulated} /></span>}
        actions={
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={unread} onChange={(e) => setUnread(e.target.checked)} className="size-4 accent-[var(--primary)]" />
            Unread only
          </label>
        }
      >
        {q.isLoading && <Spinner />}
        {q.isError && <ErrorBox error={q.error} onRetry={() => void q.refetch()} />}
        {q.data && !items.length && <p className="text-sm text-muted">No messages.</p>}
        <ul className="-mx-2 flex flex-col" data-testid="inbox">
          {items.map((m) => (
            <li key={m.id}>
              <button type="button" onClick={() => setOpen(m)} aria-current={open?.id === m.id ? "true" : undefined}
                className={cx("w-full rounded px-2 py-2 text-left text-sm hover:bg-surface-2", open?.id === m.id && "bg-primary-soft")}>
                <span className="flex items-center justify-between gap-2">
                  <span className={cx("truncate", m.unread && "font-semibold")}>{m.sender.replace(/<.*>/, "").trim() || m.sender}</span>
                  <span className="shrink-0 text-xs text-muted">{fmtDate(m.date)}</span>
                </span>
                <span className="flex items-center gap-2">
                  <span className="truncate">{m.subject}</span>
                  {m.suspicious && <Badge tone="warning">Suspicious</Badge>}
                </span>
                <span className="block truncate text-xs text-muted">{m.snippet}</span>
              </button>
            </li>
          ))}
        </ul>
      </Panel>
      {open ? (
        <Panel
          title={<span className="text-sm font-semibold">{open.subject}</span>}
          actions={<Button size="sm" variant="primary" onClick={() => onReply({ to: emailOf(open.sender), cc: "", subject: open.subject.toLowerCase().startsWith("re:") ? open.subject : `Re: ${open.subject}`, body: "", thread_id: open.thread_id })}>Reply</Button>}
        >
          <p className="text-sm"><span className="text-muted">From:</span> {open.sender}</p>
          <p className="text-sm"><span className="text-muted">Received:</span> {fmtDateTime(open.date)}</p>
          {open.suspicious && (
            <div className="mt-3"><Notice tone="warning" title="Suspicious message">This email contains text addressed to an AI assistant, such as instructions to ignore rules or send data. AgentsMind treats it as data and ignores those instructions. Do not act on it without checking with the sender.</Notice></div>
          )}
          <p className="mb-1 mt-4 text-xs text-muted">Message (outside content)</p>
          <pre className="whitespace-pre-wrap rounded-md border border-border p-3 font-sans text-sm">{open.body}</pre>
        </Panel>
      ) : (
        <Panel><p className="flex items-center gap-2 text-sm text-muted"><Inbox aria-hidden className="size-4" /> Choose a message to read it.</p></Panel>
      )}
    </div>
  );
}

function ComposeDialog({ draft, onClose }: { draft: Draft; onClose: () => void }) {
  const toast = useToast();
  const key = useRef(newKey("mail"));
  const [d, setD] = useState<Draft>(draft);
  const [review, setReview] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const m = useMutation({
    mutationFn: () =>
      api<ToolResult<{ sent: boolean; already_sent: boolean; simulated: boolean }>>("/api/communications/send", {
        body: { to: splitAddrs(d.to), cc: splitAddrs(d.cc), subject: d.subject, body: d.body, ...(d.thread_id ? { thread_id: d.thread_id } : {}) },
        idempotencyKey: key.current,
      }),
    onSuccess: (r) => {
      toast(r.result.already_sent ? "This email was already sent; nothing was sent again." : r.result.simulated ? "Sent (Simulated: nothing was delivered)." : "Email sent.", "success");
      onClose();
    },
    onError: (e) => { setReview(false); if (e instanceof ApiError) setErrors({ form: e.message }); },
  });
  const check = (e: FormEvent) => {
    e.preventDefault();
    const errs: Record<string, string> = {};
    const to = splitAddrs(d.to);
    if (!to.length || !to.every((x) => EMAIL_RE.test(x))) errs.to = "Enter one or more valid email addresses.";
    if (d.cc && !splitAddrs(d.cc).every((x) => EMAIL_RE.test(x))) errs.cc = "Check the Cc addresses.";
    if (!d.subject.trim()) errs.subject = "Add a subject.";
    if (/[\r\n]/.test(d.subject)) errs.subject = "The subject must be one line.";
    if (!d.body.trim()) errs.body = "Write a message.";
    setErrors(errs);
    if (!Object.keys(errs).length) setReview(true);
  };
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()} title={review ? "Send this email?" : "New email"} wide
      footer={review ? (
        <><Button onClick={() => setReview(false)}>Back to editing</Button><Button variant="primary" busy={m.isPending} icon={<Send aria-hidden className="size-4" />} onClick={() => m.mutate()}>Send now</Button></>
      ) : (
        <><Button onClick={onClose}>Cancel</Button><Button variant="primary" type="submit" form="compose">Review</Button></>
      )}>
      {review ? (
        <dl className="grid grid-cols-[5rem_1fr] gap-x-3 gap-y-1 text-sm">
          <dt className="text-muted">To</dt><dd>{splitAddrs(d.to).join(", ")}</dd>
          {d.cc && <><dt className="text-muted">Cc</dt><dd>{splitAddrs(d.cc).join(", ")}</dd></>}
          <dt className="text-muted">Subject</dt><dd>{d.subject}</dd>
          <dt className="text-muted">Message</dt><dd className="whitespace-pre-wrap">{d.body}</dd>
        </dl>
      ) : (
        <form id="compose" onSubmit={check} className="flex flex-col gap-4" noValidate>
          {errors.form && <Notice tone="danger">{errors.form}</Notice>}
          <Field label="To" required error={errors.to} hint="Separate several addresses with commas.">
            {(id, desc, inv) => <Input id={id} aria-describedby={desc} aria-invalid={inv} value={d.to} onChange={(e) => setD({ ...d, to: e.target.value })} />}
          </Field>
          <Field label="Cc" error={errors.cc}>
            {(id, desc, inv) => <Input id={id} aria-describedby={desc} aria-invalid={inv} value={d.cc} onChange={(e) => setD({ ...d, cc: e.target.value })} />}
          </Field>
          <Field label="Subject" required error={errors.subject}>
            {(id, desc, inv) => <Input id={id} aria-describedby={desc} aria-invalid={inv} value={d.subject} maxLength={300} onChange={(e) => setD({ ...d, subject: e.target.value })} />}
          </Field>
          <Field label="Message" required error={errors.body}>
            {(id, desc, inv) => <Textarea id={id} aria-describedby={desc} aria-invalid={inv} value={d.body} rows={10} maxLength={20000} onChange={(e) => setD({ ...d, body: e.target.value })} />}
          </Field>
        </form>
      )}
    </Dialog>
  );
}

function todayIn(tz = "Asia/Karachi"): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
}

function NewEventDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const key = useRef(newKey("cal"));
  const [f, setF] = useState({ summary: "", date: todayIn(), time: "15:00", minutes: "30", attendees: "", add_meet: false, description: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const startIso = f.date && f.time ? zonedIso(f.date, f.time) : "";
  const endIso = startIso ? new Date(new Date(startIso).getTime() + Number(f.minutes) * 60000).toISOString() : "";
  const avail = useQuery({
    queryKey: ["calendar", "availability", startIso, endIso],
    enabled: !!startIso && Number(f.minutes) > 0,
    queryFn: () => api<ToolResult<{ is_free: boolean; conflicts: CalEvent[] } & Mode>>(`/api/calendar/availability?start=${encodeURIComponent(startIso)}&end=${encodeURIComponent(endIso)}`),
  });
  const m = useMutation({
    mutationFn: () =>
      api<ToolResult<{ created: boolean; verified: boolean; event: CalEvent } & Mode>>("/api/calendar/events", {
        body: { summary: f.summary, start: startIso, end: endIso, attendees: splitAddrs(f.attendees), add_meet: f.add_meet, description: f.description },
        idempotencyKey: key.current,
      }),
    onSuccess: (r) => {
      toast(`"${r.result.event.summary}" ${r.result.verified ? "is on the calendar (read back and confirmed)" : "was created"}${r.result.simulated ? ", Simulated" : ""}.`, "success");
      void qc.invalidateQueries({ queryKey: ["calendar"] });
      onClose();
    },
    onError: (e) => setErrors({ form: e instanceof ApiError ? e.message : String(e) }),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (!f.summary.trim()) errs.summary = "Add a title.";
    if (!startIso) errs.date = "Choose a date and time.";
    else if (new Date(startIso) < new Date()) errs.date = "That time has already passed.";
    if (f.attendees && !splitAddrs(f.attendees).every((x) => EMAIL_RE.test(x))) errs.attendees = "Check the attendee addresses.";
    setErrors(errs);
    if (!Object.keys(errs).length) m.mutate();
  };
  const conflicts = avail.data?.result.conflicts ?? [];
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()} title="New event" description="Times are in Asia/Karachi." wide
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" type="submit" form="new-event" busy={m.isPending}>Create event</Button></>}>
      <form id="new-event" onSubmit={submit} className="grid grid-cols-1 gap-4 sm:grid-cols-3" noValidate>
        {errors.form && <div className="sm:col-span-3"><Notice tone="danger">{errors.form}</Notice></div>}
        <div className="sm:col-span-3">
          <Field label="Title" required error={errors.summary}>
            {(id, d, inv) => <Input id={id} aria-describedby={d} aria-invalid={inv} value={f.summary} maxLength={200} onChange={(e) => setF({ ...f, summary: e.target.value })} />}
          </Field>
        </div>
        <Field label="Date" required error={errors.date}>
          {(id, d, inv) => <Input id={id} type="date" aria-describedby={d} aria-invalid={inv} value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} />}
        </Field>
        <Field label="Start time" required>{(id) => <Input id={id} type="time" value={f.time} onChange={(e) => setF({ ...f, time: e.target.value })} />}</Field>
        <Field label="Duration (minutes)" required>
          {(id) => <Input id={id} type="number" min={5} max={720} step={5} value={f.minutes} onChange={(e) => setF({ ...f, minutes: e.target.value })} />}
        </Field>
        <div className="sm:col-span-3">
          <Field label="Attendees" hint="Email addresses, separated by commas." error={errors.attendees}>
            {(id, d, inv) => <Input id={id} aria-describedby={d} aria-invalid={inv} value={f.attendees} onChange={(e) => setF({ ...f, attendees: e.target.value })} />}
          </Field>
        </div>
        <label className="flex items-center gap-2 text-sm sm:col-span-3">
          <input type="checkbox" className="size-4 accent-[var(--primary)]" checked={f.add_meet} onChange={(e) => setF({ ...f, add_meet: e.target.checked })} />
          Add a Google Meet link
        </label>
        <div className="sm:col-span-3" aria-live="polite">
          {avail.data && (avail.data.result.is_free ? (
            <Notice>You are free at this time.</Notice>
          ) : (
            <Notice tone="warning" title="Conflict">
              This overlaps {conflicts.map((c) => `${c.summary} (${fmtTime(c.start)} to ${fmtTime(c.end)})`).join(", ") || "another event"}.
            </Notice>
          ))}
        </div>
      </form>
    </Dialog>
  );
}

function CalendarTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const [creating, setCreating] = useState(false);
  const [cancelling, setCancelling] = useState<CalEvent | null>(null);
  const q = useQuery({ queryKey: ["calendar", "events"], queryFn: () => api<ToolResult<{ items: CalEvent[] } & Mode>>("/api/calendar/events?days=14") });
  const cancel = useMutation({
    mutationFn: (ev: CalEvent) => api(`/api/calendar/events/${ev.id}`, { method: "DELETE", body: { confirm: true }, idempotencyKey: newKey("cx") }),
    onSuccess: () => { toast("Event cancelled.", "success"); setCancelling(null); void qc.invalidateQueries({ queryKey: ["calendar"] }); },
    onError: (e) => toast(e instanceof ApiError ? e.message : String(e), "error"),
  });
  const byDay = useMemo(() => {
    const m = new Map<string, CalEvent[]>();
    for (const e of q.data?.result.items ?? []) {
      const k = fmtDate(e.start);
      m.set(k, [...(m.get(k) ?? []), e]);
    }
    return [...m.entries()];
  }, [q.data]);
  return (
    <Panel
      title={<span className="flex items-center gap-2 text-sm font-semibold">Next 14 days <SimulatedBadge show={!!q.data?.result.simulated} /></span>}
      actions={<Button size="sm" variant="primary" icon={<Plus aria-hidden className="size-4" />} onClick={() => setCreating(true)}>New event</Button>}
    >
      {q.isLoading && <Spinner />}
      {q.isError && <ErrorBox error={q.error} onRetry={() => void q.refetch()} />}
      {q.data && !byDay.length && <p className="flex items-center gap-2 text-sm text-muted"><Calendar aria-hidden className="size-4" /> Nothing scheduled.</p>}
      <div className="flex flex-col gap-4" data-testid="agenda">
        {byDay.map(([day, evs]) => (
          <section key={day}>
            <h3 className="mb-1 text-sm font-semibold">{day}</h3>
            <ul className="flex flex-col gap-1">
              {evs.map((e) => (
                <li key={e.id} className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2 text-sm">
                  <span>
                    <span className="tabular-nums text-muted">{fmtTime(e.start)} to {fmtTime(e.end)}</span>{" "}
                    <span className="font-medium">{e.summary}</span>
                    {e.meet_link && (
                      <a href={e.meet_link} target="_blank" rel="noreferrer noopener" className="ml-2 inline-flex items-center gap-1 text-primary hover:underline">
                        Meet <ExternalLink aria-hidden className="size-3" />
                      </a>
                    )}
                  </span>
                  <IconButton label={`Cancel ${e.summary}`} onClick={() => setCancelling(e)}><Trash2 aria-hidden className="size-4" /></IconButton>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
      {creating && <NewEventDialog onClose={() => setCreating(false)} />}
      {cancelling && (
        <Dialog open onOpenChange={(v) => !v && setCancelling(null)} title={`Cancel "${cancelling.summary}"?`}
          description={`${fmtDateTime(cancelling.start)}. Attendees are not notified.`}
          footer={<><Button onClick={() => setCancelling(null)}>Keep it</Button><Button variant="danger" busy={cancel.isPending} onClick={() => cancel.mutate(cancelling)}>Cancel event</Button></>}>
          <p className="text-sm">This removes the event from the calendar.</p>
        </Dialog>
      )}
    </Panel>
  );
}

export function CommunicationsPage() {
  const [tab, setTab] = useState("inbox");
  const [draft, setDraft] = useState<Draft | null>(null);
  return (
    <div>
      <PageHeader
        title="Communications"
        description="Your inbox and calendar. Every email you send is reviewed by you first; booking and cancelling go through the same audited path."
        actions={<Button variant="primary" icon={<Send aria-hidden className="size-4" />} onClick={() => setDraft({ to: "", cc: "", subject: "", body: "" })}>New email</Button>}
      />
      <Tabs value={tab} onValueChange={setTab} label="Communications" tabs={[{ value: "inbox", label: "Inbox" }, { value: "calendar", label: "Calendar" }]}>
        <TabPanel value="inbox"><InboxTab onReply={setDraft} /></TabPanel>
        <TabPanel value="calendar"><CalendarTab /></TabPanel>
      </Tabs>
      {draft && <ComposeDialog draft={draft} onClose={() => setDraft(null)} />}
    </div>
  );
}
