const DEFAULT_API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010";
const API_KEY = "ozicare.api";
const TOKEN_KEY = "ozicare.token";
const USER_KEY = "ozicare.user";

/**
 * The API address can be changed on the login page and is remembered per
 * browser, so a new ngrok URL does not need a rebuild and redeploy.
 */
export function getApiBase(): string {
  try {
    return localStorage.getItem(API_KEY) || DEFAULT_API;
  } catch {
    return DEFAULT_API;
  }
}

export function setApiBase(url: string) {
  const clean = url.trim().replace(/\/+$/, "");
  try {
    if (clean && clean !== DEFAULT_API) localStorage.setItem(API_KEY, clean);
    else localStorage.removeItem(API_KEY);
  } catch {}
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
  appointment: { label: string; clinic: string; address: string; channel: string } | null;
  escalation: { reason: string; summary: string; at: string; by: string } | null;
  callback_requested_at?: string | null;
  next_action_at: string | null;
  sla_due_at: string | null;
  first_contact_at: string | null;
  acknowledged_at: string | null;
  booked_at: string | null;
  closed_reason: string | null;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
};

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
};

export type Meta = {
  screening_types: Record<string, string>;
  urgencies: string[];
  statuses: string[];
  close_statuses: string[];
  channels: { whatsapp: boolean; phone_call: boolean; whatsapp_call: boolean };
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
