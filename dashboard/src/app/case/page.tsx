"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { Button, Card, ErrorNote, OverduePill, RiskPill, StatusPill, UrgencyPill, inputCls } from "@/components/ui";
import { api, getUser, post, type CaseDetail, type Event, type Message, type Meta, type User } from "@/lib/api";
import { ACTION_LABEL, PATHWAY_LABEL, REFERRAL_STYLE, REGION_LABEL, SCREENING_LABEL, STATUS_LABEL, ago, apptLabel, isClosed, when } from "@/lib/format";

type Item = { kind: "msg"; at: string; msg: Message } | { kind: "event"; at: string; ev: Event };

// Events already visible as a message bubble, or too noisy for the timeline.
const QUIET_EVENTS = new Set(["staff_message"]);

function eventText(ev: Event): string {
  const p = ev.payload as Record<string, string | number | boolean | string[] | undefined>;
  switch (ev.type) {
    case "created":
      return `Case created · ${p.urgency} · assigned to ${p.owner ?? "nobody"}`;
    case "status_changed":
      return `${STATUS_LABEL[p.from as string] ?? p.from} → ${STATUS_LABEL[p.to as string] ?? p.to}${p.note ? ` · ${p.note}` : ""}`;
    case "contacted":
      return `WhatsApp contact attempt ${p.attempt}${p.reminder ? " (reminder)" : ""}`;
    case "identity_confirmed":
      return "Patient confirmed identity and consented to details";
    case "escalated":
      return `Escalated: ${p.reason}${p.owner ? ` → ${p.owner}` : ""}`;
    case "booked":
      return `Booked ${p.label} at ${p.clinic} (${p.channel})`;
    case "slots_offered":
      return `Offered slots: ${(p.slots as string[] | undefined)?.join(", ")}`;
    case "callback_requested":
      return "Patient asked for a call";
    case "ai_answer":
      return "AI answered a free-text question (guard passed)";
    case "ai_reply_blocked":
      return "AI reply BLOCKED by safety guard and replaced with approved text";
    case "note":
      return `Note by ${p.by}: ${p.text}`;
    case "assigned":
      return `Assigned to ${p.to ?? "nobody"}`;
    case "overdue":
      return `SLA breached while ${STATUS_LABEL[p.status as string] ?? p.status}`;
    case "call_placed":
      return `Phone call placed via ${p.provider}${p.live ? "" : " (test call)"}`;
    case "call_started":
      return `${p.direction === "inbound" ? "Patient called in" : "Call started"} via ${p.provider === "livekit" ? "WhatsApp" : "phone"}`;
    case "call_ended":
      return `Call ended${p.summary ? ` · ${p.summary}` : ""}`;
    case "call_summary":
      return `Call summary: ${p.summary}`;
    case "language_changed":
      return `Language switched to ${p.to === "ar" ? "Arabic" : "English"}`;
    case "delivery_failed":
      return `WhatsApp delivery failed: ${p.error}`;
    case "ai_paused":
      return "Bot paused — staff handling conversation";
    case "ai_resumed":
      return "Bot resumed";
    case "risk_assessed":
      return `Risk rules: ${PATHWAY_LABEL[p.pathway as string] ?? p.pathway} · ${p.urgency}`;
    case "referral_sent":
      return `${p.re_referral ? "Re-referred" : "Referral sent"}: ${p.service} → ${p.facility ?? "no facility found"}${p.network_ok === false ? " (out of network)" : ""}`;
    case "referral_accepted":
      return `Referral accepted by ${p.by} at ${p.facility}`;
    case "referral_declined":
      return `Referral declined by ${p.by}: ${p.note}`;
    case "consult_note":
      return `Consult · ${p.by}: ${p.text}`;
    case "attended":
      return `Attended ${p.appointment ?? "appointment"}`;
    case "no_show":
      return `Did not attend ${p.appointment ?? ""} (no-show #${p.count})`;
    case "fhir_ingested":
      return `Received from health record (FHIR) · ${p.findings}`;
    default:
      return ev.type.replaceAll("_", " ");
  }
}

