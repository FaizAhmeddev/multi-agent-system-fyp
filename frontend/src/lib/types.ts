/* Shapes returned by the AgentsMind API (see docs/ASSISTANT.md and docs/MCP_TOOLS.md). */

export interface Department {
  slug: string;
  name: string;
  description: string;
  accessible: boolean;
  reason: string;
}

export interface Detail {
  label: string;
  value: string;
}

export interface ApprovalInfo {
  id: number;
  tool: string;
  risk: "write" | "destructive";
  summary: string;
  details: Detail[];
  confirm_text: string;
}

export type CardKind = "text" | "clarify" | "approval" | "result" | "error" | "denied" | "fallback";

export interface Card {
  kind: CardKind;
  agent: string;
  title: string;
  body: string;
  data: Record<string, unknown>;
  simulated: boolean;
  untrusted: boolean;
  warnings: string[];
  options: string[];
  links: { label: string; url: string }[];
  approval: ApprovalInfo | null;
}

export interface TurnResult {
  conversation_id: number;
  message_id: number;
  cards: Card[];
  planner: string;
  steps: { agent: string; text: string }[];
  pending: boolean;
  simulated: boolean;
  llm: string;
}

export interface Approval {
  id: number;
  agent: string;
  tool: string;
  risk: "write" | "destructive";
  summary: string;
  arguments: Record<string, unknown>;
  status: "pending" | "approved" | "rejected" | "executed" | "failed";
  result: Record<string, unknown>;
  created_at: string;
  decided_at: string | null;
}

export interface ApproveResponse {
  approval: Approval;
  outcome: {
    status: string;
    error: string;
    code: string;
    result: { body: string; links: { label: string; url: string }[]; simulated: boolean } | null;
  };
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages?: number;
}

export interface ToolResult<T> {
  result: T;
  tool: string;
  approval_id?: number | null;
  source: string;
}

export interface Person {
  id: number;
  full_name: string;
  email: string;
  department: string;
  job_title: string;
  employment_type: string;
  monthly_salary: string;
  currency: string;
  status: string;
  start_date: string;
  notes: string;
}

export interface Payment {
  id: number;
  person_id: number;
  person_name: string;
  month: string;
  amount: string;
  currency: string;
  status: string;
  paid_on: string | null;
  note: string;
}

export interface FinanceSummary {
  people_total: number;
  people_active: number;
  people_inactive: number;
  payroll_by_currency: { currency: string; active_people: number; total_monthly_payroll: string }[];
  payroll_by_department: { department: string; currency: string; active_people: number; total_monthly_payroll: string }[];
  payments_by_status: { status: string; currency: string; count: number; total: string }[];
  computed_by: string;
}

export interface Ticket {
  number: string;
  requester_name: string;
  requester_email: string;
  department: string;
  category: string;
  priority: string;
  summary: string;
  description: string;
  status: string;
  assignee: string;
  source: string;
  sla_due_at: string;
  sla_breached: boolean;
  expected_response: string;
  created_at: string;
  updated_at: string;
  comments: { author: string; body: string; internal: boolean; created_at: string }[];
}

export interface RubricRow {
  criterion: string;
  kind: string;
  rating: string;
  evidence: string;
}

export interface Candidate {
  id: number;
  name: string;
  job_title: string;
  stage: string;
  notes: string;
  updated_at: string;
  rubric_score: number | null;
  keyword_score: number | null;
  needs_human_review: boolean;
  recommendation: string | null;
  simulated: boolean;
  matched?: string[];
  missing?: string[];
  details?: {
    rubric?: RubricRow[];
    review_reasons?: string[];
    flags?: string[];
    recommendation?: string;
    job_description_file?: string;
  };
}

export interface DriveFile {
  id: string;
  name: string;
  mime_type: string;
  modified: string;
  size: number | null;
  path: string;
  web_link: string | null;
}

export interface Email {
  id: string;
  thread_id: string;
  sender: string;
  to: string;
  subject: string;
  date: string;
  snippet: string;
  body: string;
  unread: boolean;
  body_truncated: boolean;
  suspicious?: boolean;
}

export interface CalEvent {
  id: string;
  summary: string;
  start: string;
  end: string;
  timezone: string;
  description: string;
  location: string;
  attendees: string[];
  meet_link: string | null;
  html_link: string | null;
  status: string;
}

export interface Mode {
  mode: "sandbox" | "google";
  simulated: boolean;
}
