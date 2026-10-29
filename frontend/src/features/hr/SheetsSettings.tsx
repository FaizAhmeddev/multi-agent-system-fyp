import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ExternalLink, Plus, RefreshCw, Trash2, Upload } from "../../components/icons";
import { Dialog } from "../../components/ui/overlays";
import { Badge, Button, ErrorBox, Field, Input, Notice, Panel, Select, Spinner, Table, Textarea } from "../../components/ui/primitives";
import { api, ApiError, uploadFile } from "../../lib/api";
import { fmtDateTime, humanize } from "../../lib/format";
import { useToast } from "../../lib/toast";
import type { HRSheet } from "../../lib/types";

const PURPOSES = ["employees", "new_joiners", "attendance", "leave", "payroll", "separations", "compliance", "candidates", "other"];

function AddSheet({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [f, setF] = useState({ name: "", purpose: "leave", source: "google" as "google" | "excel", location: "", tab: "", description: "", auto_record: true });
  const [file, setFile] = useState<File | null>(null);
  const m = useMutation({
    mutationFn: async () => {
      let location = f.location;
      if (f.source === "excel" && file) location = (await uploadFile<{ location: string }>("/api/hr/sheets/upload", file)).location;
      return api<HRSheet>("/api/hr/sheets", { body: { ...f, location } });
    },
    onSuccess: (s) => { toast(`'${s.name}' registered with ${s.headers.length} column(s).`, "success"); void qc.invalidateQueries({ queryKey: ["hr", "sheets"] }); onClose(); },
    onError: (e) => toast(e instanceof ApiError ? e.message : String(e), "error"),
  });
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()} title="Register an HR sheet" wide
      description="Tell AgentsMind where you keep each kind of record. It reads the sheet when you ask about it, and adds rows after approved actions."
      footer={<Button variant="primary" busy={m.isPending} disabled={!f.name.trim() || (f.source === "google" ? !f.location.trim() : !file && !f.location.trim())} onClick={() => m.mutate()}>Register</Button>}>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Name">{(id) => <Input id={id} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Leave tracker 2026" />}</Field>
        <Field label="It holds">{(id) => (
          <Select id={id} value={f.purpose} onChange={(e) => setF({ ...f, purpose: e.target.value })}>{PURPOSES.map((p) => <option key={p} value={p}>{humanize(p)}</option>)}</Select>
        )}</Field>
        <Field label="Where">{(id) => (
          <Select id={id} value={f.source} onChange={(e) => setF({ ...f, source: e.target.value as "google" | "excel" })}>
            <option value="google">Google Sheets</option><option value="excel">Excel file on this computer</option>
          </Select>
        )}</Field>
        <Field label="Tab (optional)" hint="Empty = the first tab">{(id, d) => <Input id={id} aria-describedby={d} value={f.tab} onChange={(e) => setF({ ...f, tab: e.target.value })} />}</Field>
        <div className="sm:col-span-2">
          {f.source === "google" ? (
            <Field label="Google Sheets link" hint="Share the sheet with the Google account AgentsMind signed in with.">
              {(id, d) => <Input id={id} aria-describedby={d} value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} placeholder="https://docs.google.com/spreadsheets/d/..." />}
            </Field>
          ) : (
            <Field label="Excel file" hint="Upload it (saved in data\hr_sheets), or type the path of a file inside a folder listed in HR_EXCEL_DIRS.">
              {(id, d) => (
                <div className="flex flex-col gap-2">
                  <input id={id} aria-describedby={d} type="file" accept=".xlsx,.xlsm" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="text-sm" />
                  <Input aria-label="Or a file path" value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} placeholder="or: C:\Users\you\Documents\HR\leave.xlsx" />
                </div>
              )}
            </Field>
          )}
        </div>
        <div className="sm:col-span-2">
          <Field label="What is in it (helps the assistant)">{(id) => <Textarea id={id} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} placeholder="One row per leave request: employee, type, from, to, days, status" />}</Field>
        </div>
        <label className="flex items-center gap-2 text-sm sm:col-span-2">
          <input type="checkbox" checked={f.auto_record} onChange={(e) => setF({ ...f, auto_record: e.target.checked })} className="size-4" />
          Add rows to this sheet automatically after approved actions (new joiners, separations, payroll)
        </label>
      </div>
    </Dialog>
  );
}

