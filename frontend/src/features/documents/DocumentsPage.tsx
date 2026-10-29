import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Dialog } from "../../components/ui/overlays";
import { ExternalLink, FileText, Search } from "../../components/icons";
import { Button, EmptyState, ErrorBox, Field, Input, Notice, PageHeader, Panel, Select, SimulatedBadge, Spinner, cx } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import { fmtDateTime } from "../../lib/format";
import type { DriveFile, Mode, ToolResult } from "../../lib/types";

interface FileText_ {
  file: DriveFile;
  text: string;
  truncated: boolean;
  extracted_from: string;
}

interface Summary {
  file: DriveFile;
  summary: string;
  simulated: boolean;
  model: string;
  injection_suspected: boolean;
}

interface AgentRun {
  id: number;
  status: string;
  output: string;
  error: string;
  simulated: boolean;
}

/* Compare two files with the Documents agent (queued agent run, polled until done). */
function CompareDialog({ first, files, onClose }: { first: DriveFile; files: DriveFile[]; onClose: () => void }) {
  const [other, setOther] = useState("");
  const [run, setRun] = useState<AgentRun | null>(null);
  const m = useMutation({
    mutationFn: async () => {
      const read = (id: string) => api<ToolResult<FileText_>>(`/api/documents/files/${id}`).then((r) => r.result);
      const [a, b] = await Promise.all([read(first.id), read(other)]);
      let r = await api<AgentRun>("/api/agents/documents/runs", {
        body: { action: "compare", inputs: { doc1_content: a.text.slice(0, 200000), doc2_content: b.text.slice(0, 200000), doc1_name: a.file.name, doc2_name: b.file.name } },
      });
      for (let i = 0; i < 90 && !["done", "failed"].includes(r.status); i++) {
        await new Promise((res) => setTimeout(res, 1000));
        r = await api<AgentRun>(`/api/agents/runs/${r.id}`);
      }
      return r;
    },
    onSuccess: setRun,
  });
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()} title={`Compare ${first.name}`} wide
      footer={<><Button onClick={onClose}>Close</Button><Button variant="primary" disabled={!other} busy={m.isPending} onClick={() => m.mutate()}>Compare</Button></>}>
      <div className="flex flex-col gap-4">
        <Field label="Compare with">
          {(id) => (
            <Select id={id} value={other} onChange={(e) => setOther(e.target.value)}>
              <option value="">Choose a file...</option>
              {files.filter((f) => f.id !== first.id).map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
            </Select>
          )}
        </Field>
        {m.isPending && <Spinner label="The Documents agent is comparing the files (queued run)" />}
        {m.isError && <ErrorBox error={m.error} />}
        {run && (run.status === "done" ? (
          <div className="rounded-md border border-border bg-surface-2 p-3" data-testid="doc-compare">
            <p className="mb-2 flex items-center gap-2 text-sm font-semibold">Comparison <SimulatedBadge show={run.simulated} /></p>
            <p className="whitespace-pre-wrap text-sm">{run.output}</p>
          </div>
        ) : (
          <Notice tone="danger">{run.status === "failed" ? run.error || "The comparison failed." : "The comparison is taking too long. Check that the queue worker is running."}</Notice>
        ))}
      </div>
    </Dialog>
  );
}