const EVENT_TONE: Record<string, string> = {
  escalated: "text-orange-700",
  ai_reply_blocked: "text-red-700",
  delivery_failed: "text-red-700",
  overdue: "text-red-700",
  booked: "text-teal-700",
  identity_confirmed: "text-teal-700",
  attended: "text-emerald-700",
  referral_accepted: "text-emerald-700",
  no_show: "text-red-700",
  referral_declined: "text-red-700",
  risk_assessed: "text-indigo-700",
  consult_note: "text-indigo-700",
};

function Bubble({ m }: { m: Message }) {
  const inbound = m.direction === "inbound";
  const by = (m.meta?.by as string) ?? "";
  const kind = (m.meta?.kind as string) ?? "";
  const label = inbound ? "Patient" : by === "staff" ? `Staff · ${m.meta?.staff ?? ""}` : by === "ai" ? "AI answer" : "OziCare";
  const failed = Boolean(m.meta?.error);
  return (
    <div className={`flex ${inbound ? "justify-start" : "justify-end"}`}>
      <div className="max-w-[78%]">
        <div className={`mb-1 flex items-center gap-2 text-[11px] text-slate-500 ${inbound ? "" : "justify-end"}`}>
          <span className="font-medium">{label}</span>
          <span>{m.channel === "voice" ? "📞 call" : "WhatsApp"}</span>
          <span>{when(m.created_at)}</span>
          {!inbound && m.delivery && <span className={m.delivery === "failed" ? "text-red-600" : ""}>· {m.delivery}</span>}
        </div>
        <div
          dir="auto"
          className={`whitespace-pre-wrap rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed shadow-sm ${
            failed
              ? "bg-red-50 text-red-900 ring-1 ring-red-200"
              : inbound
                ? "rounded-tl-sm bg-white text-slate-900 ring-1 ring-slate-200"
                : by === "staff"
                  ? "rounded-tr-sm bg-indigo-600 text-white"
                  : by === "ai"
                    ? "rounded-tr-sm bg-teal-50 text-teal-950 ring-1 ring-teal-200"
                    : "rounded-tr-sm bg-teal-700 text-white"
          }`}
        >
          {m.body}
          {failed && <div className="mt-1 text-xs text-red-700">Not delivered: {String(m.meta?.error)}</div>}
          {kind === "explain" && <div className="mt-1 text-[11px] opacity-75">Approved template</div>}
        </div>
      </div>
    </div>
  );
}

// Static export cannot pre-render unknown case ids, so the id is a query
// parameter (/case?id=OC-…) rather than a path segment.
export default function CasePage() {
  return (
    <Suspense fallback={null}>
      <CaseView />
    </Suspense>
  );
}

