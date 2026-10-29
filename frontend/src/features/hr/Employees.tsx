import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type InputHTMLAttributes } from "react";
import { Download, RefreshCw, UserPlus } from "../../components/icons";
import { Dialog, TabPanel, Tabs } from "../../components/ui/overlays";
import { Button, ErrorBox, Field, Input, Notice, Panel, Select, Spinner, Table, Textarea } from "../../components/ui/primitives";
import { api, ApiError, newKey, openFile } from "../../lib/api";
import { fmtDate, humanize } from "../../lib/format";
import { useToast } from "../../lib/toast";
import type { Employee, EmployeeDetail, HRTask } from "../../lib/types";
import { DEPARTMENTS, money, ProgressBar, StatusBadge, useAsk } from "./common";

const STATUSES = ["", "offered", "onboarding", "active", "notice", "separated"];
const OWNER: Record<string, string> = { hr: "HR", it: "IT", finance: "Finance", manager: "Manager", employee: "Employee" };
const EDITABLE = ["full_name", "email", "phone", "job_title", "department", "manager", "location", "employment_type", "status",
  "joining_date", "probation_end", "last_working_day", "monthly_salary", "allowances", "bank_account_on_file", "notes"];

function patchBody(edit: Partial<Employee>): Partial<Employee> {
  const src = edit as unknown as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  for (const k of EDITABLE) if (k in src) out[k] = src[k];
  if (!out.email) delete out.email;
  return out as Partial<Employee>;
}

interface OnboardForm {
  name: string; job: string; dept: string; joining: string; salary: string; email: string; phone: string; manager: string;
}

function OnboardDialog({ onClose }: { onClose: () => void }) {
  const [f, setF] = useState<OnboardForm>({ name: "", job: "", dept: "Engineering", joining: "", salary: "", email: "", phone: "", manager: "" });
  const { ask, busy, view } = useAsk();
  const set = (k: keyof OnboardForm, v: string) => setF({ ...f, [k]: v });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const parts = [`Onboard ${f.name.trim()} as ${f.job.trim()} in ${f.dept}`, `joining ${f.joining}`];
    if (f.salary.trim()) parts.push(`salary ${f.salary.trim()}`);
    if (f.email.trim()) parts.push(`email ${f.email.trim()}`);
    if (f.phone.trim()) parts.push(`phone ${f.phone.trim()}`);
    if (f.manager.trim()) parts.push(`reporting to ${f.manager.trim()}`);
    ask(parts.join(", "));
  };
  const input = (k: keyof OnboardForm, label: string, props: InputHTMLAttributes<HTMLInputElement> = {}) => (
    <Field label={label}>{(id, d) => <Input id={id} aria-describedby={d} value={f[k]} onChange={(e) => set(k, e.target.value)} {...props} />}</Field>
  );
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()} title="Onboard a new joiner" wide
      description="AgentsMind prepares every step (record, checklists, contract, welcome letter and email, IT ticket, payroll, induction invites, WhatsApp, your HR sheet) on one approval card.">
      <form className="grid grid-cols-1 gap-3 sm:grid-cols-2" onSubmit={submit}>
        {input("name", "Full name", { required: true })}
        {input("job", "Job title", { required: true })}
        <Field label="Department">
          {(id) => <Select id={id} value={f.dept} onChange={(e) => set("dept", e.target.value)}>{DEPARTMENTS.map((d) => <option key={d}>{d}</option>)}</Select>}
        </Field>
        {input("joining", "Joining date", { type: "date", required: true })}
        {input("salary", "Monthly gross salary (PKR)", { inputMode: "numeric" })}
        {input("email", "Email", { type: "email" })}
        {input("phone", "Mobile (WhatsApp)", { placeholder: "03001234567" })}
        {input("manager", "Reports to")}
        <div className="sm:col-span-2">
          <Button type="submit" variant="primary" busy={busy} icon={<UserPlus aria-hidden className="size-4" />}>Prepare onboarding</Button>
        </div>
      </form>
      {view}
    </Dialog>
  );
}

function AddEmployeeDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [f, setF] = useState({ full_name: "", email: "", job_title: "", department: "Engineering", joining_date: "", monthly_salary: "", phone: "" });
  const m = useMutation({
    mutationFn: () => api<Employee>("/api/hr/employees", {
      body: { ...f, email: f.email || null, joining_date: f.joining_date || null, monthly_salary: Number(f.monthly_salary || 0), status: "active" },
    }),
    onSuccess: (e) => {
      toast(`${e.full_name} (${e.code}) added.`, "success");
      void qc.invalidateQueries({ queryKey: ["hr"] });
      onClose();
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : String(e), "error"),
  });
  const input = (k: keyof typeof f, label: string, props: InputHTMLAttributes<HTMLInputElement> = {}) => (
    <Field label={label}>{(id, d) => <Input id={id} aria-describedby={d} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} {...props} />}</Field>
  );
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()} title="Add an existing employee" description="For staff who already work here (no onboarding steps)."
      footer={<Button variant="primary" busy={m.isPending} disabled={!f.full_name.trim()} onClick={() => m.mutate()}>Add</Button>}>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {input("full_name", "Full name", { required: true })}
        {input("email", "Email", { type: "email" })}
        {input("job_title", "Job title")}
        <Field label="Department">
          {(id) => <Select id={id} value={f.department} onChange={(e) => setF({ ...f, department: e.target.value })}>{DEPARTMENTS.map((d) => <option key={d}>{d}</option>)}</Select>}
        </Field>
        {input("joining_date", "Joining date", { type: "date" })}
        {input("monthly_salary", "Monthly gross salary (PKR)", { inputMode: "numeric" })}
        {input("phone", "Mobile")}
      </div>
    </Dialog>
  );
}

function TaskList({ tasks, process }: { tasks: HRTask[]; process: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const set = useMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) => api<HRTask>(`/api/hr/tasks/${id}`, { method: "PATCH", body: { status } }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["hr"] }),
    onError: (e) => toast(e instanceof ApiError ? e.message : String(e), "error"),
  });
  const retry = useMutation({
    mutationFn: (id: number) => api<{ result: { steps: { status: string; error: string }[] } }>(`/api/hr/tasks/${id}/retry`, { body: {}, idempotencyKey: newKey("retry") }),
    onSuccess: (r) => {
      const s = r.result.steps[0];
      toast(s?.status === "ok" ? "Done." : `Still failing: ${s?.error ?? ""}`, s?.status === "ok" ? "success" : "error");
      void qc.invalidateQueries({ queryKey: ["hr"] });
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : String(e), "error"),
  });
  const mine = tasks.filter((t) => t.process === process);
  if (!mine.length) return <p className="text-sm text-muted">No {process} checklist yet.</p>;
  return (
    <ul className="flex flex-col divide-y divide-border rounded-md border border-border">
      {mine.map((t) => (
        <li key={t.id} className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm">
          <input type="checkbox" aria-label={`${t.title} done`} checked={t.status === "done" || t.status === "skipped"}
            onChange={(e) => set.mutate({ id: t.id, status: e.target.checked ? "done" : "pending" })} className="size-4 accent-[var(--color-primary)]" />
          <span className="min-w-48 flex-1">
            {t.title}
            {t.result?.summary && <span className="block text-xs text-muted">{String(t.result.summary)}</span>}
            {t.status === "failed" && t.result?.error && <span className="block text-xs text-danger">{String(t.result.error)}</span>}
          </span>
          <span className="text-xs text-muted">{OWNER[t.owner] ?? humanize(t.owner)}{t.due_date ? `, due ${fmtDate(t.due_date)}` : ""}</span>
          <StatusBadge status={t.status} />
          {t.status === "failed" && !!t.result?.step && (
            <Button size="sm" busy={retry.isPending} icon={<RefreshCw aria-hidden className="size-3.5" />} onClick={() => retry.mutate(t.id)}>Retry</Button>
          )}
        </li>
      ))}
    </ul>
  );
}

