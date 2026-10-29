import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { TabPanel, Tabs } from "../../components/ui/overlays";
import { Button, ErrorBox, Notice, PageHeader, Panel, Spinner, Stat, Table } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import { fmtDate } from "../../lib/format";
import type { HROverview } from "../../lib/types";
import { StatusBadge, useAsk } from "./common";
import { EmployeesTab } from "./Employees";
import { LettersTab, PayrollTab, ReportsTab } from "./Operations";
import { RecruitmentTab } from "./Recruitment";
import { HRSettingsTab, SheetsTab } from "./SheetsSettings";
import { TimeLeaveTab } from "./TimeLeave";

const TABS = [
  { value: "overview", label: "Overview" },
  { value: "employees", label: "Employees" },
  { value: "recruitment", label: "Recruitment" },
  { value: "time", label: "Attendance and leave" },
  { value: "payroll", label: "Payroll" },
  { value: "letters", label: "Letters" },
  { value: "reports", label: "Reports" },
  { value: "sheets", label: "Sheets" },
  { value: "settings", label: "HR settings" },
];

const QUICK = [
  "New joiners report for this month",
  "Induction report for this month",
  "Who resigned this month?",
  "Attendance report for this month",
  "Compliance checklist",
  "Where do I keep the leave records?",
];

function Overview({ go }: { go: (tab: string) => void }) {
  const q = useQuery({ queryKey: ["hr", "overview"], queryFn: () => api<HROverview>("/api/hr/overview") });
  const { ask, busy, view } = useAsk();
  const o = q.data;
  if (q.isLoading) return <Spinner />;
  if (q.isError) return <ErrorBox error={q.error} onRetry={() => void q.refetch()} />;
  if (!o) return null;
  const n = (k: string) => o.by_status[k] ?? 0;
  return (
    <div className="flex flex-col gap-6">
      {!!o.company_missing.length && (
        <Notice tone="warning" title="Letters need your company details">
          Add the {o.company_missing.join(", ")} in <button type="button" className="text-primary underline" onClick={() => go("settings")}>HR settings</button>.
        </Notice>
      )}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Stat label="Active employees" value={n("active")} />
        <Stat label="Onboarding" value={n("onboarding") + n("offered")} hint={`${n("offered")} offered`} />
        <Stat label="On notice" value={n("notice")} hint={`${o.open_separations} separation(s) open`} />
        <Stat label="Leave to decide" value={o.pending_leave} />
        <Stat label="Joiners this month" value={o.joiners_this_month.length} />
        <Stat label="Overdue checklist items" value={o.overdue_items} />
        <Stat label="Open jobs" value={o.jobs_open} />
        <Stat label="HR sheets connected" value={o.sheets} />
      </div>
      <Panel title="Upcoming joiners">
        <Table caption="Upcoming joiners" rows={o.upcoming_joiners} rowKey={(e) => e.id} empty="No upcoming joiners."
          columns={[{ key: "full_name", header: "Name" }, { key: "job_title", header: "Job title" }, { key: "department", header: "Department" },
            { key: "joining_date", header: "Joining", render: (e) => fmtDate(e.joining_date) }, { key: "status", header: "Status", render: (e) => <StatusBadge status={e.status} /> }]} />
      </Panel>
      <Panel title="Quick reports">
        <div className="flex flex-wrap gap-2">
          {QUICK.map((t) => <Button key={t} size="sm" busy={busy} onClick={() => ask(t)}>{t}</Button>)}
        </div>
        {view}
      </Panel>
    </div>
  );
}

export function HRPage({ employeeId }: { employeeId?: number }) {
  const [tab, setTab] = useState(employeeId ? "employees" : "overview");
  return (
    <div>
      <PageHeader title="HR" description="Recruitment, new joiners, attendance and leave, payroll, letters, compliance and separations. Anything that reaches people or other systems waits for your approval." />
      <Tabs value={tab} onValueChange={setTab} label="HR sections" tabs={TABS}>
        <TabPanel value="overview"><Overview go={setTab} /></TabPanel>
        <TabPanel value="employees"><EmployeesTab initialOpen={employeeId} /></TabPanel>
        <TabPanel value="recruitment"><RecruitmentTab /></TabPanel>
        <TabPanel value="time"><TimeLeaveTab /></TabPanel>
        <TabPanel value="payroll"><PayrollTab /></TabPanel>
        <TabPanel value="letters"><LettersTab /></TabPanel>
        <TabPanel value="reports"><ReportsTab /></TabPanel>
        <TabPanel value="sheets"><SheetsTab /></TabPanel>
        <TabPanel value="settings"><HRSettingsTab /></TabPanel>
      </Tabs>
    </div>
  );
}
