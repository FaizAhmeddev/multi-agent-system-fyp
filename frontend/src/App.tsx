import { useEffect, type ReactNode } from "react";
import { AppShell } from "./components/layout/AppShell";
import { Spinner } from "./components/ui/primitives";
import { AdminPage } from "./features/admin/AdminPage";
import { ApprovalsPage } from "./features/approvals/ApprovalsPage";
import { AssistantPage } from "./features/assistant/AssistantPage";
import { ForgotPage, LoginPage, ResetPage } from "./features/auth/AuthPages";
import { CommunicationsPage } from "./features/communications/CommunicationsPage";
import { DocumentsPage } from "./features/documents/DocumentsPage";
import { Forbidden, NotFound } from "./features/errors/ErrorPages";
import { FinancePage } from "./features/finance/FinancePage";
import { HRPage } from "./features/hr/HRPage";
import { HubPage } from "./features/hub/HubPage";
import { ITPage } from "./features/it/ITPage";
import { SettingsPage } from "./features/settings/SettingsPage";
import { useAuth } from "./lib/auth";
import { match, useRouter } from "./lib/router";

interface Route {
  path: string;
  page: (p: Record<string, string>) => ReactNode;
  roles?: string[]; // admin always passes
  title: string;
}

const ROUTES: Route[] = [
  { path: "/", page: () => <HubPage />, title: "Hub" },
  { path: "/assistant", page: () => <AssistantPage />, title: "Assistant" },
  { path: "/assistant/:id", page: (p) => <AssistantPage conversationId={Number(p.id)} />, title: "Assistant" },
  { path: "/approvals", page: () => <ApprovalsPage />, title: "Approvals" },
  { path: "/hr", page: () => <HRPage />, roles: ["hr"], title: "HR" },
  { path: "/it", page: () => <ITPage />, title: "IT" },
  { path: "/finance", page: () => <FinancePage />, roles: ["finance"], title: "Finance" },
  { path: "/documents", page: () => <DocumentsPage />, roles: ["hr", "it", "finance"], title: "Documents" },
  { path: "/communications", page: () => <CommunicationsPage />, title: "Communications" },
  { path: "/admin", page: () => <AdminPage />, roles: [], title: "Admin" },
  { path: "/settings", page: () => <SettingsPage />, title: "Settings" },
];

const PUBLIC: Route[] = [
  { path: "/login", page: () => <LoginPage />, title: "Sign in" },
  { path: "/forgot-password", page: () => <ForgotPage />, title: "Reset your password" },
  { path: "/reset-password", page: () => <ResetPage />, title: "Choose a new password" },
];

export function App() {
  const { path, navigate } = useRouter();
  const { user, ready, has } = useAuth();
  const pub = PUBLIC.find((r) => match(r.path, path));
  const found = ROUTES.map((r) => ({ r, params: match(r.path, path) })).find((x) => x.params);
  const title = pub?.title ?? found?.r.title ?? "Not found";

  useEffect(() => {
    document.title = `${title} | AgentsMind`;
  }, [title]);

  useEffect(() => {
    if (!ready) return;
    if (!user && !pub) navigate(`/login?next=${encodeURIComponent(path)}`, { replace: true });
    if (user && path === "/login") navigate("/", { replace: true });
  }, [ready, user, pub, path, navigate]);

  if (!ready) return <div className="p-8"><Spinner label="Starting AgentsMind" /></div>;
  if (pub) return <>{pub.page({})}</>;
  if (!user) return null;
  if (!found) return <AppShell><NotFound /></AppShell>;
  const { r, params } = found;
  const allowed = r.roles === undefined || has(...r.roles);
  return <AppShell>{allowed ? r.page(params!) : <Forbidden area={r.title} />}</AppShell>;
}
