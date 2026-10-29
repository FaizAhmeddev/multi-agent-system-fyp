import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { ChevronDown, Plus, Users } from "../../components/icons";
import { Dialog, Menu } from "../../components/ui/overlays";
import { Badge, Button, ErrorBox, Field, Input, Notice, Panel, Select, SimulatedBadge, Spinner, Table, Textarea } from "../../components/ui/primitives";
import { api, ApiError } from "../../lib/api";
import { fmtDateTime, humanize } from "../../lib/format";
import { useToast } from "../../lib/toast";
import type { Candidate, HRJob, RubricRow } from "../../lib/types";
import { DEPARTMENTS, useAsk } from "./common";

const STAGES = ["new", "screened", "shortlisted", "interview", "rejected"];

function Score({ value, label }: { value: number | null; label: string }) {
  return (
    <span className="flex flex-col items-start">
      <span className="text-xs text-muted">{label}</span>
      <span className="font-semibold tabular-nums">{value ?? "-"}</span>
    </span>
  );
}

function CandidateDialog({ id, onClose }: { id: number; onClose: () => void }) {
  const q = useQuery({ queryKey: ["hr", "candidate", id], queryFn: () => api<Candidate>(`/api/hr/candidates/${id}`) });
  const { ask, busy, view } = useAsk();
  const c = q.data;
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()} title={c ? c.name : "Candidate"} description={c ? `${c.job_title}, ${humanize(c.stage)}` : undefined} wide>
      {q.isLoading && <Spinner />}
      {q.isError && <ErrorBox error={q.error} />}
      {c && (
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-4">
            <Score value={c.rubric_score} label="Rubric score" />
            <Score value={c.keyword_score} label="Keyword check" />
            {c.needs_human_review ? <Badge tone="warning">Needs human review</Badge> : c.recommendation && <Badge tone="primary">{humanize(c.recommendation)}</Badge>}
            <SimulatedBadge show={c.simulated} />
          </div>
          <p className="text-sm text-muted">
            {[c.email, c.phone, c.location, c.source ? `from ${humanize(c.source)}` : ""].filter(Boolean).join(" · ") || "No contact details found in the CV."}
          </p>
          {!!c.details?.review_reasons?.length && (
            <Notice tone="warning" title="Why a person should review this">
              <ul className="list-disc pl-5">{c.details.review_reasons.map((r) => <li key={r}>{r}</li>)}</ul>
            </Notice>
          )}
          {!!c.details?.flags?.length && <Notice tone="warning">{c.details.flags.join(" ")}</Notice>}
          {c.details?.rubric ? (
            <Table caption="Rubric" rows={c.details.rubric} rowKey={(r) => r.criterion}
              columns={[
                { key: "criterion", header: "Criterion", render: (r: RubricRow) => <span>{r.criterion} <span className="text-xs text-muted">({r.kind === "must" ? "must have" : "nice to have"})</span></span> },
                { key: "rating", header: "Rating", render: (r) => <Badge tone={r.rating === "met" ? "success" : r.rating === "partial" ? "warning" : "neutral"}>{humanize(r.rating)}</Badge> },
                { key: "evidence", header: "Evidence from the CV", render: (r) => <span className="text-muted">{r.evidence || "None"}</span> },
              ]} />
          ) : <p className="text-sm text-muted">This candidate has not been screened yet.</p>}
          <p className="text-xs text-muted">Scores rank skills and experience only. Names, contact details, age, gender, nationality, religion and similar details were removed before scoring.</p>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" busy={busy} onClick={() => ask(`Issue an offer letter to ${c.name} for ${c.job_title}`)}>Prepare offer letter</Button>
            <Button size="sm" busy={busy} onClick={() => ask(`Write interview questions for the ${c.job_title} role`)}>Interview questions</Button>
          </div>
          {view}
        </div>
      )}
    </Dialog>
  );
}

function JobDialog({ job, onClose }: { job: HRJob | null; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [f, setF] = useState<Omit<HRJob, "id">>(job ?? { title: "", department: "Engineering", location: "Karachi", employment_type: "permanent", description: "Requirements:\n- \n\nNice to have:\n- ", status: "open" });
  const m = useMutation({
    mutationFn: () => api<HRJob>(job ? `/api/hr/jobs/${job.id}` : "/api/hr/jobs", {
      method: job ? "PUT" : "POST",
      body: { title: f.title, department: f.department, location: f.location, employment_type: f.employment_type, description: f.description, status: f.status },
    }),
    onSuccess: () => { toast("Job saved.", "success"); void qc.invalidateQueries({ queryKey: ["hr"] }); onClose(); },
    onError: (e) => toast(e instanceof ApiError ? e.message : String(e), "error"),
  });
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()} title={job ? "Edit job opening" : "New job opening"} wide
      description="Screening uses the requirements: one per line under 'Requirements:' (must have) and 'Nice to have:'."
      footer={<Button variant="primary" busy={m.isPending} disabled={!f.title.trim()} onClick={() => m.mutate()}>Save</Button>}>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Job title">{(id) => <Input id={id} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />}</Field>
        <Field label="Department">{(id) => <Select id={id} value={f.department} onChange={(e) => setF({ ...f, department: e.target.value })}>{DEPARTMENTS.map((d) => <option key={d}>{d}</option>)}</Select>}</Field>
        <Field label="Location">{(id) => <Input id={id} value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} />}</Field>
        <Field label="Status">{(id) => <Select id={id} value={f.status} onChange={(e) => setF({ ...f, status: e.target.value as HRJob["status"] })}><option value="open">Open</option><option value="closed">Closed</option></Select>}</Field>
        <div className="sm:col-span-2">
          <Field label="Description and requirements">{(id) => <Textarea id={id} rows={10} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} />}</Field>
        </div>
      </div>
    </Dialog>
  );
}