export function EmployeeDialog({ id, onClose }: { id: number; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [tab, setTab] = useState("checklists");
  const q = useQuery({ queryKey: ["hr", "employee", id], queryFn: () => api<EmployeeDetail>(`/api/hr/employees/${id}`) });
  const [edit, setEdit] = useState<Partial<Employee> | null>(null);
  const { ask, busy, view } = useAsk();
  const [lastDay, setLastDay] = useState("");
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: (body: Partial<Employee>) => api<Employee>(`/api/hr/employees/${id}`, { method: "PATCH", body }),
    onSuccess: () => {
      toast("Saved.", "success");
      setEdit(null);
      void qc.invalidateQueries({ queryKey: ["hr"] });
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : String(e), "error"),
  });
  const mk = useMutation({
    mutationFn: (process: string) => api(`/api/hr/employees/${id}/checklists`, { body: { process } }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["hr"] }),
  });
  const d = q.data;
  const e = d?.employee;
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()} wide title={e ? `${e.full_name} (${e.code})` : "Employee"}
      description={e ? `${e.job_title || "-"}, ${e.department || "-"}. ${humanize(e.status)}${e.joining_date ? `, joined ${fmtDate(e.joining_date)}` : ""}` : undefined}>
      {q.isLoading && <Spinner />}
      {q.isError && <ErrorBox error={q.error} />}
      {d && e && (
        <Tabs value={tab} onValueChange={setTab} label="Employee sections" tabs={[
          { value: "checklists", label: "Checklists" }, { value: "profile", label: "Profile" }, { value: "letters", label: "Letters" },
          { value: "time", label: "Leave and attendance" }, { value: "exit", label: "Separation" },
        ]}>
          <TabPanel value="checklists" className="flex flex-col gap-4">
            {(["onboarding", "induction", "compliance", "separation"] as const).map((p) => (
              <section key={p}>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <h3 className="text-sm font-semibold">{humanize(p)}</h3>
                  <ProgressBar p={d.progress[p]} label={humanize(p)} />
                  {!d.progress[p]?.total && p !== "separation" && <Button size="sm" busy={mk.isPending} onClick={() => mk.mutate(p)}>Create</Button>}
                </div>
                <TaskList tasks={d.tasks} process={p} />
              </section>
            ))}
          </TabPanel>
          <TabPanel value="profile">
            {!edit ? (
              <div className="flex flex-col gap-3">
                <dl className="grid grid-cols-1 gap-x-4 gap-y-1.5 text-sm sm:grid-cols-[11rem_1fr]">
                  {([["Email", e.email], ["Mobile", e.phone], ["Job title", e.job_title], ["Department", e.department], ["Reports to", e.manager],
                    ["Location", e.location], ["Employment type", humanize(e.employment_type)], ["Joining date", fmtDate(e.joining_date)],
                    ["Probation ends", fmtDate(e.probation_end)], ["Monthly gross", money(e.monthly_salary, e.currency)],
                    ["Bank details on file", e.bank_account_on_file ? "Yes" : "No"], ["Finance Portal record", e.finance_person_id || "not yet"],
                    ["Notes", e.notes]] as [string, string][]).map(([k, v]) => (
                    <div key={k} className="contents"><dt className="text-muted">{k}</dt><dd className="break-words">{v || "-"}</dd></div>
                  ))}
                </dl>
                <div><Button size="sm" onClick={() => setEdit({ ...e })}>Edit</Button></div>
              </div>
            ) : (
              <form className="grid grid-cols-1 gap-3 sm:grid-cols-2" onSubmit={(ev) => { ev.preventDefault(); save.mutate(patchBody(edit)); }}>
                {(["full_name", "email", "phone", "job_title", "department", "manager", "location"] as const).map((k) => (
                  <Field key={k} label={humanize(k)}>{(fid) => <Input id={fid} value={String(edit[k] ?? "")} onChange={(ev) => setEdit({ ...edit, [k]: ev.target.value })} />}</Field>
                ))}
                <Field label="Joining date">{(fid) => <Input id={fid} type="date" value={edit.joining_date ?? ""} onChange={(ev) => setEdit({ ...edit, joining_date: ev.target.value || null })} />}</Field>
                <Field label="Monthly gross salary">{(fid) => <Input id={fid} inputMode="numeric" value={String(edit.monthly_salary ?? 0)} onChange={(ev) => setEdit({ ...edit, monthly_salary: Number(ev.target.value || 0) })} />}</Field>
                <Field label="Status">{(fid) => (
                  <Select id={fid} value={edit.status} onChange={(ev) => setEdit({ ...edit, status: ev.target.value as Employee["status"] })}>
                    {STATUSES.filter(Boolean).map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
                  </Select>
                )}</Field>
                <Field label="Notes">{(fid) => <Textarea id={fid} value={edit.notes ?? ""} onChange={(ev) => setEdit({ ...edit, notes: ev.target.value })} />}</Field>
                <div className="flex gap-2 sm:col-span-2">
                  <Button type="submit" variant="primary" busy={save.isPending}>Save</Button>
                  <Button onClick={() => setEdit(null)}>Cancel</Button>
                </div>
              </form>
            )}
          </TabPanel>
          <TabPanel value="letters" className="flex flex-col gap-3">
            <Table caption="Letters" rows={d.letters} rowKey={(l) => l.id} empty="No letters yet."
              columns={[
                { key: "title", header: "Letter" },
                { key: "status", header: "Status", render: (l) => <StatusBadge status={l.status} /> },
                { key: "created_at", header: "Created", render: (l) => fmtDate(l.created_at) },
                { key: "files", header: "Files", render: (l) => (
                  <span className="flex gap-2">
                    <Button size="sm" icon={<Download aria-hidden className="size-3.5" />} onClick={() => void openFile(`/api/hr/letters/${l.id}/pdf`)}>PDF</Button>
                    <Button size="sm" icon={<Download aria-hidden className="size-3.5" />} onClick={() => void openFile(`/api/hr/letters/${l.id}/docx`)}>Word</Button>
                  </span>
                ) },
              ]} />
            <div className="flex flex-wrap gap-2">
              {(["contract", "welcome", "experience"] as const).map((k) => (
                <Button key={k} size="sm" busy={busy} onClick={() => ask(`${k === "contract" ? "Employment contract" : k === "welcome" ? "Welcome letter" : "Experience letter"} for ${e.full_name}`)}>
                  {k === "contract" ? "Contract" : k === "welcome" ? "Welcome letter" : "Experience letter"}
                </Button>
              ))}
            </div>
            {view}
          </TabPanel>
          <TabPanel value="time" className="flex flex-col gap-4">
            <Table caption="Leave balance" rowKey={(r) => r.type}
              rows={Object.entries(d.balances).filter(([, v]) => v.entitled || v.taken).map(([k, v]) => ({ type: k, ...v }))}
              columns={[{ key: "type", header: "Type", render: (r) => humanize(r.type) }, { key: "entitled", header: "Entitled" }, { key: "taken", header: "Taken" }, { key: "remaining", header: "Remaining" }]} />
            <Table caption="Leave requests" rows={d.leave} rowKey={(r) => r.id} empty="No leave requests."
              columns={[{ key: "leave_type", header: "Type", render: (r) => humanize(r.leave_type) }, { key: "start_date", header: "From", render: (r) => fmtDate(r.start_date) },
                { key: "end_date", header: "To", render: (r) => fmtDate(r.end_date) }, { key: "days", header: "Days" }, { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> }]} />
            <Table caption="Attendance this month" rows={d.attendance} rowKey={(r) => r.day} empty="No attendance marked this month."
              columns={[{ key: "day", header: "Day", render: (r) => fmtDate(r.day) }, { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> },
                { key: "check_in", header: "In" }, { key: "check_out", header: "Out" }]} />
          </TabPanel>
          <TabPanel value="exit" className="flex flex-col gap-3">
            {d.separation ? (
              <Notice tone="info" title={`${humanize(d.separation.kind)}: last working day ${fmtDate(d.separation.last_working_day)}`}>
                Status: {humanize(d.separation.status)}. The separation checklist is on the Checklists tab.
              </Notice>
            ) : <p className="text-sm text-muted">No separation in progress.</p>}
            <form className="flex flex-wrap items-end gap-3" onSubmit={(ev) => { ev.preventDefault(); ask(`${e.full_name} resigned, last working day ${lastDay}${reason ? `, because ${reason}` : ""}`); }}>
              <Field label="Last working day">{(fid) => <Input id={fid} type="date" required value={lastDay} onChange={(ev) => setLastDay(ev.target.value)} />}</Field>
              <div className="w-64"><Field label="Reason (optional)">{(fid) => <Input id={fid} value={reason} onChange={(ev) => setReason(ev.target.value)} />}</Field></div>
              <Button type="submit" busy={busy}>Start resignation</Button>
              <Button busy={busy} onClick={() => ask(`Final settlement for ${e.full_name}`)} disabled={!d.separation}>Final settlement</Button>
            </form>
            {view}
          </TabPanel>
        </Tabs>
      )}
    </Dialog>
  );
}

