// Fixed at build time: .env.production for the deployed site, .env.local for dev.
const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010").replace(/\/+$/, "");
const TOKEN_KEY = "ozicare.token";
const USER_KEY = "ozicare.user";

export function getApiBase(): string {
  return API_BASE;
}

export type User = { id: string; name: string; email: string; role: string };

export type Case = {
  id: string;
  patient_name: string;
  phone: string;
  language: "en" | "ar";
  screening_type: string;
  result_summary: string;
  urgency: "routine" | "soon" | "urgent";
  status: string;
  source: string;
  location: string;
  owner_staff_id: string | null;
  owner_name: string | null;
  overdue: boolean;
  attempts: number;
  ai_paused?: boolean;
  identity_confirmed: boolean;
  appointment: { label: string; slot_iso?: string; clinic: string; address: string; channel: string } | null;
  escalation: { reason: string; summary: string; at: string; by: string } | null;
  callback_requested_at?: string | null;
  next_action_at: string | null;
  sla_due_at: string | null;
  first_contact_at: string | null;
  acknowledged_at: string | null;
  booked_at: string | null;
  attended_at?: string | null;
  closed_reason: string | null;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
  emirates_id?: string;
  region?: string;
  insurance?: string;
  pathway?: string;
  readings?: Record<string, string | number>;
  risk_findings?: Finding[];
  referral?: Referral | null;
  no_show_count?: number;
  next_action?: string;
  loss_risk: LossRisk;
  patient_link?: string;
  care_plan?: CarePlan | null;
  legs?: Leg[];
  checkins?: Checkin[];
  verification?: { at: string; source: string; facility: string; result: string; by: string } | null;
  provider_alert?: { reason: string; at: string; leg: string; service: string; facility: string } | null;
  signoff?: { by: string; role: string; at: string; note: string } | null;
};

export type CarePlan = { outcome: string; instructions: string[]; warning_signs: string[]; verify_text: string; by: string; at: string; pathway: string };

export type LegAction = { at: string; level?: number; text: string };

export type Leg = {
  id: string;
  key: string;
  service: string;
  label: string;
  kind: "report" | "visit" | "result";
  after: string | null;
  verifies: boolean;
  facility_name: string;
  network_ok: boolean;
  status: "waiting" | "requested" | "accepted" | "done";
  requested_at: string | null;
  due_at: string | null;
  level: number;
  actions: LegAction[];
  done_at: string | null;
  result: string;
  normal: boolean | null;
  token?: string;
};

export type Checkin = {
  id: string;
  day: number | null;
  due_at: string;
  status: "scheduled" | "sent" | "done" | "cancelled";
  channel: string | null;
  answers: { feeling: string; following_plan: boolean | null; warning_signs: string; notes: string } | null;
  concern?: boolean;
  done_at: string | null;
};

export type EvidenceItem = { key: string; label: string; ok: boolean; at: string | null; detail: string; required: boolean };
export type Evidence = { items: EvidenceItem[]; missing: string[]; ready_to_close: boolean; complete: boolean };

export type PlanTemplate = {
  outcome: string;
  instructions: string[];
  warning_signs: string[];
  legs: { key: string; service: string; kind: string; days: number; after?: string; verifies?: boolean; label: string }[];
  checkins: number[];
  verify_text: string;
};

export type ProviderRow = {
  case_id: string;
  patient_name: string;
  urgency: string;
  case_status: string;
  id: string;
  label: string;
  facility_name: string;
  kind: string;
  status: string;
  level: number;
  hours_waiting: number;
  due_at: string | null;
  overdue: boolean;
  blocked_by: string | null;
  actions: LegAction[];
  result?: string;
};

export type Notification = { id: string; type: string; tone: "danger" | "warn" | "info" | "ok"; case_id: string; patient_name: string; payload: Record<string, unknown>; at: string };

export type Finding = { pathway: string; urgency: string; reason: string };

export type LossRisk = { score: number; level: "none" | "low" | "medium" | "high"; reasons: string[] };

export type Referral = {
  id: string;
  service: string;
  service_label: string;
  facility_id: string | null;
  facility_name: string | null;
  facility_region: string | null;
  patient_region: string;
  insurance: string;
  network_ok: boolean;
  status: "sent" | "accepted" | "declined" | "no_facility";
  sent_at: string;
  responded_at: string | null;
  responder: string | null;
  response_note: string;
  consult: { by: string; role: string; text: string; at: string }[];
  previous: { facility_name: string; status: string; response_note: string; responder: string | null }[];
};

export type Facility = { id: string; name: string; address: string; region: string; region_label: string; services: string[]; networks: string[] };

export type Assessment = { actionable: boolean; urgency: string | null; pathway: string | null; screening_type: string | null; findings: Finding[] };

export type Message = {
  id: string;
  channel: "whatsapp" | "voice" | "system";
  direction: "inbound" | "outbound";
  body: string;
  delivery: string | null;
  meta: Record<string, unknown>;
  created_at: string;
};

export type Event = {
  id: string;
  actor: string;
  type: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type Call = {
  id: string;
  provider: string;
  direction: string;
  status: string;
  started_at: string;
  ended_at: string | null;
  summary?: string;
  agent_summary?: string;
  actions: string[];
};

export type CaseDetail = {
  case: Case;
  messages: Message[];
  events: Event[];
  calls: Call[];
  allowed_transitions: string[];
  evidence: Evidence;
};

export type Meta = {
  screening_types: Record<string, string>;
  urgencies: string[];
  statuses: string[];
  close_statuses: string[];
  channels: { whatsapp: boolean; phone_call: boolean; whatsapp_call: boolean };
  readings: Record<string, string>;
  pathways: Record<string, string>;
  rules: { pathway: string; pathway_label: string; urgency: string; criterion: string }[];
  regions: Record<string, string>;
  insurances: string[];
  services: Record<string, string>;
  facilities: Facility[];
};

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function getUser(): User | null {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as User) : null;
  } catch {
    return null;
  }
}

export function saveSession(token: string, user: User) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  // Free ngrok tunnels answer browsers with an HTML warning page unless this is set.
  headers.set("ngrok-skip-browser-warning", "1");
  const res = await fetch(`${getApiBase()}${path}`, { ...init, headers });
  if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/api/auth/login")) {
    clearSession();
    window.location.href = "/login";
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {}
    throw new ApiError(res.status, detail);
  }
  const type = res.headers.get("content-type") ?? "";
  return (type.includes("application/json") ? res.json() : res.text()) as Promise<T>;
}

export const post = <T,>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
