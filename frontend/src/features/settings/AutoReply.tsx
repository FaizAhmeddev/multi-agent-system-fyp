import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Button, ErrorBox, Field, Input, Notice, Panel, Select, Spinner, Textarea } from "../../components/ui/primitives";
import { api, ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { fmtDateTime } from "../../lib/format";
import { useToast } from "../../lib/toast";

type Mode = "off" | "draft" | "send";
interface AutoReply {
  mode: Mode;
  interval_minutes: number;
  instructions: string;
  max_per_run: number;
  max_per_day: number;
  enabled_at: string | null;
  state: { last_run: string | null; last_result: string; handled: number; sent_today: number };
}

const MODES: { v: Mode; label: string; hint: string }[] = [
  { v: "off", label: "Off", hint: "New emails are not answered automatically." },
  { v: "draft", label: "Draft replies for approval", hint: "Each new email gets a drafted reply in Approvals. Nothing is sent until you approve it." },
  { v: "send", label: "Send replies automatically", hint: "Replies are sent from your Gmail without asking. Suspicious emails still wait for approval." },
];

/* Settings > Email auto-reply (admin and HR). */
export function AutoReplyPanel() {
  const { has } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const allowed = has("admin") || has("hr");
  const q = useQuery({ queryKey: ["auto-reply"], queryFn: () => api<AutoReply>("/api/settings/auto-reply"), enabled: allowed });
  const [f, setF] = useState({ mode: "off" as Mode, interval_minutes: 5, instructions: "" });
  useEffect(() => {
    if (q.data) setF({ mode: q.data.mode, interval_minutes: q.data.interval_minutes, instructions: q.data.instructions });
  }, [q.data]);
  const save = useMutation({
    mutationFn: () => api<AutoReply>("/api/settings/auto-reply", { method: "PUT", body: f }),
    onSuccess: (r) => {
      qc.setQueryData(["auto-reply"], r);
      toast(r.mode === "off" ? "Auto-reply is off." : r.mode === "send" ? "Auto-reply is on: replies are sent automatically." : "Auto-reply is on: drafts wait for your approval.", "success");
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : String(e), "error"),
  });
  const run = useMutation({
    mutationFn: () => api<{ status: string; message?: string; config: AutoReply }>("/api/settings/auto-reply/run", { body: {} }),
    onSuccess: (r) => {
      qc.setQueryData(["auto-reply"], r.config);
      void qc.invalidateQueries({ queryKey: ["approvals"] });
      toast(r.status === "off" ? "Auto-reply is off. Choose a mode and save first." : r.message ?? "Checked.", r.status === "error" ? "error" : "success");
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : String(e), "error"),
  });
  if (!allowed) return null;
  const d = q.data;
  const hint = MODES.find((m) => m.v === f.mode)?.hint;
  return (
    <Panel title="Email auto-reply">
      {q.isLoading && <Spinner />}
      {q.isError && <ErrorBox error={q.error} />}
      {d && (
        <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <Field label="Mode" hint={hint}>
            {(id, dsc) => (
              <Select id={id} aria-describedby={dsc} value={f.mode} onChange={(e) => setF({ ...f, mode: e.target.value as Mode })}>
                {MODES.map((m) => <option key={m.v} value={m.v}>{m.label}</option>)}
              </Select>
            )}
          </Field>
          <Field label="Check the inbox every (minutes)">
            {(id) => <Input id={id} type="number" min={1} max={240} value={f.interval_minutes} onChange={(e) => setF({ ...f, interval_minutes: Number(e.target.value) || 5 })} />}
          </Field>
          <Field label="What the replies should say" hint="The model writes each reply from this and the email it answers. It never adds facts, prices or promises you did not give.">
            {(id, dsc) => <Textarea id={id} aria-describedby={dsc} rows={3} maxLength={1000} value={f.instructions} onChange={(e) => setF({ ...f, instructions: e.target.value })} />}
          </Field>
          {f.mode === "send" && <Notice tone="warning">Replies go out from your Gmail without asking. Only emails that arrive after you save are answered, each once; no-reply, newsletter and your own emails are skipped; at most {d.max_per_day} per day.</Notice>}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant="primary" busy={save.isPending}>Save</Button>
            <Button type="button" busy={run.isPending} disabled={d.mode === "off"} onClick={() => run.mutate()}>Check the inbox now</Button>
          </div>
          <p className="text-xs text-muted" role="status">
            {d.mode === "off" ? "Off." : `On since ${fmtDateTime(d.enabled_at)}.`}{" "}
            {d.state.last_run ? `Last check ${fmtDateTime(d.state.last_run)}: ${d.state.last_result}` : "Not checked yet."}
            {d.state.handled ? ` ${d.state.handled} email(s) handled so far.` : ""}
          </p>
        </form>
      )}
    </Panel>
  );
}