export function SheetsTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const [adding, setAdding] = useState(false);
  const q = useQuery({ queryKey: ["hr", "sheets"], queryFn: () => api<{ items: HRSheet[] }>("/api/hr/sheets") });
  const refresh = useMutation({
    mutationFn: (id: number) => api<HRSheet>(`/api/hr/sheets/${id}/refresh`, { body: {} }),
    onSuccess: (s) => { toast(`'${s.name}': ${s.headers.length} column(s).`, "success"); void qc.invalidateQueries({ queryKey: ["hr", "sheets"] }); },
    onError: (e) => toast(e instanceof ApiError ? e.message : String(e), "error"),
  });
  const remove = useMutation({
    mutationFn: (id: number) => api(`/api/hr/sheets/${id}`, { method: "DELETE" }),
    onSuccess: () => { toast("Registration removed. The sheet itself is unchanged.", "success"); void qc.invalidateQueries({ queryKey: ["hr", "sheets"] }); },
  });
  return (
    <Panel title="Your HR sheets" actions={<Button variant="primary" size="sm" icon={<Plus aria-hidden className="size-4" />} onClick={() => setAdding(true)}>Register a sheet</Button>}>
      <p className="mb-3 text-sm text-muted">Ask the assistant things like "Where do I keep the leave records?" or "Show Ahmed's leaves from my leave sheet".</p>
      {q.isLoading && <Spinner />}
      {q.isError && <ErrorBox error={q.error} />}
      {q.data && (
        <Table caption="HR sheets" rows={q.data.items} rowKey={(s) => s.id} empty="No sheets registered yet."
          columns={[
            { key: "name", header: "Name", render: (s) => <span className="font-medium">{s.name}</span> },
            { key: "purpose", header: "Holds", render: (s) => <Badge>{humanize(s.purpose)}</Badge> },
            { key: "source", header: "Where", render: (s) => (s.source === "google" ? "Google Sheets" : "Excel") },
            { key: "headers", header: "Columns", render: (s) => <span className="text-xs text-muted">{s.headers.slice(0, 8).join(", ")}{s.headers.length > 8 ? "…" : ""}</span> },
            { key: "last_read_at", header: "Last read", render: (s) => fmtDateTime(s.last_read_at) },
            { key: "act", header: "", render: (s) => (
              <span className="flex gap-2">
                {s.source === "google" && (
                  <a href={s.link} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-sm text-primary hover:underline">Open <ExternalLink aria-hidden className="size-3.5" /></a>
                )}
                <Button size="sm" icon={<RefreshCw aria-hidden className="size-3.5" />} busy={refresh.isPending} onClick={() => refresh.mutate(s.id)}>Re-read</Button>
                <Button size="sm" icon={<Trash2 aria-hidden className="size-3.5" />} onClick={() => remove.mutate(s.id)}>Remove</Button>
              </span>
            ) },
          ]} />
      )}
      {adding && <AddSheet onClose={() => setAdding(false)} />}
      <p className="mt-3 flex items-center gap-1 text-xs text-muted"><Upload aria-hidden className="size-3.5" /> Excel files you upload are kept in data\hr_sheets on this computer.</p>
    </Panel>
  );
}

type Policy = Record<string, Record<string, unknown>>;

