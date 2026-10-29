import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Check, X } from "../../components/icons";
import { Button, ErrorBox, Field, Input, Panel, Select, Spinner, Table } from "../../components/ui/primitives";
import { api, ApiError } from "../../lib/api";
import { fmtDate, humanize } from "../../lib/format";
import { useToast } from "../../lib/toast";
import type { AttendanceRow, Employee, LeaveRow } from "../../lib/types";
import { StatusBadge, useAsk } from "./common";

interface Summary {
  employee_id: number; code: string; name: string; department: string; working_days: number; present: number; late: number;
  absent: number; half_day: number; leave: number; wfh: number; unmarked: number;
}

function monthStart(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
}

function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function MarkForm() {
  const qc = useQueryClient();
  const toast = useToast();
  const emps = useQuery({ queryKey: ["hr", "employees", "active,onboarding,notice", ""], queryFn: () => api<{ items: Employee[] }>("/api/hr/employees?status=active,onboarding,notice") });
  const [f, setF] = useState({ employee_id: "", day: today(), status: "present", check_in: "", check_out: "" });
  const m = useMutation({
    mutationFn: () => api("/api/hr/attendance", { body: { ...f, employee_id: Number(f.employee_id) } }),
    onSuccess: () => { toast("Attendance saved.", "success"); void qc.invalidateQueries({ queryKey: ["hr"] }); },
    onError: (e) => toast(e instanceof ApiError ? e.message : String(e), "error"),
  });
  return (
    <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); if (f.employee_id) m.mutate(); }}>
      <Field label="Employee">{(id) => (
        <Select id={id} value={f.employee_id} required onChange={(e) => setF({ ...f, employee_id: e.target.value })}>
          <option value="">Choose</option>
          {(emps.data?.items ?? []).map((e) => <option key={e.id} value={e.id}>{e.full_name} ({e.code})</option>)}
        </Select>
      )}</Field>
      <Field label="Day">{(id) => <Input id={id} type="date" value={f.day} onChange={(e) => setF({ ...f, day: e.target.value })} />}</Field>
      <Field label="Status">{(id) => (
        <Select id={id} value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}>
          {["present", "late", "absent", "half_day", "wfh", "leave", "holiday"].map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
        </Select>
      )}</Field>
      <Field label="In">{(id) => <Input id={id} type="time" value={f.check_in} onChange={(e) => setF({ ...f, check_in: e.target.value })} />}</Field>
      <Field label="Out">{(id) => <Input id={id} type="time" value={f.check_out} onChange={(e) => setF({ ...f, check_out: e.target.value })} />}</Field>
      <Button type="submit" variant="primary" busy={m.isPending}>Save</Button>
    </form>
  );
}

export function TimeLeaveTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const [start, setStart] = useState(monthStart());
  const [end, setEnd] = useState(today());
  const att = useQuery({
    queryKey: ["hr", "attendance", start, end],
    queryFn: () => api<{ rows: AttendanceRow[]; summary: Summary[] }>(`/api/hr/attendance?start=${start}&end=${end}`),
  });
  const pending = useQuery({ queryKey: ["hr", "leave", "pending"], queryFn: () => api<{ items: LeaveRow[] }>("/api/hr/leave?status=pending") });
  const all = useQuery({ queryKey: ["hr", "leave", "all"], queryFn: () => api<{ items: LeaveRow[] }>("/api/hr/leave") });
  const decide = useMutation({
    mutationFn: ({ id, approve }: { id: number; approve: boolean }) => api<LeaveRow>(`/api/hr/leave/${id}/decide`, { body: { approve } }),
    onSuccess: (r) => { toast(`${r.name}'s leave ${r.status}.`, "success"); void qc.invalidateQueries({ queryKey: ["hr"] }); },
    onError: (e) => toast(e instanceof ApiError ? e.message : String(e), "error"),
  });
  const { ask, busy, view } = useAsk();
  return (
    <div className="flex flex-col gap-6">
      <Panel title="Leave requests waiting for a decision">
        {pending.isError && <ErrorBox error={pending.error} />}
        {pending.data && (
          <Table caption="Pending leave" rows={pending.data.items} rowKey={(r) => r.id} empty="No pending requests."
            columns={[
              { key: "name", header: "Employee" }, { key: "leave_type", header: "Type", render: (r) => humanize(r.leave_type) },
              { key: "start_date", header: "From", render: (r) => fmtDate(r.start_date) }, { key: "end_date", header: "To", render: (r) => fmtDate(r.end_date) },
              { key: "days", header: "Days" }, { key: "reason", header: "Reason" },
              { key: "act", header: "Decision", render: (r) => (
                <span className="flex gap-2">
                  <Button size="sm" variant="primary" icon={<Check aria-hidden className="size-3.5" />} busy={decide.isPending} onClick={() => decide.mutate({ id: r.id, approve: true })}>Approve</Button>
                  <Button size="sm" icon={<X aria-hidden className="size-3.5" />} busy={decide.isPending} onClick={() => decide.mutate({ id: r.id, approve: false })}>Reject</Button>
                </span>
              ) },
            ]} />
        )}
      </Panel>
      <Panel title="Attendance" actions={<Button size="sm" busy={busy} onClick={() => ask("Import attendance from my attendance sheet")}>Import from my attendance sheet</Button>}>
        <div className="mb-4 flex flex-wrap items-end gap-3">
          <Field label="From">{(id) => <Input id={id} type="date" value={start} onChange={(e) => setStart(e.target.value)} />}</Field>
          <Field label="To">{(id) => <Input id={id} type="date" value={end} onChange={(e) => setEnd(e.target.value)} />}</Field>
        </div>
        {view}
        {att.isLoading && <Spinner />}
        {att.isError && <ErrorBox error={att.error} />}
        {att.data && (
          <Table caption="Attendance summary" rows={att.data.summary} rowKey={(r) => r.employee_id} empty="No employees."
            columns={[
              { key: "name", header: "Employee" }, { key: "working_days", header: "Working days" }, { key: "present", header: "Present" },
              { key: "late", header: "Late" }, { key: "absent", header: "Absent" }, { key: "half_day", header: "Half days" },
              { key: "leave", header: "On leave" }, { key: "wfh", header: "WFH" }, { key: "unmarked", header: "Not marked" },
            ]} />
        )}
        <h3 className="mb-2 mt-6 text-sm font-semibold">Mark attendance</h3>
        <MarkForm />
      </Panel>
      <Panel title="All leave requests">
        {all.data && (
          <Table caption="Leave requests" rows={all.data.items} rowKey={(r) => r.id} empty="No leave requests yet."
            columns={[
              { key: "name", header: "Employee" }, { key: "leave_type", header: "Type", render: (r) => humanize(r.leave_type) },
              { key: "start_date", header: "From", render: (r) => fmtDate(r.start_date) }, { key: "end_date", header: "To", render: (r) => fmtDate(r.end_date) },
              { key: "days", header: "Days" }, { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> },
            ]} />
        )}
      </Panel>
    </div>
  );
}
