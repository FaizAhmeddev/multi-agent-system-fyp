import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { ChevronDown, Users } from "../../components/icons";
import { Dialog, Menu } from "../../components/ui/overlays";
import { Badge, Button, ErrorBox, Field, Input, Notice, PageHeader, Panel, SimulatedBadge, Spinner, Table } from "../../components/ui/primitives";
import { api, ApiError } from "../../lib/api";
import { fmtDateTime, humanize } from "../../lib/format";
import { useToast } from "../../lib/toast";
import type { Candidate, RubricRow, TurnResult } from "../../lib/types";

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
          {!!c.details?.review_reasons?.length && (
            <Notice tone="warning" title="Why a person should review this">
              <ul className="list-disc pl-5">{c.details.review_reasons.map((r) => <li key={r}>{r}</li>)}</ul>
            </Notice>
          )}
          {!!c.details?.flags?.length && <Notice tone="warning">{c.details.flags.join(" ")}</Notice>}
          {c.details?.rubric ? (
            <Table
              caption="Rubric"
              columns={[
                { key: "criterion", header: "Criterion", render: (r: RubricRow) => <span>{r.criterion} <span className="text-xs text-muted">({r.kind === "must" ? "must have" : "nice to have"})</span></span> },
                { key: "rating", header: "Rating", render: (r) => <Badge tone={r.rating === "met" ? "success" : r.rating === "partial" ? "warning" : "neutral"}>{humanize(r.rating)}</Badge> },
                { key: "evidence", header: "Evidence from the CV", render: (r) => <span className="text-muted">{r.evidence || "None"}</span> },
              ]}
              rows={c.details.rubric}
              rowKey={(r) => r.criterion}
            />
          ) : (
            <p className="text-sm text-muted">This candidate has not been screened yet.</p>
          )}
          <p className="text-xs text-muted">
            Scores rank skills and experience only. Names, contact details, age, gender, nationality, religion and similar details were removed before scoring.
            {c.details?.job_description_file && ` Job description: ${c.details.job_description_file}.`}
          </p>
        </div>
      )}
    </Dialog>
  );
}

function ScreenPanel() {
  const qc = useQueryClient();
  const toast = useToast();
  const [role, setRole] = useState("Python Developer");
  const [last, setLast] = useState<TurnResult | null>(null);
  const m = useMutation({
    mutationFn: () => api<TurnResult>("/api/assistant/messages", { body: { text: `Screen the CVs for the ${role.trim()} role` } }),
    onSuccess: (r) => {
      setLast(r);
      void qc.invalidateQueries({ queryKey: ["hr"] });
      const card = r.cards[0];
      toast(card?.kind === "result" ? "Screening finished." : card?.body ?? "Done.", card?.kind === "error" ? "error" : "success");
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : String(e), "error"),
  });
  const card = last?.cards[0];
  return (
    <Panel title="Screen CVs">
      <form className="flex flex-wrap items-end gap-3" onSubmit={(e: FormEvent) => { e.preventDefault(); if (role.trim()) m.mutate(); }}>
        <div className="w-72">
          <Field label="Role" hint="Uses the job description and CVs in Drive (HR/CVs).">
            {(id, d) => <Input id={id} aria-describedby={d} value={role} onChange={(e) => setRole(e.target.value)} />}
          </Field>
        </div>
        <Button type="submit" variant="primary" busy={m.isPending}>Screen CVs</Button>
      </form>
      {card && (
        <div className="mt-4 flex flex-col gap-2">
          <p className="flex items-center gap-2 text-sm">{card.body} <SimulatedBadge show={card.simulated} /></p>
          {card.warnings.map((w) => <Notice key={w} tone="warning">{w}</Notice>)}
        </div>
      )}
    </Panel>
  );
}

export function HRPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [open, setOpen] = useState<number | null>(null);
  const q = useQuery({ queryKey: ["hr", "candidates"], queryFn: () => api<{ items: Candidate[] }>("/api/hr/candidates") });
  const move = useMutation({
    mutationFn: ({ id, stage }: { id: number; stage: string }) => api<Candidate>(`/api/hr/candidates/${id}`, { method: "PATCH", body: { stage } }),
    onSuccess: (c) => {
      toast(`${c.name} moved to ${humanize(c.stage)}.`, "success");
      void qc.invalidateQueries({ queryKey: ["hr"] });
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : String(e), "error"),
  });
  const items = q.data?.items ?? [];
  return (
    <div>
      <PageHeader title="HR" description="Candidates board and CV screening. Screening ranks; people decide who moves forward." />
      <div className="mb-6"><ScreenPanel /></div>
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
                <h2 className="flex items-center justify-between px-1 text-sm font-semibold">
                  {humanize(stage)} <span className="text-xs font-normal text-muted">{col.length}</span>
                </h2>
                {col.map((c) => (
                  <article key={c.id} className="rounded-md border border-border bg-surface p-3 text-sm" data-testid="candidate-card">
                    <button type="button" className="text-left font-medium text-fg hover:underline" onClick={() => setOpen(c.id)}>
                      {c.name}
                    </button>
                    <p className="text-xs text-muted">{c.job_title}</p>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      {c.rubric_score !== null && <Badge>Rubric {c.rubric_score}</Badge>}
                      {c.keyword_score !== null && <Badge>Keywords {c.keyword_score}</Badge>}
                      {c.needs_human_review && <Badge tone="warning">Needs review</Badge>}
                      <SimulatedBadge show={c.simulated} />
                    </div>
                    <div className="mt-2 flex items-center justify-between">
                      <span className="text-xs text-muted">{fmtDateTime(c.updated_at)}</span>
                      <Menu
                        label={`Move ${c.name}`}
                        trigger={
                          <button type="button" className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-primary hover:bg-primary-soft" aria-label={`Move ${c.name} to another stage`}>
                            Move <ChevronDown aria-hidden className="size-3" />
                          </button>
                        }
                        items={STAGES.filter((s) => s !== c.stage).map((s) => ({ label: humanize(s), onSelect: () => move.mutate({ id: c.id, stage: s }) }))}
                      />
                    </div>
                  </article>
                ))}
              </section>
            );
          })}
        </div>
      )}
      {open !== null && <CandidateDialog id={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
