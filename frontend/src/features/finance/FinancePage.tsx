import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";
import { Pencil, Plus, Trash2 } from "../../components/icons";
import { Dialog, TabPanel, Tabs } from "../../components/ui/overlays";
import { Badge, Button, ErrorBox, Field, IconButton, Input, Notice, PageHeader, Panel, Select, Spinner, Stat, Table, Textarea } from "../../components/ui/primitives";
import { api, ApiError, newKey } from "../../lib/api";
import { fmtDate, fmtMoney, humanize } from "../../lib/format";
import { useToast } from "../../lib/toast";
import type { FinanceSummary, Page, Payment, Person, ToolResult } from "../../lib/types";

const DEPARTMENTS = ["Finance", "HR", "IT", "Operations", "Sales", "Marketing", "Engineering", "Administration"];
const TYPES = ["full_time", "part_time", "contract", "intern"];
const CURRENCIES = ["PKR", "USD", "EUR", "GBP", "AED"];
type Form = Omit<Person, "id">;
const EMPTY: Form = {
  full_name: "", email: "", department: "", job_title: "", employment_type: "full_time", monthly_salary: "", currency: "PKR",
  status: "active", start_date: "", notes: "",
};

function validate(f: Form): Record<string, string> {
  const e: Record<string, string> = {};
  if (f.full_name.trim().length < 2) e.full_name = "Enter the full name.";
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(f.email)) e.email = "Enter a valid email address.";
  if (!f.department) e.department = "Choose a department.";
  if (f.job_title.trim().length < 2) e.job_title = "Enter the job title.";
  if (!/^\d{1,8}(\.\d{1,2})?$/.test(f.monthly_salary.replace(/,/g, ""))) e.monthly_salary = "Use digits only, for example 150000 or 150000.50.";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(f.start_date)) e.start_date = "Choose the start date.";
  return e;
}

function PersonDialog({ person, onClose }: { person: Person | "new"; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const isNew = person === "new";
  const key = useRef(newKey("fin"));
  const [f, setF] = useState<Form>(isNew ? EMPTY : { ...person });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const m = useMutation({
    mutationFn: () => {
      const body = { ...f, monthly_salary: f.monthly_salary.replace(/,/g, "") };
      if (isNew) return api("/api/finance/people", { body, idempotencyKey: key.current });
      const changed = Object.fromEntries(Object.entries(body).filter(([k, v]) => (person as unknown as Record<string, unknown>)[k] !== v));
      if (!Object.keys(changed).length) return Promise.resolve(null);
      return api(`/api/finance/people/${(person as Person).id}`, { method: "PATCH", body: changed, idempotencyKey: key.current });
    },
    onSuccess: () => {
      toast(isNew ? `${f.full_name} was added.` : "Changes saved.", "success");
      void qc.invalidateQueries({ queryKey: ["finance"] });
      onClose();
    },
    onError: (e) => {
      if (e instanceof ApiError && e.fields.length) setErrors(Object.fromEntries(e.fields.map((x) => [x.field.split(".").pop()!, x.message])));
      else if (e instanceof ApiError && e.status === 409) setErrors({ email: e.message });
    },
  });
  const set = (k: keyof Form, v: string) => setF((s) => ({ ...s, [k]: v }));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const errs = validate(f);
    setErrors(errs);
    if (!Object.keys(errs).length) m.mutate();
  };
  const text = (k: keyof Form, label: string, props: Record<string, unknown> = {}) => (
    <Field label={label} required error={errors[k]}>
      {(id, d, inv) => <Input id={id} aria-describedby={d} aria-invalid={inv} value={String(f[k])} onChange={(e) => set(k, e.target.value)} {...props} />}
    </Field>
  );
  const select = (k: keyof Form, label: string, options: string[], placeholder?: string) => (
    <Field label={label} required error={errors[k]}>
      {(id, d, inv) => (
        <Select id={id} aria-describedby={d} aria-invalid={inv} value={String(f[k])} onChange={(e) => set(k, e.target.value)}>
          {placeholder && <option value="">{placeholder}</option>}
          {options.map((o) => <option key={o} value={o}>{humanize(o)}</option>)}
        </Select>
      )}
    </Field>
  );
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()} title={isNew ? "Add a person" : `Edit ${person.full_name}`} wide
      description="Saved to the Finance Portal through finance-mcp. Your submission is recorded as approved by you."
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" type="submit" form="person-form" busy={m.isPending}>{isNew ? "Add person" : "Save changes"}</Button></>}>
      <form id="person-form" onSubmit={submit} className="grid grid-cols-1 gap-4 sm:grid-cols-2" noValidate>
        {m.isError && !Object.keys(errors).length && <div className="sm:col-span-2"><ErrorBox error={m.error} /></div>}
        {text("full_name", "Full name", { autoComplete: "off" })}
        {text("email", "Email", { type: "email", autoComplete: "off" })}
        {select("department", "Department", DEPARTMENTS, "Choose...")}
        {text("job_title", "Job title")}
        {select("employment_type", "Employment type", TYPES)}
        {select("status", "Status", ["active", "inactive"])}
        {text("monthly_salary", "Monthly salary", { inputMode: "decimal", placeholder: "150000.00" })}
        {select("currency", "Currency", CURRENCIES)}
        {text("start_date", "Start date", { type: "date" })}
        <div className="sm:col-span-2">
          <Field label="Notes">{(id) => <Textarea id={id} value={f.notes} maxLength={2000} onChange={(e) => set("notes", e.target.value)} />}</Field>
        </div>
      </form>
    </Dialog>
  );
}

