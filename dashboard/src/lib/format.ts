export const STATUS_LABEL: Record<string, string> = {
  new: "New",
  contacted: "Contacted",
  acknowledged: "Acknowledged",
  booked: "Booked",
  in_care: "In care",
  escalated: "Escalated",
  closed_completed: "Closed · completed",
  closed_declined: "Closed · declined",
  closed_lost: "Closed · lost to follow-up",
  closed_transferred: "Closed · transferred",
};

export const STATUS_STYLE: Record<string, string> = {
  new: "bg-slate-100 text-slate-700 ring-slate-200",
  contacted: "bg-sky-50 text-sky-700 ring-sky-200",
  acknowledged: "bg-indigo-50 text-indigo-700 ring-indigo-200",
  booked: "bg-teal-50 text-teal-700 ring-teal-200",
  in_care: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  escalated: "bg-orange-50 text-orange-700 ring-orange-300",
  closed_completed: "bg-emerald-600 text-white ring-emerald-600",
  closed_declined: "bg-slate-200 text-slate-700 ring-slate-300",
  closed_lost: "bg-slate-200 text-slate-700 ring-slate-300",
  closed_transferred: "bg-slate-200 text-slate-700 ring-slate-300",
};

export const URGENCY_STYLE: Record<string, string> = {
  urgent: "bg-red-600 text-white ring-red-600",
  soon: "bg-amber-100 text-amber-800 ring-amber-300",
  routine: "bg-slate-100 text-slate-600 ring-slate-200",
};

export const SCREENING_LABEL: Record<string, string> = {
  blood_pressure: "Blood pressure",
  diabetes: "Blood sugar / diabetes",
  obesity: "Weight / BMI",
  cervical: "Cervical",
  colorectal: "Bowel (FIT)",
  breast: "Breast (mammogram)",
  general_abnormal: "General abnormal",
};

export const PATHWAY_LABEL: Record<string, string> = {
  hypertension: "Hypertension",
  diabetes: "Diabetes",
  obesity: "Obesity",
  cervical: "Cervical cancer",
  colorectal: "Colorectal cancer",
  breast: "Breast cancer",
  general: "General review",
};

export const REGION_LABEL: Record<string, string> = { abu_dhabi: "Abu Dhabi", al_ain: "Al Ain", al_dhafra: "Al Dhafra" };

export const RISK_STYLE: Record<string, string> = {
  high: "bg-rose-600 text-white ring-rose-600",
  medium: "bg-amber-50 text-amber-800 ring-amber-300",
  low: "bg-slate-50 text-slate-500 ring-slate-200",
  none: "bg-slate-50 text-slate-400 ring-slate-200",
};

export const REFERRAL_STYLE: Record<string, string> = {
  sent: "bg-sky-50 text-sky-700 ring-sky-200",
  accepted: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  declined: "bg-red-50 text-red-700 ring-red-200",
  no_facility: "bg-red-50 text-red-700 ring-red-200",
};

export const ACTION_LABEL: Record<string, string> = {
  contacted: "Mark contacted",
  acknowledged: "Mark acknowledged",
  booked: "Mark booked",
  in_care: "Mark attended / in care",
  escalated: "Escalate",
  closed_completed: "Close · completed",
  closed_declined: "Close · declined",
  closed_lost: "Close · lost to follow-up",
  closed_transferred: "Close · transferred",
};

export function ago(iso: string | null | undefined): string {
  if (!iso) return "—";
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  const future = s < 0;
  const a = Math.abs(s);
  const txt = a < 60 ? `${a}s` : a < 3600 ? `${Math.round(a / 60)}m` : a < 86400 ? `${Math.round(a / 3600)}h` : `${Math.round(a / 86400)}d`;
  return future ? `in ${txt}` : `${txt} ago`;
}

export function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function maskPhone(p: string): string {
  return p.length > 6 ? `${p.slice(0, 4)} ••• ${p.slice(-4)}` : p;
}

export const isClosed = (s: string) => s.startsWith("closed_");

/** Appointment time in English for staff, whatever language the patient uses. */
export function apptLabel(a: { slot_iso?: string; label: string } | null | undefined): string {
  if (!a) return "—";
  if (!a.slot_iso) return a.label;
  const d = new Date(a.slot_iso);
  return d.toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}
