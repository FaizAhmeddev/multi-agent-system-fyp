import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Badge, Button, ErrorBox, Notice, Panel, Spinner } from "../../components/ui/primitives";
import { api, ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useToast } from "../../lib/toast";
import type { Connections } from "../../lib/types";

function Row({ name, ok, children }: { name: string; ok: boolean; children: ReactNode }) {
  return (
    <div className="contents">
      <dt className="flex items-center gap-2 font-medium">{name}</dt>
      <dd className="flex flex-wrap items-center gap-2">
        <Badge tone={ok ? "success" : "warning"}>{ok ? "Connected" : "Not connected"}</Badge>
        <span className="text-muted">{children}</span>
      </dd>
    </div>
  );
}

/* Which outside services AgentsMind can use right now, and the one-click Google sign-in. */
export function ConnectionsPanel() {
  const { has } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["connections"], queryFn: () => api<Connections>("/api/connections"), refetchInterval: (qq) => (qq.state.data?.google_signin.running ? 3000 : false) });
  const google = useMutation({
    mutationFn: () => api<{ message?: string }>("/api/connections/google", { body: {} }),
    onSuccess: (r) => { toast(r.message ?? "Google sign-in started.", "success"); void qc.invalidateQueries({ queryKey: ["connections"] }); },
    onError: (e) => toast(e instanceof ApiError ? e.message : String(e), "error"),
  });
  const c = q.data;
  const w = c?.workspace ?? {};
  const g = w.google ?? {};
  return (
    <Panel title="Connections">
      {q.isLoading && <Spinner />}
      {q.isError && <ErrorBox error={q.error} />}
      {c && (
        <div className="flex flex-col gap-3">
          {w.error && <Notice tone="warning">workspace-mcp: {w.error}</Notice>}
          <dl className="grid grid-cols-1 gap-x-4 gap-y-2 text-sm sm:grid-cols-[10rem_1fr]">
            <Row name="OpenAI" ok={c.openai}>{c.openai ? `Model ${c.model}` : "Set OPENAI_API_KEY in .env; until then answers are labeled Simulated."}</Row>
            <Row name="Gmail" ok={w.mail === "imap" || w.mail === "google"}>
              {w.mail === "imap" ? `${w.mail_account} (app password)` : w.mail === "google" ? "Gmail API" : "Set GMAIL_EMAIL and GMAIL_APP_PASSWORD in .env."}
            </Row>
            <Row name="Google Drive" ok={w.drive === "google"}>{w.drive === "google" ? "Signed in" : "Sign in to Google below."}</Row>
            <Row name="Calendar and Sheets" ok={Boolean(g.signed_in && g.scopes?.calendar && g.scopes?.sheets)}>
              {g.signed_in ? (g.missing?.length ? `Sign in again to add: ${g.missing.join(", ")}` : "Signed in") : "Until you sign in, events stay on this computer."}
            </Row>
            <Row name="WhatsApp" ok={Boolean(w.whatsapp)}>{w.whatsapp ? "Twilio" : "Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_FROM in .env."}</Row>
            <Row name="Excel folders" ok={Boolean(w.excel_folders?.length)}>{(w.excel_folders ?? []).join("; ") || "-"}</Row>
            <Row name="CV folders" ok={Boolean(w.cv_folders?.length)}>{(w.cv_folders ?? []).join("; ") || "-"}</Row>
          </dl>
          {w.demo_mode && <Notice tone="info">Sample data is on (DEMO_MODE=true): the sample inbox, Drive and calendar are used where nothing is connected.</Notice>}
          {(has("admin") || has("hr")) && (
            <div className="flex flex-col gap-2">
              <div>
                <Button variant="primary" busy={google.isPending || c.google_signin.running} disabled={!g.client_file} onClick={() => google.mutate()}>
                  {g.signed_in ? "Sign in to Google again" : "Sign in to Google"}
                </Button>
              </div>
              {!g.client_file && <p className="text-xs text-muted">Needs a Google OAuth client file (GOOGLE_OAUTH_CLIENT_FILE in .env).</p>}
              {c.google_signin.running && <p className="text-xs text-muted" role="status">A Google page is open in the browser on the AgentsMind computer. Finish the sign-in there.</p>}
              {c.google_signin.error && <Notice tone="danger">{c.google_signin.error}</Notice>}
              {c.google_signin.done && <Notice tone="info">Google is connected. Calendar, Drive and Sheets switch over automatically.</Notice>}
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}
