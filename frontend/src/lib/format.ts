export const TZ_FALLBACK = "Asia/Karachi";

export function fmtDateTime(iso: string | null | undefined, tz?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat("en-GB", {
    weekday: "short", day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
    timeZone: tz || TZ_FALLBACK,
  }).format(d);
}

export function fmtDate(iso: string | null | undefined, tz?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: tz || TZ_FALLBACK }).format(d);
}

export function fmtTime(iso: string, tz?: string): string {
  const d = new Date(iso);
  return new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: tz || TZ_FALLBACK }).format(d);
}

/* Money arrives as an exact decimal string from the Finance Portal; only formatting happens here. */
export function fmtMoney(amount: string, currency = "PKR"): string {
  const [whole, frac = "00"] = amount.split(".");
  return `${currency} ${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}.${frac.padEnd(2, "0").slice(0, 2)}`;
}

export function humanize(s: string): string {
  const t = s.replace(/_/g, " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
}

export function initials(name: string): string {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase()).join("");
}

/* "Usman Tariq <usman@example.com>" -> "usman@example.com" */
export function emailOf(sender: string): string {
  const m = sender.match(/<([^>]+)>/);
  return (m ? m[1] : sender).trim().toLowerCase();
}

/* Local date + time inputs in the company time zone -> ISO string with offset. */
export function zonedIso(date: string, time: string, tz = TZ_FALLBACK): string {
  const [y, mo, d] = date.split("-").map(Number);
  const [h, mi] = time.split(":").map(Number);
  const guess = Date.UTC(y, mo - 1, d, h, mi);
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: tz, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).formatToParts(new Date(guess));
  const get = (t: string) => Number(parts.find((p) => p.type === t)?.value);
  const asTz = Date.UTC(get("year"), get("month") - 1, get("day"), get("hour"), get("minute"));
  const offsetMin = Math.round((asTz - guess) / 60000);
  const sign = offsetMin >= 0 ? "+" : "-";
  const abs = Math.abs(offsetMin);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date}T${pad(h)}:${pad(mi)}:00${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
}
