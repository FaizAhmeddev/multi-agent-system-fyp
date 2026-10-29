import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Download, Send } from "../../components/icons";
import { Button, ErrorBox, Field, Input, Notice, Panel, Select, Spinner, Table } from "../../components/ui/primitives";
import { api, ApiError, newKey, openFile } from "../../lib/api";
import { fmtDate, humanize } from "../../lib/format";
import { useToast } from "../../lib/toast";
import type { Employee, HRLetter, HRReport } from "../../lib/types";
import { money, StatusBadge, useAsk } from "./common";

interface PayrollLine {
  employee_id: number; code: string; name: string; department: string; gross: number; proration: number; unpaid_leave_days: number;
  absent_days: number; leave_deduction: number; eobi: number; tax: number; net: number; currency: string; tax_note: string;
}
interface PayrollRun {
  id: number; month: string; status: string; totals: Record<string, { employees: number; gross: number; deductions: number; net: number }>;
  lines: PayrollLine[]; steps: { title: string; summary: string }[];
}

function thisMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export function PayrollTab() {
  const [month, setMonth] = useState(thisMonth());
  const q = useQuery({ queryKey: ["hr", "payroll", month], queryFn: () => api<PayrollRun>(`/api/hr/payroll/${month}`) });
  const { ask, busy, view } = useAsk();
  const r = q.data;
  const label = new Date(`${month}-01T00:00:00`).toLocaleDateString("en-GB", { month: "long", year: "numeric" });
  return (
    <Panel title="Payroll" actions={
      <div className="flex items-end gap-2">
        <Field label="Month">{(id) => <Input id={id} type="month" value={month} onChange={(e) => setMonth(e.target.value)} />}</Field>
      </div>
    }>
      {q.isLoading && <Spinner />}
      {q.isError && <ErrorBox error={q.error} />}
      {r && (
        <div className="flex flex-col gap-4">
          <p className="text-sm">
            {humanize(r.status)}.{" "}
            {Object.entries(r.totals).map(([c, t]) => `${t.employees} employee(s), gross ${money(t.gross, c)}, deductions ${money(t.deductions, c)}, net ${money(t.net, c)}`).join("; ") || "No employees with a salary on record."}
          </p>
          {r.lines.some((l) => l.tax_note) && <Notice tone="warning">{r.lines.find((l) => l.tax_note)?.tax_note}</Notice>}
          <Table caption="Payroll lines" rows={r.lines} rowKey={(l) => l.employee_id} empty="No payroll lines."
            columns={[
              { key: "name", header: "Employee" }, { key: "department", header: "Department" },
              { key: "gross", header: "Gross", render: (l) => money(l.gross, l.currency) },
              { key: "proration", header: "Not employed", render: (l) => (l.proration ? money(l.proration, l.currency) : "-") },
              { key: "unpaid_leave_days", header: "Unpaid days", render: (l) => String(l.unpaid_leave_days + l.absent_days) },
              { key: "leave_deduction", header: "Leave deduction", render: (l) => money(l.leave_deduction, l.currency) },
              { key: "eobi", header: "EOBI", render: (l) => money(l.eobi, l.currency) },
              { key: "tax", header: "Tax", render: (l) => money(l.tax, l.currency) },
              { key: "net", header: "Net pay", render: (l) => <span className="font-semibold">{money(l.net, l.currency)}</span> },
            ]} />
          <p className="text-xs text-muted">Computed in code from salaries, attendance and approved leave. Unpaid leave and absences without leave are deducted at the daily rate.</p>
          {r.status === "draft" && (
            <div><Button variant="primary" busy={busy} disabled={!r.lines.length} onClick={() => ask(`Run payroll for ${label}`)}>Prepare posting to the Finance Portal</Button></div>
          )}
          {view}
        </div>
      )}
    </Panel>
  );
}

const LETTER_KINDS: Record<string, string> = {
  offer: "Offer letter", contract: "Employment contract", welcome: "Onboarding welcome letter", conduct: "Conduct letter",
  resignation_acceptance: "Resignation acceptance", final_settlement: "Final settlement letter", experience: "Experience certificate",
};