export function HRSettingsTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["hr", "settings"], queryFn: () => api<Policy>("/api/hr/settings") });
  const [p, setP] = useState<Policy | null>(null);
  useEffect(() => { if (q.data && !p) setP(q.data); }, [q.data, p]);
  const save = useMutation({
    mutationFn: () => api<Policy>("/api/hr/settings", { method: "PUT", body: { company: p?.company, recruitment: p?.recruitment, work: p?.work, leave: p?.leave, payroll: p?.payroll } }),
    onSuccess: (r) => { setP(r); toast("HR settings saved.", "success"); void qc.invalidateQueries({ queryKey: ["hr"] }); },
    onError: (e) => toast(e instanceof ApiError ? e.message : String(e), "error"),
  });
  if (q.isLoading || !p) return q.isError ? <ErrorBox error={q.error} /> : <Spinner />;
  const val = (sec: string, k: string) => String((p[sec] ?? {})[k] ?? "");
  const set = (sec: string, k: string, v: unknown) => setP({ ...p, [sec]: { ...(p[sec] ?? {}), [k]: v } });
  const text = (sec: string, k: string, label: string, hint?: string) => (
    <Field label={label} hint={hint}>{(id, d) => <Input id={id} aria-describedby={d} value={val(sec, k)} onChange={(e) => set(sec, k, e.target.value)} />}</Field>
  );
  const num = (sec: string, k: string, label: string, hint?: string) => (
    <Field label={label} hint={hint}>{(id, d) => <Input id={id} aria-describedby={d} inputMode="decimal" value={val(sec, k)} onChange={(e) => set(sec, k, e.target.value === "" ? 0 : Number(e.target.value))} />}</Field>
  );
  return (
    <div className="flex flex-col gap-6">
      <Panel title="Company (printed on letters)">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {text("company", "name", "Company name")}
          {text("company", "address", "Address")}
          {text("company", "city", "City")}
          {text("company", "phone", "Phone")}
          {text("company", "email", "HR email")}
          {text("company", "website", "Website")}
          {text("company", "signatory_name", "Letters signed by")}
          {text("company", "signatory_title", "Signatory title")}
        </div>
      </Panel>
      <Panel title="Recruitment">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {text("recruitment", "candidate_city", "Screen candidates in", "CVs from other cities are listed but not screened")}
          {text("recruitment", "gmail_query", "Gmail search for CVs", "Gmail search syntax")}
          <label className="flex items-center gap-2 text-sm sm:col-span-2">
            <input type="checkbox" className="size-4" checked={Boolean(p.recruitment?.include_unknown_location)} onChange={(e) => set("recruitment", "include_unknown_location", e.target.checked)} />
            Also screen CVs that do not mention any city
          </label>
        </div>
      </Panel>
      <Panel title="Working hours">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {text("work", "office_start", "Office starts (HH:MM)")}
          {text("work", "late_after", "Late after (HH:MM)")}
          {text("work", "office_end", "Office ends (HH:MM)")}
        </div>
      </Panel>
      <Panel title="Leave entitlement (working days per year)">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {num("leave", "annual", "Annual")}{num("leave", "casual", "Casual")}{num("leave", "sick", "Sick")}
          {num("leave", "maternity", "Maternity")}{num("leave", "paternity", "Paternity")}{num("leave", "carry_forward_annual", "Annual carried forward")}
        </div>
        <label className="mt-3 flex items-center gap-2 text-sm">
          <input type="checkbox" className="size-4" checked={Boolean(p.leave?.encash_annual_on_exit)} onChange={(e) => set("leave", "encash_annual_on_exit", e.target.checked)} />
          Pay unused annual leave in the final settlement
        </label>
      </Panel>
      <Panel title="Payroll">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {num("payroll", "probation_months", "Probation (months)")}
          {num("payroll", "notice_days", "Notice period (days)")}
          {num("payroll", "tax_withholding_percent", "Income tax withheld (%)", "Set from the current FBR slabs; 0 = not withheld")}
          {num("payroll", "eobi_employee_amount", "EOBI employee share (PKR a month)", "Set to the current rate; 0 = none")}
          <Field label="Daily rate for deductions">{(id) => (
            <Select id={id} value={val("payroll", "days_basis")} onChange={(e) => set("payroll", "days_basis", e.target.value)}>
              <option value="calendar">Gross / days in the month</option><option value="30">Gross / 30</option><option value="working">Gross / working days</option>
            </Select>
          )}</Field>
        </div>
      </Panel>
      <Notice tone="info">The onboarding, induction, compliance and separation checklists use the built-in Karachi (Sindh) templates; each employee's items can be ticked, skipped or retried on their page.</Notice>
      <div><Button variant="primary" busy={save.isPending} onClick={() => save.mutate()}>Save settings</Button></div>
    </div>
  );
}