export function DocumentsPage() {
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<DriveFile | null>(null);
  const [comparing, setComparing] = useState(false);
  const list = useQuery({
    queryKey: ["documents", query],
    queryFn: () =>
      query
        ? api<ToolResult<{ items: DriveFile[] } & Mode>>(`/api/documents/search?q=${encodeURIComponent(query)}`)
        : api<ToolResult<{ items: DriveFile[] } & Mode>>("/api/documents/files"),
  });
  const doc = useQuery({
    queryKey: ["documents", "file", selected?.id],
    enabled: !!selected,
    queryFn: () => api<ToolResult<FileText_ & Mode>>(`/api/documents/files/${selected!.id}`),
  });
  const summary = useMutation({ mutationFn: (id: string) => api<Summary>(`/api/documents/files/${id}/summary`, { method: "POST" }) });

  const onSearch = (e: FormEvent) => {
    e.preventDefault();
    setQuery(input.trim().length >= 2 ? input.trim() : "");
  };
  const sim = list.data?.result.simulated;

  return (
    <div>
      <PageHeader
        title="Documents"
        description="Search and read company files in Drive. File text is written by other people, so AgentsMind treats it as data and never follows instructions inside it."
        actions={<SimulatedBadge show={!!sim} />}
      />
      <form onSubmit={onSearch} className="mb-4 flex max-w-xl gap-2" role="search">
        <label htmlFor="doc-search" className="sr-only">Search files</label>
        <Input id="doc-search" value={input} onChange={(e) => setInput(e.target.value)} placeholder="Search by name or text, for example: leave policy" />
        <Button type="submit" icon={<Search aria-hidden className="size-4" />}>Search</Button>
        {query && <Button variant="ghost" onClick={() => { setInput(""); setQuery(""); }}>Clear</Button>}
      </form>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[22rem_1fr]">
        <Panel title={query ? `Results for "${query}"` : "All files"}>
          {list.isLoading && <Spinner />}
          {list.isError && <ErrorBox error={list.error} onRetry={() => void list.refetch()} />}
          {list.data && !list.data.result.items.length && <p className="text-sm text-muted">No files match.</p>}
          <ul className="-mx-2 flex flex-col">
            {list.data?.result.items.map((f) => (
              <li key={f.id}>
                <button
                  type="button"
                  onClick={() => { setSelected(f); summary.reset(); }}
                  aria-current={selected?.id === f.id ? "true" : undefined}
                  className={cx("flex w-full items-start gap-2 rounded px-2 py-2 text-left text-sm hover:bg-surface-2", selected?.id === f.id && "bg-primary-soft")}
                >
                  <FileText aria-hidden className="mt-0.5 size-4 shrink-0 text-muted" />
                  <span className="min-w-0">
                    <span className="block truncate font-medium">{f.name}</span>
                    <span className="block truncate text-xs text-muted">{f.path || f.mime_type} . {fmtDateTime(f.modified)}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </Panel>
        <div className="flex flex-col gap-4">
          {!selected && <EmptyState title="Choose a file">Select a file on the left to read it or get a summary.</EmptyState>}
          {selected && (
            <Panel
              title={<span className="flex items-center gap-2 text-sm font-semibold">{selected.name} <SimulatedBadge show={!!doc.data?.result.simulated} /></span>}
              actions={
                <span className="flex gap-2">
                  {selected.web_link && (
                    <a href={selected.web_link} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-sm text-primary hover:underline">
                      Open in Drive <ExternalLink aria-hidden className="size-3.5" />
                    </a>
                  )}
                  <Button size="sm" onClick={() => setComparing(true)}>Compare</Button>
                  <Button size="sm" variant="primary" busy={summary.isPending} onClick={() => summary.mutate(selected.id)}>Summarize</Button>
                </span>
              }
            >
              {summary.data && (
                <div className="mb-4 rounded-md border border-border bg-surface-2 p-3" data-testid="doc-summary">
                  <p className="mb-2 flex items-center gap-2 text-sm font-semibold">
                    Summary <SimulatedBadge show={summary.data.simulated} />
                    {summary.data.simulated && <span className="text-xs font-normal text-muted">Extract of the main points; no model is configured.</span>}
                  </p>
                  {summary.data.injection_suspected && (
                    <div className="mb-2"><Notice tone="warning">This file contains text addressed to an AI assistant. It was treated as data and ignored.</Notice></div>
                  )}
                  <p className="whitespace-pre-wrap text-sm">{summary.data.summary}</p>
                </div>
              )}
              {summary.isError && <ErrorBox error={summary.error} />}
              {doc.isLoading && <Spinner label="Reading the file" />}
              {doc.isError && <ErrorBox error={doc.error} />}
              {doc.data && (
                <>
                  {doc.data.result.truncated && <div className="mb-2"><Notice>The file is long; only the first part is shown.</Notice></div>}
                  <p className="mb-1 text-xs text-muted">File text (outside content)</p>
                  <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap rounded-md border border-border p-3 font-mono text-xs">{doc.data.result.text}</pre>
                </>
              )}
            </Panel>
          )}
        </div>
      </div>
      {comparing && selected && <CompareDialog first={selected} files={list.data?.result.items ?? []} onClose={() => setComparing(false)} />}
    </div>
  );
}
