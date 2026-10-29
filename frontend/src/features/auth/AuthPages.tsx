import { useState, type FormEvent, type ReactNode } from "react";
import { Logo } from "../../components/layout/AppShell";
import { Button, Field, Input, Notice } from "../../components/ui/primitives";
import { api, ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { Link, useRouter } from "../../lib/router";

function AuthFrame({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <div className="flex min-h-full items-center justify-center bg-bg px-4 py-10">
      <main className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-6 text-center">
          <Logo width={240} />
          <div>
            <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
            {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
          </div>
        </div>
        <div className="rounded-lg border border-border bg-surface p-6 shadow-[var(--shadow)]">{children}</div>
      </main>
    </div>
  );
}

export function LoginPage() {
  const { signIn } = useAuth();
  const { navigate, search } = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!email.trim() || !password) {
      setError("Enter your email and password.");
      return;
    }
    setBusy(true);
    try {
      await signIn(email.trim(), password);
      const next = search.get("next");
      navigate(next && next.startsWith("/") && !next.startsWith("//") ? next : "/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthFrame title="Sign in" subtitle="Use the account your administrator created for you.">
      <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
        {error && <Notice tone="danger">{error}</Notice>}
        <Field label="Email" required>
          {(id, d) => (
            <Input id={id} aria-describedby={d} type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
          )}
        </Field>
        <Field label="Password" required>
          {(id, d) => (
            <Input id={id} aria-describedby={d} type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          )}
        </Field>
        <Button type="submit" variant="primary" busy={busy} className="w-full">
          Sign in
        </Button>
        <Link to="/forgot-password" className="text-sm text-primary hover:underline">
          Forgot your password?
        </Link>
      </form>
    </AuthFrame>
  );
}

export function ForgotPage() {
  const [email, setEmail] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ message: string }>("/api/auth/password/forgot", { body: { email: email.trim() } });
      setDone(r.message);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not send the reset code.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <AuthFrame title="Reset your password" subtitle="We will send a one-time reset code to your email address.">
      {done ? (
        <div className="flex flex-col gap-4">
          <Notice>{done}</Notice>
          <Link to="/reset-password" className="text-sm text-primary hover:underline">
            I have a reset code
          </Link>
        </div>
      ) : (
        <form onSubmit={submit} className="flex flex-col gap-4">
          {error && <Notice tone="danger">{error}</Notice>}
          <Field label="Email" required>
            {(id) => <Input id={id} type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />}
          </Field>
          <Button type="submit" variant="primary" busy={busy}>
            Send reset code
          </Button>
          <Link to="/login" className="text-sm text-primary hover:underline">
            Back to sign in
          </Link>
        </form>
      )}
    </AuthFrame>
  );
}

export function ResetPage() {
  const { search, navigate } = useRouter();
  const [token, setToken] = useState(search.get("token") ?? "");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (pw !== pw2) {
      setError("The two passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await api("/api/auth/password/reset", { body: { token: token.trim(), new_password: pw } });
      navigate("/login", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The reset did not work.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <AuthFrame title="Choose a new password" subtitle="At least 12 characters. Avoid your name or email.">
      <form onSubmit={submit} className="flex flex-col gap-4">
        {error && <Notice tone="danger">{error}</Notice>}
        <Field label="Reset code" required>
          {(id) => <Input id={id} value={token} onChange={(e) => setToken(e.target.value)} autoComplete="one-time-code" required />}
        </Field>
        <Field label="New password" required>
          {(id) => <Input id={id} type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} required />}
        </Field>
        <Field label="Repeat new password" required>
          {(id) => <Input id={id} type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} required />}
        </Field>
        <Button type="submit" variant="primary" busy={busy}>
          Save new password
        </Button>
      </form>
    </AuthFrame>
  );
}
