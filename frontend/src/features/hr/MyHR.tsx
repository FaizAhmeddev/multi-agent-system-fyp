import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { LogIn } from "../../components/icons";
import { Button, Field, Input, Panel, Select, Table } from "../../components/ui/primitives";
import { api, ApiError } from "../../lib/api";
import { fmtDate, humanize } from "../../lib/format";
import { useToast } from "../../lib/toast";
import type { AttendanceRow, Balances, Employee, LeaveRow } from "../../lib/types";
import { StatusBadge } from "./common";

interface Me {
  employee: Partial<Employee> | null;
  balances?: Balances;
  leave?: LeaveRow[];
  attendance?: AttendanceRow[];
}

/* Self-service for every staff member: check in and out, own leave balance, apply for leave. */
export function MyHRPanel() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["me", "hr"], queryFn: () => api<Me>("/api/me/hr") });
  const [f, setF] = useState({ leave_type: "casual", start_date: "", end_date: "", reason: "" });
  const check = useMutation({
    mutationFn: () => api<{ action: string; check_in: string; check_out: string; status: string }>("/api/me/attendance/check", { body: {} }),
    onSuccess: (r) => {
      toast(r.action === "check_in" ? `Checked in at ${r.check_in}${r.status === "late" ? " (late)" : ""}.` : `Checked out at ${r.check_out}.`, "success");
      void qc.invalidateQueries({ queryKey: ["me", "hr"] });
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : String(e), "error"),
  });
  const apply = useMutation({
    mutationFn: () => api<LeaveRow>("/api/me/leave", { body: { ...f, end_date: f.end_date || f.start_date } }),
    onSuccess: (r) => {
      toast(`${humanize(r.leave_type)} leave requested (${r.days} day(s)). HR will decide.`, "success");
      void qc.invalidateQueries({ queryKey: ["me", "hr"] });
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : String(e), "error"),
  });
  if (!q.data?.employee) return null;
  const today = new Date().toISOString().slice(0, 10);
  const row = q.data.attendance?.find((a) => a.day === today);
  const bal = Object.entries(q.data.balances ?? {}).filter(([k, v]) => k !== "unpaid" && v.entitled);
  return (
    <Panel title="My attendance and leave">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" busy={check.isPending} icon={<LogIn aria-hidden className="size-4" />} onClick={() => check.mutate()}>
          {row?.check_in && !row.check_out ? "Check out" : row?.check_out ? "Checked out" : "Check in"}
        </Button>
        <span className="text-sm text-muted">
          {row ? `Today: in ${row.check_in || "-"}, out ${row.check_out || "-"}` : "Not checked in today."}
        </span>
      </div>
      {!!bal.length && (
        <p className="mt-3 text-sm">{bal.map(([k, v]) => `${humanize(k)} ${v.remaining}/${v.entitled}`).join(" · ")} days left</p>
      )}
      <form className="mt-4 flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); if (f.start_date) apply.mutate(); }}>
        <Field label="Leave">{(id) => (
          <Select id={id} value={f.leave_type} onChange={(e) => setF({ ...f, leave_type: e.target.value })}>
            {["casual", "annual", "sick", "unpaid"].map((t) => <option key={t} value={t}>{humanize(t)}</option>)}
          </Select>
        )}</Field>
        <Field label="From">{(id) => <Input id={id} type="date" required value={f.start_date} onChange={(e) => setF({ ...f, start_date: e.target.value })} />}</Field>
        <Field label="To">{(id) => <Input id={id} type="date" value={f.end_date} onChange={(e) => setF({ ...f, end_date: e.target.value })} />}</Field>
        <div className="w-56"><Field label="Reason">{(id) => <Input id={id} value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} />}</Field></div>
        <Button type="submit" busy={apply.isPending}>Apply</Button>
      </form>
      {!!q.data.leave?.length && (
        <div className="mt-4">
          <Table caption="My leave requests" rows={q.data.leave.slice(0, 5)} rowKey={(r) => r.id}
            columns={[{ key: "leave_type", header: "Type", render: (r) => humanize(r.leave_type) }, { key: "start_date", header: "From", render: (r) => fmtDate(r.start_date) },
              { key: "end_date", header: "To", render: (r) => fmtDate(r.end_date) }, { key: "days", header: "Days" }, { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> }]} />
        </div>
      )}
    </Panel>
  );
}