function ScreenPanel() {
  const [role, setRole] = useState("");
  const [src, setSrc] = useState("Gmail, the CV folders and Drive");
  const { ask, busy, view } = useAsk();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const s = src.startsWith("Gmail,") ? "" : ` from ${src}`;
    ask(`Screen CVs${s} for the ${role.trim()} role`);
  };
  return (
    <Panel title="Gather and screen CVs">
      <form className="flex flex-wrap items-end gap-3" onSubmit={submit}>
        <div className="w-72">
          <Field label="Role" hint="The job opening's requirements are used (or a job description file in Drive).">
            {(id, d) => <Input id={id} aria-describedby={d} value={role} required onChange={(e) => setRole(e.target.value)} placeholder="Python Developer" />}
          </Field>
        </div>
        <Field label="Look in">
          {(id) => (
            <Select id={id} value={src} onChange={(e) => setSrc(e.target.value)}>
              {["Gmail, the CV folders and Drive", "Gmail", "the CV folder", "Drive"].map((x) => <option key={x}>{x}</option>)}
            </Select>
          )}
        </Field>
        <Button type="submit" variant="primary" busy={busy}>Screen CVs</Button>
      </form>
      <p className="mt-2 text-xs text-muted">Only candidates in the city set in HR settings (Karachi) are screened; the others are listed separately.</p>
      {view}
    </Panel>
  );
}

export function RecruitmentTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const [open, setOpen] = useState<number | null>(null);
  const [job, setJob] = useState<HRJob | null | "new">(null);
  const q = useQuery({ queryKey: ["hr", "candidates"], queryFn: () => api<{ items: Candidate[] }>("/api/hr/candidates") });
  const jobs = useQuery({ queryKey: ["hr", "jobs"], queryFn: () => api<{ items: HRJob[] }>("/api/hr/jobs") });
  const move = useMutation({
    mutationFn: ({ id, stage }: { id: number; stage: string }) => api<Candidate>(`/api/hr/candidates/${id}`, { method: "PATCH", body: { stage } }),
    onSuccess: (c) => { toast(`${c.name} moved to ${humanize(c.stage)}.`, "success"); void qc.invalidateQueries({ queryKey: ["hr"] }); },
    onError: (e) => toast(e instanceof ApiError ? e.message : String(e), "error"),
  });
  const items = q.data?.items ?? [];
  return (
    <div className="flex flex-col gap-6">
      <ScreenPanel />
      <Panel title="Job openings" actions={<Button size="sm" icon={<Plus aria-hidden className="size-4" />} onClick={() => setJob("new")}>New job</Button>}>
        {jobs.isError && <ErrorBox error={jobs.error} />}
        {jobs.data && (
          <Table caption="Job openings" rows={jobs.data.items} rowKey={(j) => j.id} onRowClick={(j) => setJob(j)} empty="No job openings yet."
            columns={[{ key: "title", header: "Title" }, { key: "department", header: "Department" }, { key: "location", header: "Location" },
              { key: "status", header: "Status", render: (j) => <Badge tone={j.status === "open" ? "success" : "neutral"}>{humanize(j.status)}</Badge> }]} />
        )}
      </Panel>
      {q.isLoading && <Spinner />}
      {q.isError && <ErrorBox error={q.error} onRetry={() => void q.refetch()} />}
      {q.data && !items.length && (
        <Panel><p className="flex items-center gap-2 text-sm text-muted"><Users aria-hidden className="size-4" /> No candidates yet. Screen CVs to fill the board.</p></Panel>
      )}
      {!!items.length && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3 xl:grid-cols-5" data-testid="candidates-board">
          {STAGES.map((stage) => {
            const col = items.filter((c) => c.stage === stage);
            return (
              <section key={stage} aria-label={humanize(stage)} className="flex flex-col gap-2 rounded-lg border border-border bg-surface-2 p-2">
                <h2 className="flex items-center justify-between px-1 text-sm font-semibold">{humanize(stage)} <span className="text-xs font-normal text-muted">{col.length}</span></h2>
                {col.map((c) => (
                  <article key={c.id} className="rounded-md border border-border bg-surface p-3 text-sm" data-testid="candidate-card">
                    <button type="button" className="text-left font-medium text-fg hover:underline" onClick={() => setOpen(c.id)}>{c.name}</button>
                    <p className="text-xs text-muted">{c.job_title}{c.location ? `, ${c.location}` : ""}</p>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      {c.rubric_score !== null && <Badge>Rubric {c.rubric_score}</Badge>}
                      {c.keyword_score !== null && <Badge>Keywords {c.keyword_score}</Badge>}
                      {c.needs_human_review && <Badge tone="warning">Needs review</Badge>}
                      <SimulatedBadge show={c.simulated} />
                    </div>
                    <div className="mt-2 flex items-center justify-between">
                      <span className="text-xs text-muted">{fmtDateTime(c.updated_at)}</span>
                      <Menu label={`Move ${c.name}`}
                        trigger={<button type="button" className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-primary hover:bg-primary-soft" aria-label={`Move ${c.name} to another stage`}>Move <ChevronDown aria-hidden className="size-3" /></button>}
                        items={STAGES.filter((s) => s !== c.stage).map((s) => ({ label: humanize(s), onSelect: () => move.mutate({ id: c.id, stage: s }) }))} />
                    </div>
                  </article>
                ))}
              </section>
            );
          })}
        </div>
      )}
      {open !== null && <CandidateDialog id={open} onClose={() => setOpen(null)} />}
      {job !== null && <JobDialog job={job === "new" ? null : job} onClose={() => setJob(null)} />}
    </div>
  );
}