function DeleteDialog({ person, onClose }: { person: Person; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [typed, setTyped] = useState("");
  const key = useRef(newKey("del"));
  const m = useMutation({
    mutationFn: () => api(`/api/finance/people/${person.id}`, { method: "DELETE", body: { confirm: true, confirm_name: typed }, idempotencyKey: key.current }),
    onSuccess: () => {
      toast(`${person.full_name} was deleted.`, "success");
      void qc.invalidateQueries({ queryKey: ["finance"] });
      onClose();
    },
  });
  const ok = typed.trim().toLowerCase() === person.full_name.toLowerCase();
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()} title={`Delete ${person.full_name}?`}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="danger" disabled={!ok} busy={m.isPending} onClick={() => m.mutate()}>Delete permanently</Button></>}>
      <div className="flex flex-col gap-3">
        <Notice tone="danger">This permanently deletes the record for {person.full_name} ({person.email}) and all of their payment records. It cannot be undone.</Notice>
        {m.isError && <ErrorBox error={m.error} />}
        <Field label={`Type ${person.full_name} to confirm`}>
          {(id) => <Input id={id} value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />}
        </Field>
      </div>
    </Dialog>
  );
}

/* CSV of the rows on screen. Cells that a spreadsheet would run as a formula are prefixed with '. */
function downloadCsv(rows: Person[]) {
  const cols: (keyof Person)[] = ["full_name", "email", "department", "job_title", "employment_type", "monthly_salary", "currency", "status", "start_date"];
  const cell = (v: unknown) => {
    let t = String(v ?? "");
    if (/^[=+\-@\t\r]/.test(t)) t = "'" + t;
    return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
  };
  const csv = [cols.join(","), ...rows.map((r) => cols.map((c) => cell(r[c])).join(","))].join("\r\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `people-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

function PeopleTab() {
  const [q, setQ] = useState("");
  const [dept, setDept] = useState("");
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Person | "new" | null>(null);
  const [deleting, setDeleting] = useState<Person | null>(null);
  const params = new URLSearchParams({ page: String(page), page_size: "25", ...(q ? { q } : {}), ...(dept ? { department: dept } : {}) });
  const people = useQuery({ queryKey: ["finance", "people", params.toString()], queryFn: () => api<ToolResult<Page<Person>>>(`/api/finance/people?${params}`) });
  const data = people.data?.result;
  return (
    <Panel title="People" actions={
      <span className="flex gap-2">
        <Button size="sm" disabled={!data?.items.length} onClick={() => data && downloadCsv(data.items)}>Download CSV</Button>
        <Button variant="primary" size="sm" icon={<Plus aria-hidden className="size-4" />} onClick={() => setEditing("new")}>Add person</Button>
      </span>
    }>
      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Field label="Search">{(id) => <Input id={id} value={q} placeholder="Name, email or job title" onChange={(e) => { setPage(1); setQ(e.target.value); }} />}</Field>
        <Field label="Department">
          {(id) => (
            <Select id={id} value={dept} onChange={(e) => { setPage(1); setDept(e.target.value); }}>
              <option value="">All</option>
              {DEPARTMENTS.map((d) => <option key={d}>{d}</option>)}
            </Select>
          )}
        </Field>
      </div>
      {people.isLoading && <Spinner />}
      {people.isError && <ErrorBox error={people.error} onRetry={() => void people.refetch()} />}
      {data && (
        <>
          <Table
            caption="People records"
            columns={[
              { key: "full_name", header: "Name", render: (p: Person) => <span><span className="font-medium">{p.full_name}</span><span className="block text-xs text-muted">{p.email}</span></span> },
              { key: "department", header: "Department" },
              { key: "job_title", header: "Job title" },
              { key: "monthly_salary", header: "Monthly salary", className: "text-right tabular-nums", render: (p) => fmtMoney(p.monthly_salary, p.currency) },
              { key: "status", header: "Status", render: (p) => <Badge tone={p.status === "active" ? "success" : "neutral"}>{humanize(p.status)}</Badge> },
              { key: "actions", header: "", className: "text-right", render: (p) => (
                <span className="inline-flex gap-1">
                  <IconButton label={`Edit ${p.full_name}`} onClick={() => setEditing(p)}><Pencil aria-hidden className="size-4" /></IconButton>
                  <IconButton label={`Delete ${p.full_name}`} onClick={() => setDeleting(p)}><Trash2 aria-hidden className="size-4" /></IconButton>
                </span>
              ) },
            ]}
            rows={data.items}
            rowKey={(p) => p.id}
            empty="No people match."
          />
          <div className="mt-3 flex items-center justify-between gap-2 text-sm text-muted">
            <span>{data.total} record(s)</span>
            {(data.pages ?? 1) > 1 && (
              <span className="flex items-center gap-2">
                <Button size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</Button>
                Page {data.page} of {data.pages}
                <Button size="sm" disabled={page >= (data.pages ?? 1)} onClick={() => setPage((p) => p + 1)}>Next</Button>
              </span>
            )}
          </div>
        </>
      )}
      {editing && <PersonDialog person={editing} onClose={() => setEditing(null)} />}
      {deleting && <DeleteDialog person={deleting} onClose={() => setDeleting(null)} />}
    </Panel>
  );
}

function PaymentsTab() {
  const [month, setMonth] = useState("");
  const [status, setStatus] = useState("");
  const params = new URLSearchParams({ page_size: "100", ...(month ? { month } : {}), ...(status ? { status } : {}) });
  const q = useQuery({ queryKey: ["finance", "payments", params.toString()], queryFn: () => api<ToolResult<Page<Payment>>>(`/api/finance/payments?${params}`) });
  return (
    <Panel title="Payments">
      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Field label="Month">{(id) => <Input id={id} type="month" value={month} onChange={(e) => setMonth(e.target.value)} />}</Field>
        <Field label="Status">
          {(id) => (
            <Select id={id} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">Any</option>
              {["pending", "paid", "failed"].map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
            </Select>
          )}
        </Field>
      </div>
      {q.isLoading && <Spinner />}
      {q.isError && <ErrorBox error={q.error} />}
      {q.data && (
        <Table
          caption="Payments"
          columns={[
            { key: "person_name", header: "Person" },
            { key: "month", header: "Month" },
            { key: "amount", header: "Amount", className: "text-right tabular-nums", render: (p: Payment) => fmtMoney(p.amount, p.currency) },
            { key: "status", header: "Status", render: (p) => <Badge tone={p.status === "paid" ? "success" : p.status === "failed" ? "danger" : "warning"}>{humanize(p.status)}</Badge> },
            { key: "paid_on", header: "Paid on", render: (p) => fmtDate(p.paid_on) },
          ]}
          rows={q.data.result.items}
          rowKey={(p) => p.id}
          empty="No payments match."
        />
      )}
    </Panel>
  );
}

export function FinancePage() {
  const [tab, setTab] = useState("people");
  const sum = useQuery({ queryKey: ["finance", "summary"], queryFn: () => api<ToolResult<FinanceSummary>>("/api/finance/summary") });
  const s = sum.data?.result;
  return (
    <div>
      <PageHeader title="Finance" description="People records and payments in the Finance Portal. Totals are computed by SQL in the portal, never by a model." />
      {sum.isError && <ErrorBox error={sum.error} onRetry={() => void sum.refetch()} />}
      {s && (
        <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4" data-testid="finance-summary">
          <Stat label="People" value={s.people_total} hint={`${s.people_active} active, ${s.people_inactive} inactive`} />
          {s.payroll_by_currency.map((c) => (
            <Stat key={c.currency} label={`Monthly payroll (${c.currency})`} value={fmtMoney(c.total_monthly_payroll, c.currency)} hint={`${c.active_people} active people`} />
          ))}
          <Stat label="Computed by" value={<span className="text-base">{s.computed_by}</span>} />
        </div>
      )}
      <Tabs value={tab} onValueChange={setTab} label="Finance sections" tabs={[{ value: "people", label: "People" }, { value: "payments", label: "Payments" }, { value: "departments", label: "By department" }]}>
        <TabPanel value="people"><PeopleTab /></TabPanel>
        <TabPanel value="payments"><PaymentsTab /></TabPanel>
        <TabPanel value="departments">
          <Panel title="Payroll by department">
            {s ? (
              <Table
                columns={[
                  { key: "department", header: "Department" },
                  { key: "active_people", header: "Active people", className: "text-right tabular-nums" },
                  { key: "total", header: "Monthly payroll", className: "text-right tabular-nums", render: (r: FinanceSummary["payroll_by_department"][number]) => fmtMoney(r.total_monthly_payroll, r.currency) },
                ]}
                rows={s.payroll_by_department}
                rowKey={(r) => `${r.department}-${r.currency}`}
              />
            ) : <Spinner />}
          </Panel>
        </TabPanel>
      </Tabs>
    </div>
  );
}