export function EmployeesTab({ initialOpen }: { initialOpen?: number }) {
  const [status, setStatus] = useState("");
  const [qtext, setQ] = useState("");
  const [open, setOpen] = useState<number | null>(initialOpen ?? null);
  const [dlg, setDlg] = useState<"" | "onboard" | "add">("");
  const q = useQuery({
    queryKey: ["hr", "employees", status, qtext],
    queryFn: () => api<{ items: Employee[] }>(`/api/hr/employees?status=${encodeURIComponent(status)}&q=${encodeURIComponent(qtext)}`),
  });
  return (
    <Panel title="Employees and new joiners" actions={
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" icon={<UserPlus aria-hidden className="size-4" />} onClick={() => setDlg("onboard")}>Onboard a new joiner</Button>
        <Button onClick={() => setDlg("add")}>Add existing employee</Button>
      </div>
    }>
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <div className="w-56"><Field label="Search">{(id) => <Input id={id} value={qtext} onChange={(e) => setQ(e.target.value)} placeholder="Name, email, title or EMP-0001" />}</Field></div>
        <Field label="Status">{(id) => (
          <Select id={id} value={status} onChange={(e) => setStatus(e.target.value)}>
            {STATUSES.map((s) => <option key={s} value={s}>{s ? humanize(s) : "All"}</option>)}
          </Select>
        )}</Field>
      </div>
      {q.isLoading && <Spinner />}
      {q.isError && <ErrorBox error={q.error} onRetry={() => void q.refetch()} />}
      {q.data && (
        <Table caption="Employees" rows={q.data.items} rowKey={(e) => e.id} onRowClick={(e) => setOpen(e.id)}
          empty="No employees yet. Onboard a new joiner, add existing staff, or ask the assistant."
          columns={[
            { key: "code", header: "Code" },
            { key: "full_name", header: "Name", render: (e) => <span className="font-medium">{e.full_name}</span> },
            { key: "job_title", header: "Job title" },
            { key: "department", header: "Department" },
            { key: "status", header: "Status", render: (e) => <StatusBadge status={e.status} /> },
            { key: "joining_date", header: "Joining", render: (e) => fmtDate(e.joining_date) },
            { key: "onboarding", header: "Onboarding", render: (e) => <ProgressBar p={e.onboarding} label="Onboarding" /> },
          ]} />
      )}
      {open !== null && <EmployeeDialog id={open} onClose={() => setOpen(null)} />}
      {dlg === "onboard" && <OnboardDialog onClose={() => setDlg("")} />}
      {dlg === "add" && <AddEmployeeDialog onClose={() => setDlg("")} />}
    </Panel>
  );
}
