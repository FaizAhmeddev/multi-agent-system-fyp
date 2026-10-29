import { useState, type FormEvent, type ReactNode } from "react";
import { Monitor, Moon, Sun } from "../../components/icons";
import { Badge, Button, Field, Input, Notice, PageHeader, Panel, cx } from "../../components/ui/primitives";
import { api, ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { fmtDateTime } from "../../lib/format";
import { useRouter } from "../../lib/router";
import { useTheme, type ThemeChoice } from "../../lib/theme";
import { ConnectionsPanel } from "./Connections";

export function SettingsPage() {
  const { user, signOut } = useAuth();
  const { navigate } = useRouter();
  const { choice, setChoice } = useTheme();
  const [cur, setCur] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [msg, setMsg] = useState<{ tone: "info" | "danger"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const change = async (e: FormEvent) => {
    e.preventDefault();
    setMsg(null);
    if (pw !== pw2) {
      setMsg({ tone: "danger", text: "The two new passwords do not match." });
      return;
    }
    setBusy(true);
    try {
      await api("/api/auth/password/change", { body: { current_password: cur, new_password: pw } });
      setMsg({ tone: "info", text: "Password changed. Sign in again with the new password." });
      await signOut();
      navigate("/login");
    } catch (err) {
      setMsg({ tone: "danger", text: err instanceof ApiError ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  };

  const themes: { v: ThemeChoice; label: string; icon: ReactNode }[] = [
    { v: "light", label: "Light", icon: <Sun aria-hidden className="size-4" /> },
    { v: "dark", label: "Dark", icon: <Moon aria-hidden className="size-4" /> },
    { v: "system", label: "Match system", icon: <Monitor aria-hidden className="size-4" /> },
  ];

  return (
    <div className="max-w-3xl">
      <PageHeader title="Settings" />
      <div className="flex flex-col gap-6">
        <Panel title="Your account">
          {user && (
            <dl className="grid grid-cols-[9rem_1fr] gap-y-1.5 text-sm">
              <dt className="text-muted">Name</dt><dd>{user.full_name}</dd>
              <dt className="text-muted">Email</dt><dd>{user.email}</dd>
              <dt className="text-muted">Roles</dt><dd className="flex flex-wrap gap-1">{user.roles.map((r) => <Badge key={r}>{r}</Badge>)}</dd>
              <dt className="text-muted">Time zone</dt><dd>{user.timezone}</dd>
              <dt className="text-muted">Last sign-in</dt><dd>{user.last_login_at ? fmtDateTime(user.last_login_at) : "This is your first"}</dd>
            </dl>
          )}
        </Panel>
        <ConnectionsPanel />
        <Panel title="Appearance">
          <div role="radiogroup" aria-label="Theme" className="flex flex-wrap gap-2">
            {themes.map((t) => (
              <button
                key={t.v}
                type="button"
                role="radio"
                aria-checked={choice === t.v}
                onClick={() => setChoice(t.v)}
                className={cx("flex items-center gap-2 rounded-md border px-3 py-2 text-sm", choice === t.v ? "border-primary bg-primary-soft text-primary" : "border-border hover:bg-surface-2")}
              >
                {t.icon} {t.label}
              </button>
            ))}
          </div>
        </Panel>
        <Panel title="Change password">
          <form onSubmit={change} className="flex max-w-sm flex-col gap-4">
            {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
            <Field label="Current password" required>{(id) => <Input id={id} type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} required />}</Field>
            <Field label="New password" required hint="At least 12 characters.">
              {(id, d) => <Input id={id} aria-describedby={d} type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} required />}
            </Field>
            <Field label="Repeat new password" required>{(id) => <Input id={id} type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} required />}</Field>
            <div><Button type="submit" variant="primary" busy={busy}>Change password</Button></div>
          </form>
        </Panel>
      </div>
    </div>
  );
}