export function LettersTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const letters = useQuery({ queryKey: ["hr", "letters"], queryFn: () => api<{ items: HRLetter[] }>("/api/hr/letters") });
  const emps = useQuery({ queryKey: ["hr", "employees", "", ""], queryFn: () => api<{ items: Employee[] }>("/api/hr/employees") });
  const [f, setF] = useState({ kind: "contract", employee_id: "", issue: "" });
  const make = useMutation({
    mutationFn: () => api<HRLetter>("/api/hr/letters", { body: { kind: f.kind, employee_id: Number(f.employee_id), fields: f.kind === "conduct" ? { issue: f.issue } : {} } }),
    onSuccess: (l) => { toast(`${l.title} created.`, "success"); void qc.invalidateQueries({ queryKey: ["hr", "letters"] }); },
    onError: (e) => toast(e instanceof ApiError ? e.message : String(e), "error"),
  });
  const send = useMutation({
    mutationFn: (id: number) => api(`/api/hr/letters/${id}/send`, { body: {}, idempotencyKey: newKey("letter") }),
    onSuccess: () => { toast("Letter emailed.", "success"); void qc.invalidateQueries({ queryKey: ["hr", "letters"] }); },
    onError: (e) => toast(e instanceof ApiError ? e.message : String(e), "error"),
  });
  return (
    <div className="flex flex-col gap-6">
      <Panel title="Create a letter">
        <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); if (f.employee_id) make.mutate(); }}>
          <Field label="Letter">{(id) => (
            <Select id={id} value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
              {Object.entries(LETTER_KINDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </Select>
          )}</Field>
          <Field label="Employee">{(id) => (
            <Select id={id} value={f.employee_id} required onChange={(e) => setF({ ...f, employee_id: e.target.value })}>
              <option value="">Choose</option>
              {(emps.data?.items ?? []).map((e) => <option key={e.id} value={e.id}>{e.full_name} ({e.code})</option>)}
            </Select>
          )}</Field>
          {f.kind === "conduct" && (
            <div className="w-72"><Field label="Conduct issue">{(id) => <Input id={id} required value={f.issue} onChange={(e) => setF({ ...f, issue: e.target.value })} placeholder="repeated late arrival in October" />}</Field></div>
          )}
          <Button type="submit" variant="primary" busy={make.isPending}>Create (Word and PDF)</Button>
        </form>
        <p className="mt-2 text-xs text-muted">To use your own format, put a Word file named after the letter (for example offer.docx) in data\hr_templates with placeholders like {"{{name}}"}, {"{{job_title}}"}, {"{{joining_date}}"}, {"{{salary}}"}.</p>
      </Panel>
      <Panel title="All letters">
        {letters.isError && <ErrorBox error={letters.error} />}
        {letters.data && (
          <Table caption="Letters" rows={letters.data.items} rowKey={(l) => l.id} empty="No letters yet."
            columns={[
              { key: "title", header: "Letter" }, { key: "recipient_email", header: "Recipient" },
              { key: "status", header: "Status", render: (l) => <StatusBadge status={l.status} /> },
              { key: "created_at", header: "Created", render: (l) => fmtDate(l.created_at) },
              { key: "act", header: "", render: (l) => (
                <span className="flex flex-wrap gap-2">
                  <Button size="sm" icon={<Download aria-hidden className="size-3.5" />} onClick={() => void openFile(`/api/hr/letters/${l.id}/pdf`)}>PDF</Button>
                  <Button size="sm" icon={<Download aria-hidden className="size-3.5" />} onClick={() => void openFile(`/api/hr/letters/${l.id}/docx`)}>Word</Button>
                  {l.recipient_email && l.status !== "sent" && (
                    <Button size="sm" icon={<Send aria-hidden className="size-3.5" />} busy={send.isPending} onClick={() => send.mutate(l.id)}>Email</Button>
                  )}
                </span>
              ) },
            ]} />
        )}
      </Panel>
    </div>
  );
}

const REPORT_KINDS: Record<string, string> = {
  new_joiners: "New joiners", induction: "Induction progress", onboarding: "Onboarding progress", separations: "Separations",
  attendance: "Attendance", leave: "Leave", compliance: "Compliance checklist", payroll: "Payroll", headcount: "Headcount",
};

export function ReportsTab() {
  const [kind, setKind] = useState("new_joiners");
  const [period, setPeriod] = useState("this month");
  const q = useQuery({
    queryKey: ["hr", "report", kind, period],
    queryFn: () => api<HRReport>(`/api/hr/reports?kind=${kind}&period=${encodeURIComponent(period)}`),
  });
  const toast = useToast();
  const matrix = useMutation({
    mutationFn: async () => {
      const r = await api<{ file: string }>("/api/hr/compliance/matrix");
      await openFile(`/api/hr/reports/file/${r.file}`);
    },
    onError: (e) => toast(e instanceof Error ? e.message : String(e), "error"),
  });
  const r = q.data;
  return (
    <Panel title="Reports" actions={<Button size="sm" busy={matrix.isPending} onClick={() => matrix.mutate()}>Compliance matrix (Excel)</Button>}>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="Report">{(id) => (
          <Select id={id} value={kind} onChange={(e) => setKind(e.target.value)}>
            {Object.entries(REPORT_KINDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </Select>
        )}</Field>
        <Field label="Period">{(id) => (
          <Select id={id} value={period} onChange={(e) => setPeriod(e.target.value)}>
            {["this month", "last month", "this week", "last 30 days", "last 90 days", "this year", "last year"].map((p) => <option key={p}>{p}</option>)}
          </Select>
        )}</Field>
        {r?.file && <Button icon={<Download aria-hidden className="size-4" />} onClick={() => void openFile(`/api/hr/reports/file/${r.file}`)}>Download Excel</Button>}
      </div>
      {q.isLoading && <Spinner />}
      {q.isError && <ErrorBox error={q.error} />}
      {r && (
        <div className="flex flex-col gap-3">
          <p className="text-sm"><span className="font-medium">{r.title}.</span> {r.summary}</p>
          <Table caption={r.title} rows={r.rows} rowKey={(x) => JSON.stringify(x)} empty="Nothing in this period."
            columns={r.columns.map((c) => ({ key: c, header: humanize(c), render: (x: Record<string, unknown>) => {
              const v = x[c];
              if (c === "status") return <StatusBadge status={String(v)} />;
              return v === null || v === undefined ? "" : String(v);
            } }))} />
        </div>
      )}
    </Panel>
  );
}
