import { forwardRef, useId, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { Info, LoaderCircle, TriangleAlert } from "../icons";

export function cx(...xs: (string | false | null | undefined)[]): string {
  return xs.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "ghost" | "danger";
const VARIANT: Record<Variant, string> = {
  primary: "bg-primary text-primary-fg hover:bg-primary-hover border-transparent",
  secondary: "bg-surface text-fg border-border-strong hover:bg-surface-2",
  ghost: "bg-transparent text-fg border-transparent hover:bg-surface-2",
  danger: "bg-danger text-white border-transparent hover:opacity-90 [[data-theme=dark]_&]:text-[#1a0a08]",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "sm" | "md";
  busy?: boolean;
  icon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", busy, icon, className, children, disabled, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-md border font-medium transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-60",
        size === "sm" ? "h-8 px-3 text-sm" : "h-10 px-4 text-sm",
        VARIANT[variant],
        className,
      )}
      {...rest}
    >
      {busy ? <LoaderCircle aria-hidden className="size-4 animate-spin" /> : icon}
      {children}
    </button>
  );
});

export function IconButton({ label, children, className, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={cx("inline-flex size-9 items-center justify-center rounded-md text-muted hover:bg-surface-2 hover:text-fg", className)}
      {...rest}
    >
      {children}
    </button>
  );
}

interface FieldProps {
  label: string;
  hint?: string;
  error?: string;
  required?: boolean;
  children: (id: string, describedBy: string | undefined, invalid: boolean) => ReactNode;
}

export function Field({ label, hint, error, required, children }: FieldProps) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errId = error ? `${id}-err` : undefined;
  const describedBy = [hintId, errId].filter(Boolean).join(" ") || undefined;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium text-fg">
        {label}
        {required && <span className="text-danger"> *</span>}
      </label>
      {children(id, describedBy, !!error)}
      {hint && !error && (
        <p id={hintId} className="text-xs text-muted">
          {hint}
        </p>
      )}
      {error && (
        <p id={errId} className="text-xs text-danger" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

const control =
  "w-full rounded-md border border-border-strong bg-surface px-3 text-sm text-fg placeholder:text-muted aria-[invalid=true]:border-danger";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...rest }, ref) {
  return <input ref={ref} className={cx(control, "h-10", className)} {...rest} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea(
  { className, ...rest },
  ref,
) {
  return <textarea ref={ref} className={cx(control, "min-h-24 py-2", className)} {...rest} />;
});

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select(
  { className, children, ...rest },
  ref,
) {
  return (
    <select ref={ref} className={cx(control, "h-10", className)} {...rest}>
      {children}
    </select>
  );
});

export function Panel({ title, actions, children, className }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cx("rounded-lg border border-border bg-surface shadow-[var(--shadow)]", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
          {typeof title === "string" ? <h2 className="text-sm font-semibold">{title}</h2> : title}
          {actions}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

type Tone = "neutral" | "primary" | "success" | "warning" | "danger";
const TONE: Record<Tone, string> = {
  neutral: "bg-surface-2 text-fg border-border",
  primary: "bg-primary-soft text-primary border-transparent",
  success: "bg-success-soft text-success border-transparent",
  warning: "bg-warning-soft text-warning border-transparent",
  danger: "bg-danger-soft text-danger border-transparent",
};

export function Badge({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={cx("inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs font-medium", TONE[tone], className)}>
      {children}
    </span>
  );
}

/* Shown on anything produced by a sandbox backend or the sandbox model. */
export function SimulatedBadge({ show = true }: { show?: boolean }) {
  if (!show) return null;
  return (
    <span
      data-testid="simulated"
      title="Produced by a sandbox: no real email, calendar, file or model was used."
      className="inline-flex items-center rounded border border-warning px-1.5 py-0.5 text-xs font-medium text-warning"
    >
      Simulated
    </span>
  );
}

export function Notice({ tone = "info", title, children }: { tone?: "info" | "warning" | "danger"; title?: string; children: ReactNode }) {
  const styles = {
    info: "border-border bg-surface-2",
    warning: "border-warning bg-warning-soft",
    danger: "border-danger bg-danger-soft",
  }[tone];
  const Icon = tone === "info" ? Info : TriangleAlert;
  return (
    <div className={cx("flex gap-3 rounded-md border px-3 py-2.5 text-sm", styles)} role={tone === "danger" ? "alert" : undefined}>
      <Icon aria-hidden className={cx("mt-0.5 size-4 shrink-0", tone === "danger" ? "text-danger" : tone === "warning" ? "text-warning" : "text-muted")} />
      <div className="min-w-0">
        {title && <p className="font-medium">{title}</p>}
        <div className="text-fg">{children}</div>
      </div>
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-6 text-sm text-muted" role="status">
      <LoaderCircle aria-hidden className="size-4 animate-spin" />
      {label}
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-2 rounded-md border border-dashed border-border px-4 py-8">
      <p className="font-medium">{title}</p>
      {children && <div className="text-sm text-muted">{children}</div>}
      {action}
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const msg = error instanceof Error ? error.message : String(error);
  const status = (error as { status?: number })?.status;
  return (
    <Notice tone="danger" title={status === 403 ? "You do not have access to this" : "Something went wrong"}>
      <p>{msg}</p>
      {onRetry && (
        <Button size="sm" className="mt-2" onClick={onRetry}>
          Try again
        </Button>
      )}
    </Notice>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-sm text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  );
}

export interface Column<T> {
  key: string;
  header: string;
  render?: (row: T) => ReactNode;
  className?: string;
}

export function Table<T>({
  columns, rows, rowKey, onRowClick, caption, empty = "Nothing to show.",
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  onRowClick?: (row: T) => void;
  caption?: string;
  empty?: string;
}) {
  if (!rows.length) return <p className="py-6 text-sm text-muted">{empty}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted">
            {columns.map((c) => (
              <th key={c.key} scope="col" className={cx("px-3 py-2 font-medium", c.className)}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={rowKey(r)}
              className={cx("border-b border-border last:border-0", onRowClick && "cursor-pointer hover:bg-surface-2")}
              onClick={onRowClick ? () => onRowClick(r) : undefined}
              onKeyDown={onRowClick ? (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onRowClick(r)) : undefined}
              tabIndex={onRowClick ? 0 : undefined}
            >
              {columns.map((c) => (
                <td key={c.key} className={cx("px-3 py-2.5 align-top", c.className)}>
                  {c.render ? c.render(r) : String((r as Record<string, unknown>)[c.key] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