function ReferralCard({
  caseId,
  c,
  meta,
  busy,
  act,
  closed,
}: {
  caseId: string;
  c: CaseDetail["case"];
  meta: Meta | null;
  busy: boolean;
  act: (fn: () => Promise<unknown>) => Promise<void>;
  closed: boolean;
}) {
  const ref = c.referral!;
  const [consult, setConsult] = useState("");
  const [moving, setMoving] = useState(false);
  const [facility, setFacility] = useState("");
  const me = getUser();
  const canRespond = me && (me.role === "clinician" || me.role === "admin");
  const options = (meta?.facilities ?? []).filter((f) => f.services.includes(ref.service) && f.id !== ref.facility_id);

  return (
    <Card className="p-5 text-sm">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold text-slate-900">Referral</h2>
        <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${REFERRAL_STYLE[ref.status] ?? ""}`}>{ref.status.replace("_", " ")}</span>
      </div>
      <p className="mt-2 font-medium text-slate-800">{ref.service_label}</p>
      <p className="text-slate-700">{ref.facility_name ?? "No facility offers this service"}</p>
      <p className="text-xs text-slate-500">
        {REGION_LABEL[ref.facility_region ?? ""] ?? ""}
        {ref.facility_region && ref.facility_region !== ref.patient_region ? ` (patient lives in ${REGION_LABEL[ref.patient_region]})` : ""}
        {ref.insurance ? ` · ${ref.insurance} ${ref.network_ok ? "✓ in network" : "⚠ out of network"}` : ""}
      </p>
      <p className="mt-1 text-xs text-slate-500">Sent {when(ref.sent_at)}</p>
      {ref.responded_at && (
        <p className="mt-1 text-xs text-slate-600">
          {ref.status === "accepted" ? "Accepted" : "Declined"} by {ref.responder} {when(ref.responded_at)}
          {ref.response_note ? `: ${ref.response_note}` : ""}
        </p>
      )}
      {ref.previous.length > 0 && (
        <p className="mt-1 text-xs text-slate-500">Previously: {ref.previous.map((p) => `${p.facility_name} (${p.status})`).join(", ")}</p>
      )}

      {!closed && (
        <div className="mt-3 flex flex-wrap gap-2">
          {ref.status === "sent" && canRespond && (
            <>
              <Button variant="primary" disabled={busy} onClick={() => act(() => post(`/api/cases/${caseId}/referral/respond`, { accept: true }))}>
                Accept
              </Button>
              <Button
                disabled={busy}
                onClick={() => {
                  const n = window.prompt("Reason for declining (shared with the referring team)");
                  if (n) act(() => post(`/api/cases/${caseId}/referral/respond`, { accept: false, note: n }));
                }}
              >
                Decline
              </Button>
            </>
          )}
          <Button variant="ghost" disabled={busy} onClick={() => setMoving(!moving)}>
            Re-refer…
          </Button>
        </div>
      )}
      {moving && (
        <div className="mt-2 flex gap-2">
          <select className={inputCls} value={facility} onChange={(e) => setFacility(e.target.value)}>
            <option value="">Next suitable facility (auto)</option>
            {options.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name} · {f.region_label}
                {ref.insurance && !f.networks.includes(ref.insurance) ? " (out of network)" : ""}
              </option>
            ))}
          </select>
          <Button
            variant="primary"
            disabled={busy}
            onClick={() =>
              act(async () => {
                await post(`/api/cases/${caseId}/referral/resend`, { facility_id: facility || null });
                setMoving(false);
                setFacility("");
              })
            }
          >
            Send
          </Button>
        </div>
      )}

      <div className="mt-4 border-t border-slate-100 pt-3">
        <h3 className="mb-2 text-xs font-semibold uppercase text-slate-500">Clinician consult</h3>
        {ref.consult.length === 0 && <p className="text-xs text-slate-400">No consult notes yet.</p>}
        <ul className="space-y-2">
          {ref.consult.map((n, i) => (
            <li key={i} className="rounded-lg bg-indigo-50 p-2.5 text-indigo-950">
              <div className="text-[11px] text-indigo-700">
                {n.by} ({n.role}) · {when(n.at)}
              </div>
              {n.text}
            </li>
          ))}
        </ul>
        {!closed && (
          <form
            className="mt-2 flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (consult.trim())
                act(async () => {
                  await post(`/api/cases/${caseId}/referral/consult`, { text: consult });
                  setConsult("");
                });
            }}
          >
            <input className={inputCls} value={consult} onChange={(e) => setConsult(e.target.value)} placeholder="Note to the receiving clinician" />
            <Button disabled={busy || !consult.trim()}>Send</Button>
          </form>
        )}
      </div>
    </Card>
  );
}

function CaseView() {
  const id = useSearchParams().get("id") ?? "";
  const [d, setD] = useState<CaseDetail | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [staff, setStaff] = useState<User[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [closing, setClosing] = useState<string | null>(null);
  const [closeNote, setCloseNote] = useState("");
  const [note, setNote] = useState("");
  const [reply, setReply] = useState("");

  const load = useCallback(async () => {
    try {
      setD(await api<CaseDetail>(`/api/cases/${id}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load case");
    }
  }, [id]);

  useEffect(() => {
    load();
    api<Meta>("/api/meta").then(setMeta).catch(() => {});
    api<User[]>("/api/staff").then(setStaff).catch(() => {});
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [load]);

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  if (!d) {
    return (
      <Shell>
        <p className="text-slate-500">{error ?? "Loading…"}</p>
      </Shell>
    );
  }

  const c = d.case;
  const closed = isClosed(c.status);
  const items: Item[] = [
    ...d.messages.map((m) => ({ kind: "msg" as const, at: m.created_at, msg: m })),
    ...d.events.filter((e) => !QUIET_EVENTS.has(e.type)).map((e) => ({ kind: "event" as const, at: e.created_at, ev: e })),
  ].sort((a, b) => a.at.localeCompare(b.at));

  const progress = d.allowed_transitions.filter((s) => !s.startsWith("closed_") && s !== "escalated" && !(c.status === "booked" && s === "in_care"));
  const closes = d.allowed_transitions.filter((s) => s.startsWith("closed_"));

  return (
    <Shell>
      <div className="mb-4 flex items-center gap-2 text-sm text-slate-500">
        <Link href="/board" className="hover:text-teal-700">
          Case board
        </Link>
        <span>/</span>
        <span className="text-slate-700">{c.id}</span>
        {c.patient_link && (
          <a
            href={`/p?t=${new URL(c.patient_link).searchParams.get("t")}`}
            target="_blank"
            rel="noreferrer"
            className="ml-auto rounded-lg px-2.5 py-1 font-medium text-teal-800 ring-1 ring-inset ring-teal-200 hover:bg-teal-50"
            title="Opens exactly what the patient sees (actions there count as the patient's)"
          >
            Open patient page ↗
          </a>
        )}
      </div>

      {/* Header */}
      <Card className={`mb-4 p-5 ${c.urgency === "urgent" && !closed ? "border-red-300 ring-2 ring-red-200" : ""}`}>
        <div className="flex flex-wrap items-start gap-4">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-semibold text-slate-900">{c.patient_name}</h1>
              <UrgencyPill urgency={c.urgency} />
              <StatusPill status={c.status} />
              {c.overdue && !closed && <OverduePill />}
              {!closed && <RiskPill risk={c.loss_risk} />}
              {c.ai_paused && !closed && <span className="rounded-full bg-indigo-50 px-2.5 py-0.5 text-xs font-medium text-indigo-700 ring-1 ring-inset ring-indigo-200">Staff handling chat</span>}
            </div>
            <p className="mt-1 text-sm text-slate-500">
              {c.phone} · {c.language === "ar" ? "Arabic" : "English"} · {SCREENING_LABEL[c.screening_type] ?? c.screening_type} · {c.source}
              {c.location ? ` · ${c.location}` : ""}
            </p>
            <p className="mt-0.5 text-sm text-slate-500">
              {c.emirates_id ? `Emirates ID ${c.emirates_id} · ` : ""}
              {REGION_LABEL[c.region ?? ""] ?? "Abu Dhabi"}
              {c.insurance ? ` · ${c.insurance}` : ""}
              {c.pathway ? ` · ${PATHWAY_LABEL[c.pathway] ?? c.pathway} pathway` : ""}
            </p>
          </div>
          <div className="ml-auto flex items-center gap-2 text-sm">
            <span className="text-slate-500">Owner</span>
            <select
              className="rounded-lg border-0 py-1.5 pl-3 pr-8 text-sm ring-1 ring-inset ring-slate-300"
              value={c.owner_staff_id ?? ""}
              disabled={busy}
              onChange={(e) => act(() => post(`/api/cases/${id}/assign`, { staff_id: e.target.value || null }))}
            >
              <option value="">Unassigned</option>
              {staff.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.role})
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Actions */}
        {!closed ? (
          <div className="mt-5 border-t border-slate-100 pt-4">
            {/* Reach the patient: the main action on this page. */}
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="primary"
                className="px-4 py-2.5 text-[15px] shadow-md"
                disabled={busy}
                title="Sends the WhatsApp message with the patient page link and a 'Talk to us' call button; the patient calls when ready"
                onClick={() => act(() => post(`/api/cases/${id}/outreach?channel=invite`))}
              >
                📲 {c.first_contact_at ? "Notify patient again" : "Notify patient"}
              </Button>
              <Button
                disabled={busy || !meta?.channels.whatsapp_call}
                title="Sends the message, then the AI rings them on WhatsApp (blocked by Meta for some countries, e.g. +234)"
                onClick={() =>
                  act(async () => {
                    const r = await post<{ call_error: string | null }>(`/api/cases/${id}/outreach?channel=whatsapp`);
                    if (r.call_error) setError(`Message sent. WhatsApp call: ${r.call_error}`);
                  })
                }
              >
                AI calls on WhatsApp
              </Button>
              <Button
                disabled={busy || !meta?.channels.phone_call}
                title={meta?.channels.phone_call ? "Sends the WhatsApp message, then the AI rings the phone number (Bimpe)" : "Phone calls need BIMPEAI_AGENT_ID"}
                onClick={() =>
                  act(async () => {
                    const r = await post<{ call_error: string | null }>(`/api/cases/${id}/outreach?channel=phone`);
                    if (r.call_error) setError(`Message sent. Phone call: ${r.call_error}`);
                  })
                }
              >
                AI calls phone
              </Button>
              {c.status === "booked" && (
                <>
                  <span className="mx-1 h-6 w-px bg-slate-200" />
                  <Button variant="primary" disabled={busy} onClick={() => act(() => post(`/api/cases/${id}/attendance`, { attended: true }))}>
                    ✓ Attended
                  </Button>
                  <Button
                    disabled={busy}
                    onClick={() => {
                      const n = window.prompt("No-show: any note? (the patient gets a re-booking message)", "");
                      if (n !== null) act(() => post(`/api/cases/${id}/attendance`, { attended: false, note: n }));
                    }}
                  >
                    ✗ Did not attend
                  </Button>
                </>
              )}
              {c.status !== "escalated" && (
                <Button
                  variant="danger"
                  className="ml-auto"
                  disabled={busy}
                  onClick={() => {
                    const reason = window.prompt("Why are you escalating this case?");
                    if (reason) act(() => post(`/api/cases/${id}/escalate`, { reason }));
                  }}
                >
                  Escalate
                </Button>
              )}
            </div>
            {/* Manual status changes, for staff working the case by hand. */}
            <details className="mt-3 text-sm">
              <summary className="cursor-pointer select-none text-xs font-semibold text-slate-500 hover:text-slate-800">More actions: update status or close the case</summary>
              <div className="mt-2 flex flex-wrap gap-2">
                {progress.map((s) => (
                  <Button key={s} disabled={busy} onClick={() => act(() => post(`/api/cases/${id}/status`, { status: s }))}>
                    {ACTION_LABEL[s] ?? s}
                  </Button>
                ))}
                {closes.map((s) => (
                  <Button key={s} disabled={busy} onClick={() => setClosing(s)}>
                    {ACTION_LABEL[s] ?? s}
                  </Button>
                ))}
                <Button disabled={busy} onClick={() => act(() => post(`/api/cases/${id}/contact`))}>
                  Send reminder text only
                </Button>
              </div>
            </details>
          </div>
        ) : (
          <div className="mt-5 flex items-center gap-3 border-t border-slate-100 pt-4 text-sm text-slate-600">
            Closed {when(c.closed_at)} · reason: <b>{c.closed_reason?.replaceAll("_", " ")}</b>
            <Button
              className="ml-auto"
              disabled={busy}
              onClick={() => {
                const n = window.prompt("Why are you reopening this case?");
                if (n) act(() => post(`/api/cases/${id}/reopen`, { status: "contacted", note: n }));
              }}
            >
              Reopen
            </Button>
          </div>
        )}

        {closing && (
          <div className="mt-4 rounded-lg bg-slate-50 p-4 ring-1 ring-slate-200">
            <p className="mb-2 text-sm font-medium text-slate-800">{ACTION_LABEL[closing]} — what is the evidence?</p>
            <textarea
              className={inputCls}
              rows={2}
              value={closeNote}
              onChange={(e) => setCloseNote(e.target.value)}
              placeholder={closing === "closed_completed" ? "Seen at Riverside PHC on 3 Nov, repeat BP normal, discharged." : "Reason and what was tried"}
              autoFocus
            />
            <div className="mt-2 flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setClosing(null)}>
                Cancel
              </Button>
              <Button
                variant="primary"
                disabled={busy || !closeNote.trim()}
                onClick={() =>
                  act(async () => {
                    await post(`/api/cases/${id}/status`, { status: closing, note: closeNote });
                    setClosing(null);
                    setCloseNote("");
                  })
                }
              >
                Close case
              </Button>
            </div>
          </div>
        )}
        <div className="mt-3">
          <ErrorNote text={error} />
        </div>
      </Card>

      {c.escalation && c.status === "escalated" && (
        <Card className="mb-4 border-orange-300 bg-orange-50 p-5">
          <div className="flex items-center gap-2 text-sm font-semibold text-orange-900">
            <span className="grid h-6 w-6 place-items-center rounded-full bg-orange-500 text-xs text-white">!</span>
            Escalated {ago(c.escalation.at)} by {c.escalation.by} — {c.escalation.reason}
          </div>
          {c.escalation.summary && <p className="mt-2 whitespace-pre-wrap text-sm text-orange-950">{c.escalation.summary}</p>}
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
        {/* Timeline */}
        <Card className="flex flex-col">
          <div className="border-b border-slate-100 px-5 py-3 font-semibold text-slate-900">Conversation & audit timeline</div>
          <div className="flex-1 space-y-3 overflow-y-auto bg-slate-50/60 px-5 py-4" style={{ maxHeight: "62vh" }}>
            {items.map((it) =>
              it.kind === "msg" ? (
                <Bubble key={it.msg.id} m={it.msg} />
              ) : (
                <div key={it.ev.id} className={`flex items-center gap-2 text-xs ${EVENT_TONE[it.ev.type] ?? "text-slate-500"}`}>
                  <span className="h-px flex-1 bg-slate-200" />
                  <span className="max-w-[80%] text-center">
                    {eventText(it.ev)} · <span className="opacity-70">{it.ev.actor}</span> · {when(it.ev.created_at)}
                  </span>
                  <span className="h-px flex-1 bg-slate-200" />
                </div>
              ),
            )}
          </div>
          {!closed && (
            <form
              className="flex gap-2 border-t border-slate-100 p-3"
              onSubmit={(e) => {
                e.preventDefault();
                if (reply.trim()) act(async () => {
                  await post(`/api/cases/${id}/message`, { text: reply, take_over: true });
                  setReply("");
                });
              }}
            >
              <input dir="auto" className={inputCls} value={reply} onChange={(e) => setReply(e.target.value)} placeholder="Reply to the patient on WhatsApp (pauses the bot)" />
              <Button variant="primary" disabled={busy || !reply.trim()}>
                Send
              </Button>
            </form>
          )}
        </Card>

        {/* Side panel */}
        <div className="space-y-4">
          {(c.risk_findings?.length ?? 0) > 0 && (
            <Card className="p-5 text-sm">
              <h2 className="mb-2 font-semibold text-slate-900">Why this person was prioritised</h2>
              <ul className="space-y-1.5">
                {c.risk_findings!.map((f) => (
                  <li key={f.pathway} className="flex gap-2">
                    <span className={`mt-0.5 h-2 w-2 shrink-0 rounded-full ${f.urgency === "urgent" ? "bg-red-600" : f.urgency === "soon" ? "bg-amber-500" : "bg-slate-400"}`} />
                    <span>
                      <b>{PATHWAY_LABEL[f.pathway] ?? f.pathway}</b> · {f.reason}
                    </span>
                  </li>
                ))}
              </ul>
              {c.readings && Object.keys(c.readings).length > 0 && (
                <p className="mt-2 text-xs text-slate-500">
                  Readings: {Object.entries(c.readings).map(([k, v]) => `${meta?.readings[k]?.split(" (")[0] ?? k} ${v}`).join(" · ")}
                </p>
              )}
            </Card>
          )}

          {c.loss_risk && c.loss_risk.reasons.length > 0 && !closed && (
            <Card className={`p-5 text-sm ${c.loss_risk.level === "high" ? "border-rose-300 bg-rose-50" : ""}`}>
              <div className="flex items-center justify-between">
                <h2 className="font-semibold text-slate-900">Lost-to-follow-up risk</h2>
                <RiskPill risk={c.loss_risk} />
              </div>
              <ul className="mt-2 list-disc pl-5 text-slate-700">
                {c.loss_risk.reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </Card>
          )}

          {c.referral && <ReferralCard caseId={id} c={d.case} meta={meta} busy={busy} act={act} closed={closed} />}
          <Card className="p-5 text-sm">
            <h2 className="mb-3 font-semibold text-slate-900">Case</h2>
            <dl className="grid grid-cols-[110px_1fr] gap-y-2">
              <dt className="text-slate-500">Created</dt>
              <dd>{when(c.created_at)}</dd>
              <dt className="text-slate-500">First contact</dt>
              <dd>{c.first_contact_at ? `${when(c.first_contact_at)}` : "—"}</dd>
              <dt className="text-slate-500">Acknowledged</dt>
              <dd>{when(c.acknowledged_at)}</dd>
              <dt className="text-slate-500">Identity</dt>
              <dd>{c.identity_confirmed ? "Confirmed" : "Not yet"}</dd>
              <dt className="text-slate-500">Attempts</dt>
              <dd>{c.attempts}</dd>
              <dt className="text-slate-500">Attended</dt>
              <dd>{c.attended_at ? when(c.attended_at) : "—"}</dd>
              {(c.no_show_count ?? 0) > 0 && (
                <>
                  <dt className="text-slate-500">No-shows</dt>
                  <dd className="font-medium text-red-600">{c.no_show_count}</dd>
                </>
              )}
              {!closed && (
                <>
                  <dt className="text-slate-500">SLA due</dt>
                  <dd className={c.overdue ? "font-medium text-red-600" : ""}>{when(c.sla_due_at)} ({ago(c.sla_due_at)})</dd>
                </>
              )}
            </dl>
            {c.result_summary && (
              <div className="mt-3 rounded-lg bg-slate-50 p-3 text-slate-700">
                <div className="mb-1 text-xs font-medium uppercase text-slate-500">Note for patient</div>
                {c.result_summary}
              </div>
            )}
          </Card>

          {c.appointment && (
            <Card className="border-teal-200 bg-teal-50 p-5 text-sm">
              <h2 className="mb-1 font-semibold text-teal-900">Appointment</h2>
              <p className="text-lg font-bold text-teal-900">{apptLabel(c.appointment)}</p>
              <p className="text-teal-800" dir="auto">
                {c.appointment.clinic}
              </p>
              <p className="mt-1 text-xs text-teal-700">Booked via {c.appointment.channel}</p>
            </Card>
          )}

          {!closed && (
            <Card className="p-5 text-sm">
              <div className="flex items-center justify-between">
                <h2 className="font-semibold text-slate-900">WhatsApp bot</h2>
                <Button disabled={busy} onClick={() => act(() => post(`/api/cases/${id}/ai`, { paused: !c.ai_paused }))}>
                  {c.ai_paused ? "Resume bot" : "Pause bot"}
                </Button>
              </div>
              <p className="mt-2 text-slate-500">{c.ai_paused ? "Patient messages are logged for staff; the bot does not reply." : "The bot answers the patient from approved content."}</p>
            </Card>
          )}

          {d.calls.length > 0 && (
            <Card className="p-5 text-sm">
              <h2 className="mb-3 font-semibold text-slate-900">Calls</h2>
              <ul className="space-y-3">
                {d.calls.map((call) => (
                  <li key={call.id} className="rounded-lg bg-slate-50 p-3">
                    <div className="flex justify-between text-xs text-slate-500">
                      <span>
                        {call.provider === "livekit" ? "WhatsApp call" : "Phone call"} · {call.direction}
                      </span>
                      <span>{call.status}</span>
                    </div>
                    <div className="text-xs text-slate-500">{when(call.started_at)}</div>
                    {(call.summary || call.agent_summary) && <p className="mt-1.5 whitespace-pre-wrap text-slate-700">{call.summary || call.agent_summary}</p>}
                  </li>
                ))}
              </ul>
            </Card>
          )}

          <Card className="p-5 text-sm">
            <h2 className="mb-2 font-semibold text-slate-900">Add note</h2>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (note.trim()) act(async () => {
                  await post(`/api/cases/${id}/note`, { text: note });
                  setNote("");
                });
              }}
              className="space-y-2"
            >
              <textarea className={inputCls} rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Internal note (not sent to patient)" />
              <Button disabled={busy || !note.trim()}>Save note</Button>
            </form>
          </Card>
        </div>
      </div>
    </Shell>
  );
}
