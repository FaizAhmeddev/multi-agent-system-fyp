/*
  API client. The access token lives in memory only. The refresh token is kept in
  sessionStorage (this tab only, cleared when the tab closes) so a reload keeps you
  signed in. A 401 triggers one refresh attempt; if that fails the user signs in again.
*/

export interface User {
  id: number;
  email: string;
  full_name: string;
  roles: string[];
  is_active: boolean;
  timezone: string;
  last_login_at: string | null;
  locked: boolean;
}

interface TokenOut {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  user: User;
}

export interface FieldError {
  field: string;
  message: string;
}

export class ApiError extends Error {
  status: number;
  code: string;
  fields: FieldError[];
  constructor(status: number, code: string, message: string, fields: FieldError[] = []) {
    super(message);
    this.status = status;
    this.code = code;
    this.fields = fields;
  }
}

const REFRESH_KEY = "agentsmind.refresh";
let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;
let onSignedOut: (() => void) | null = null;

function readRefresh(): string | null {
  try {
    return sessionStorage.getItem(REFRESH_KEY);
  } catch {
    return null;
  }
}

function writeRefresh(v: string | null): void {
  try {
    if (v) sessionStorage.setItem(REFRESH_KEY, v);
    else sessionStorage.removeItem(REFRESH_KEY);
  } catch {
    /* storage unavailable: stay signed in for this page only */
  }
}

export function setSignedOutHandler(fn: () => void): void {
  onSignedOut = fn;
}

export function hasSession(): boolean {
  return accessToken !== null || readRefresh() !== null;
}

function store(t: TokenOut): User {
  accessToken = t.access_token;
  writeRefresh(t.refresh_token);
  return t.user;
}

export function clearSession(): void {
  accessToken = null;
  writeRefresh(null);
}

async function parseError(r: Response): Promise<ApiError> {
  let code = "http_" + r.status;
  let message = `The server answered ${r.status}.`;
  let fields: FieldError[] = [];
  try {
    const body = await r.json();
    const d = body?.detail;
    if (d && typeof d === "object" && !Array.isArray(d)) {
      code = d.code ?? code;
      message = d.message ?? message;
      fields = Array.isArray(d.fields) ? d.fields : [];
    } else if (typeof d === "string") {
      message = d;
    }
  } catch {
    /* not JSON */
  }
  if (r.status === 502 || r.status === 503 || r.status === 504) {
    message = message || "A service is not reachable right now.";
  }
  return new ApiError(r.status, code, message, fields);
}

export async function refreshSession(): Promise<boolean> {
  const rt = readRefresh();
  if (!rt) return false;
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const r = await fetch("/api/auth/refresh", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: rt }),
        });
        if (!r.ok) {
          clearSession();
          return false;
        }
        store((await r.json()) as TokenOut);
        return true;
      } catch {
        return false;
      } finally {
        refreshing = null;
      }
    })();
  }
  return refreshing;
}

export interface RequestOptions {
  method?: string;
  body?: unknown;
  idempotencyKey?: string;
  signal?: AbortSignal;
}

export async function rawFetch(path: string, opts: RequestOptions = {}, retry = true): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (accessToken) headers["Authorization"] = `Bearer ${accessToken}`;
  if (opts.idempotencyKey) headers["Idempotency-Key"] = opts.idempotencyKey;
  let r: Response;
  try {
    r = await fetch(path, {
      method: opts.method ?? (opts.body !== undefined ? "POST" : "GET"),
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: opts.signal,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "network", "AgentsMind is not reachable. Check that the core API is running.");
  }
  if (r.status === 401 && retry && !path.startsWith("/api/auth/")) {
    if (await refreshSession()) return rawFetch(path, opts, false);
    clearSession();
    onSignedOut?.();
  }
  return r;
}

export async function api<T = unknown>(path: string, opts: RequestOptions = {}): Promise<T> {
  const r = await rawFetch(path, opts);
  if (!r.ok) throw await parseError(r);
  if (r.status === 204) return undefined as T;
  return (await r.json()) as T;
}

export async function login(email: string, password: string): Promise<User> {
  const r = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  }).catch(() => {
    throw new ApiError(0, "network", "AgentsMind is not reachable. Check that the core API is running.");
  });
  if (!r.ok) throw await parseError(r);
  return store((await r.json()) as TokenOut);
}

export async function logout(): Promise<void> {
  const rt = readRefresh();
  clearSession();
  if (rt) {
    await fetch("/api/auth/logout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: rt }),
    }).catch(() => undefined);
  }
}

export function newKey(prefix = "ui"): string {
  const rnd = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
  return `${prefix}-${rnd}`.slice(0, 64);
}

/* Server-Sent Events over POST (EventSource cannot send headers or a body). */
export async function streamEvents(
  path: string,
  body: unknown,
  onEvent: (event: string, data: unknown) => void,
  signal?: AbortSignal,
): Promise<void> {
  const r = await rawFetch(path, { body, signal });
  if (!r.ok || !r.body) throw await parseError(r);
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      let ev = "message";
      const data: string[] = [];
      for (const line of chunk.split("\n")) {
        if (line.startsWith("event:")) ev = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
      }
      if (data.length) {
        try {
          onEvent(ev, JSON.parse(data.join("\n")));
        } catch {
          onEvent(ev, data.join("\n"));
        }
      }
    }
  }
}
