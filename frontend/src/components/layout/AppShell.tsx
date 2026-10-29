import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { Link, useRouter } from "../../lib/router";
import { useTheme, type ThemeChoice } from "../../lib/theme";
import type { Department, Page, Approval } from "../../lib/types";
import {
  Bot, Briefcase, Calendar, ClipboardCheck, FileText, House, LogOut, Menu as MenuIcon, Monitor, Moon, Settings, Shield, Sun, Ticket, Wallet,
} from "../icons";
import { Dialog, Menu } from "../ui/overlays";
import { cx } from "../ui/primitives";

export function Brand({ compact }: { compact?: boolean }) {
  // assets/brand/logo.png is copied in at build time when provided; the built-in mark is the fallback.
  const [src, setSrc] = useState("/brand/logo.png");
  return (
    <span className="flex items-center gap-2">
      <img src={src} alt="" width={28} height={28} className="size-7 object-contain" onError={() => setSrc("/brand/mark.svg")} />
      {!compact && <span className="text-base font-semibold tracking-tight">AgentsMind</span>}
    </span>
  );
}

interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
  dept?: string;
  admin?: boolean;
  badge?: number;
}

function useNav(): NavItem[] {
  const { has } = useAuth();
  const deps = useQuery({ queryKey: ["departments"], queryFn: () => api<{ items: Department[] }>("/api/departments") });
  const pending = useQuery({
    queryKey: ["approvals", "pending", "count"],
    queryFn: () => api<Page<Approval>>("/api/approvals?status=pending&page_size=1"),
    refetchInterval: 30_000,
  });
  const ok = (slug: string) => deps.data?.items.find((d) => d.slug === slug)?.accessible ?? false;
  const items: NavItem[] = [
    { to: "/", label: "Hub", icon: <House aria-hidden className="size-4" /> },
    { to: "/assistant", label: "Assistant", icon: <Bot aria-hidden className="size-4" /> },
    { to: "/approvals", label: "Approvals", icon: <ClipboardCheck aria-hidden className="size-4" />, badge: pending.data?.total },
    { to: "/hr", label: "HR", icon: <Briefcase aria-hidden className="size-4" />, dept: "hr" },
    { to: "/it", label: "IT", icon: <Ticket aria-hidden className="size-4" />, dept: "it_any" },
    { to: "/finance", label: "Finance", icon: <Wallet aria-hidden className="size-4" />, dept: "finance" },
    { to: "/documents", label: "Documents", icon: <FileText aria-hidden className="size-4" />, dept: "documents" },
    { to: "/communications", label: "Communications", icon: <Calendar aria-hidden className="size-4" />, dept: "communications" },
    { to: "/admin", label: "Admin", icon: <Shield aria-hidden className="size-4" />, admin: true },
    { to: "/settings", label: "Settings", icon: <Settings aria-hidden className="size-4" /> },
  ];
  // Everyone can raise and follow their own IT tickets; the IT department view is for IT staff.
  return items.filter((i) => (i.admin ? has("admin") : !i.dept || i.dept === "it_any" || ok(i.dept)));
}

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const { path } = useRouter();
  const items = useNav();
  return (
    <nav aria-label="Main" className="flex flex-col gap-0.5">
      {items.map((i) => {
        const active = i.to === "/" ? path === "/" : path === i.to || path.startsWith(i.to + "/");
        return (
          <Link
            key={i.to}
            to={i.to}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={cx(
              "flex items-center gap-3 rounded-md px-3 py-2 text-sm",
              active ? "bg-primary-soft font-medium text-primary" : "text-fg hover:bg-surface-2",
            )}
          >
            {i.icon}
            <span className="flex-1">{i.label}</span>
            {!!i.badge && (
              <span className="rounded bg-primary px-1.5 text-xs font-semibold text-primary-fg" aria-label={`${i.badge} pending`}>
                {i.badge}
              </span>
            )}
          </Link>
        );
      })}
    </nav>
  );
}

function ThemeMenu() {
  const { choice, setChoice, theme } = useTheme();
  const opt = (c: ThemeChoice, label: string, icon: ReactNode) => ({
    label: `${label}${choice === c ? " (current)" : ""}`,
    icon,
    onSelect: () => setChoice(c),
  });
  return (
    <Menu
      label="Theme"
      trigger={
        <button type="button" aria-label={`Theme: ${choice}`} data-testid="theme-menu" className="inline-flex size-9 items-center justify-center rounded-md text-muted hover:bg-surface-2 hover:text-fg">
          {theme === "dark" ? <Moon aria-hidden className="size-4" /> : <Sun aria-hidden className="size-4" />}
        </button>
      }
      items={[
        opt("light", "Light", <Sun aria-hidden className="size-4" />),
        opt("dark", "Dark", <Moon aria-hidden className="size-4" />),
        opt("system", "Match system", <Monitor aria-hidden className="size-4" />),
      ]}
    />
  );
}

function UserMenu() {
  const { user, signOut } = useAuth();
  const { navigate } = useRouter();
  if (!user) return null;
  return (
    <Menu
      label="Account"
      trigger={
        <button type="button" data-testid="user-menu" className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-surface-2">
          <span aria-hidden className="flex size-7 items-center justify-center rounded-full bg-primary-soft text-xs font-semibold text-primary">
            {user.full_name.split(/\s+/).slice(0, 2).map((p) => p[0]).join("").toUpperCase()}
          </span>
          <span className="hidden text-left sm:block">
            <span className="block font-medium leading-tight">{user.full_name}</span>
            <span className="block text-xs leading-tight text-muted">{user.roles.join(", ")}</span>
          </span>
        </button>
      }
      items={[
        { label: "Settings", icon: <Settings aria-hidden className="size-4" />, onSelect: () => navigate("/settings") },
        "separator",
        { label: "Sign out", icon: <LogOut aria-hidden className="size-4" />, onSelect: () => void signOut().then(() => navigate("/login")) },
      ]}
    />
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="flex min-h-full">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">
        Skip to content
      </a>
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col gap-6 border-r border-border bg-surface px-3 py-4 lg:flex">
        <Link to="/" className="px-2" aria-label="AgentsMind home">
          <Brand />
        </Link>
        <NavLinks />
        <p className="mt-auto px-2 text-xs text-muted">One workspace. Every department. Handled.</p>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-3 border-b border-border bg-surface px-4">
          <div className="flex items-center gap-2 lg:hidden">
            <button type="button" aria-label="Open menu" onClick={() => setOpen(true)} className="inline-flex size-9 items-center justify-center rounded-md hover:bg-surface-2">
              <MenuIcon aria-hidden className="size-5" />
            </button>
            <Brand />
          </div>
          <div className="hidden lg:block" />
          <div className="flex items-center gap-1">
            <ThemeMenu />
            <UserMenu />
          </div>
        </header>
        <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6">
          {children}
        </main>
      </div>
      <Dialog open={open} onOpenChange={setOpen} title="Menu">
        <NavLinks onNavigate={() => setOpen(false)} />
      </Dialog>
    </div>
  );
}
