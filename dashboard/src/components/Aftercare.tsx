"use client";

import { useEffect, useState } from "react";
import { Button, Card, inputCls } from "@/components/ui";
import { api, getApiBase, getToken, getUser, post, type Case, type Evidence, type Leg, type PlanTemplate } from "@/lib/api";
import { LEG_STATUS, LEVEL_LABEL, LEVEL_STYLE, ago, when } from "@/lib/format";

type Act = (fn: () => Promise<unknown>) => Promise<void>;

const isClinician = () => {
  const r = getUser()?.role;
  return r === "clinician" || r === "admin";
};

/** After the first visit: the clinician records the outcome and plan. */
export function CarePlanForm({ caseId, busy, act }: { caseId: string; busy: boolean; act: Act }) {
  const [t, setT] = useState<PlanTemplate | null>(null);
  const [outcome, setOutcome] = useState("");
  const [ins, setIns] = useState("");
  const [warn, setWarn] = useState("");
  const [legs, setLegs] = useState<string[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    api<PlanTemplate>(`/api/cases/${caseId}/care-plan/template`)
      .then((p) => {
        setT(p);
        setOutcome(p.outcome);
        setIns(p.instructions.join("\n"));
        setWarn(p.warning_signs.join("\n"));
        setLegs(p.legs.map((l) => l.key));
      })
      .catch(() => {});
  }, [caseId]);

  if (!t) return null;
  const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);

  return (
    <Card className="mb-4 border-violet-300 p-5 ring-2 ring-violet-100">
      <div className="flex flex-wrap items-center gap-3">
        <span className="grid h-8 w-8 place-items-center rounded-full bg-violet-600 text-sm font-bold text-white">✚</span>
        <div>
          <h2 className="font-semibold text-slate-900">Record the visit outcome and care plan</h2>
          <p className="text-sm text-slate-500">The navigator sends it to the patient in their language, books the next providers and starts recovery check-ins.</p>
        </div>
        {!open && (
          <Button variant="primary" className="ml-auto" onClick={() => setOpen(true)}>
            Write care plan
          </Button>
        )}
      </div>
      {open && (
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <label className="block md:col-span-2">
            <span className="mb-1 block text-sm font-medium text-slate-700">Visit outcome</span>
            <textarea className={inputCls} rows={2} value={outcome} onChange={(e) => setOutcome(e.target.value)} />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-700">What the patient should do (one per line)</span>
            <textarea className={inputCls} rows={4} value={ins} onChange={(e) => setIns(e.target.value)} />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-700">Warning signs (one per line)</span>
            <textarea className={inputCls} rows={4} value={warn} onChange={(e) => setWarn(e.target.value)} />
          </label>
          <div className="md:col-span-2">
            <span className="mb-2 block text-sm font-medium text-slate-700">Next providers OziCare coordinates</span>
            <div className="grid gap-2 sm:grid-cols-3">
              {t.legs.map((l) => (
                <label key={l.key} className={`flex cursor-pointer gap-2 rounded-lg p-3 text-sm ring-1 ring-inset ${legs.includes(l.key) ? "bg-violet-50 ring-violet-300" : "ring-slate-200"}`}>
                  <input type="checkbox" checked={legs.includes(l.key)} onChange={(e) => setLegs(e.target.checked ? [...legs, l.key] : legs.filter((k) => k !== l.key))} />
                  <span>
                    <b className="block text-slate-900">{l.label}</b>
                    <span className="text-xs text-slate-500">
                      {l.kind === "report" ? `report within ${l.days} days` : l.kind === "visit" ? "visit" : `result in ${l.days} days`}
                      {l.after ? " · after the previous step" : ""}
                      {l.verifies ? " · verifies recovery" : ""}
                    </span>
                  </span>
                </label>
              ))}
            </div>
            <p className="mt-2 text-xs text-slate-500">
              Check-ins on day {t.checkins.join(" and ")}. Recovery is verified when: <b>{t.verify_text}</b>.
            </p>
          </div>
          <div className="flex justify-end gap-2 md:col-span-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              disabled={busy || !isClinician()}
              title={isClinician() ? "" : "A clinician records the care plan"}
              onClick={() => act(() => post(`/api/cases/${caseId}/care-plan`, { outcome, instructions: lines(ins), warning_signs: lines(warn), legs, checkins: t.checkins }))}
            >
              Save and send to patient
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}

function LegRow({ leg, caseId, busy, act, closed }: { leg: Leg; caseId: string; busy: boolean; act: Act; closed: boolean }) {
  const done = leg.status === "done";
  const late = !done && leg.due_at && new Date(leg.due_at).getTime() < Date.now();
  const link = leg.token ? `/provider?t=${leg.token}` : "";
  return (
    <li className={`rounded-xl p-3.5 ring-1 ring-inset ${leg.level >= 3 && !done ? "bg-red-50 ring-red-200" : leg.level === 2 && !done ? "bg-violet-50/60 ring-violet-200" : done ? "bg-emerald-50/50 ring-emerald-200" : "bg-white ring-slate-200"}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className={`grid h-6 w-6 shrink-0 place-items-center rounded-full text-xs font-bold ${done ? "bg-emerald-600 text-white" : leg.status === "waiting" ? "bg-slate-200 text-slate-500" : "bg-sky-600 text-white"}`}>
          {done ? "✓" : leg.status === "waiting" ? "…" : "→"}
        </span>
        <b className="text-slate-900">{leg.label}</b>
        {leg.verifies && <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-bold uppercase text-emerald-800">verifies recovery</span>}
        {!done && leg.level > 0 && <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ring-1 ring-inset ${LEVEL_STYLE[leg.level]}`}>{LEVEL_LABEL[leg.level]}</span>}
        <span className="ml-auto text-xs text-slate-500">{LEG_STATUS[leg.status]}</span>
      </div>
      <p className="mt-1 pl-8 text-sm text-slate-700">
        {leg.facility_name}
        {!leg.network_ok && <span className="text-amber-700"> · out of network</span>}
      </p>
      <p className="pl-8 text-xs text-slate-500">
        {done
          ? `${leg.result || "Done"} · ${when(leg.done_at)}`
          : leg.due_at
            ? `${late ? "Overdue" : "Due"} ${ago(leg.due_at)}${leg.requested_at ? ` · requested ${ago(leg.requested_at)}` : ""}`
            : leg.status === "waiting"
              ? "Starts when the earlier step is done"
              : leg.level >= 3
                ? "With the care coordinator"
                : ""}
      </p>
      {leg.actions.length > 0 && (
        <ol className="mt-2 space-y-0.5 border-l-2 border-slate-200 pl-3 ml-8 text-xs text-slate-600">
          {leg.actions.map((a, i) => (
            <li key={i}>
              <span className="text-slate-400">{when(a.at)}</span> · {a.text}
            </li>
          ))}
        </ol>
      )}
      {!done && !closed && leg.status !== "waiting" && (
        <div className="mt-2 flex flex-wrap gap-2 pl-8">
          {leg.status === "requested" && (
            <Button className="px-2 py-1 text-xs" disabled={busy} onClick={() => act(() => post(`/api/cases/${caseId}/legs/${leg.id}`, { action: "accept" }))}>
              Provider accepted
            </Button>
          )}
          <Button
            className="px-2 py-1 text-xs"
            variant="primary"
            disabled={busy}
            onClick={() => {
              const r = window.prompt(leg.kind === "report" ? "Report received: what does it say?" : leg.kind === "visit" ? "Visit done: outcome?" : "Result received:");
              if (r === null) return;
              const normal = leg.kind === "result" ? window.confirm("Is the result normal / resolved? (OK = yes, Cancel = no)") : null;
              act(() => post(`/api/cases/${caseId}/legs/${leg.id}`, { action: "done", result: r, normal }));
            }}
          >
            {leg.kind === "report" ? "Report received" : leg.kind === "visit" ? "Visit done" : "Result received"}
          </Button>
          {link && (
            <a href={link} target="_blank" rel="noreferrer" className="rounded-lg px-2 py-1 text-xs font-medium text-teal-800 ring-1 ring-inset ring-teal-200 hover:bg-teal-50">
              Provider page ↗
            </a>
          )}
        </div>
      )}
    </li>
  );
}

/** Care plan, the providers it depends on, and recovery check-ins. */
export function AftercarePanel({ c, busy, act, closed }: { c: Case; busy: boolean; act: Act; closed: boolean }) {
  const cp = c.care_plan!;
  const legs = c.legs ?? [];
  const cks = c.checkins ?? [];
  return (
    <Card className="p-5 text-sm">
      {c.provider_alert && !closed && (
        <div className="mb-4 flex gap-3 rounded-xl bg-red-600 p-3.5 text-white shadow">
          <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-white text-sm font-bold text-red-600">!</span>
          <div>
            <div className="font-semibold">Provider delay escalated to you {ago(c.provider_alert.at)}</div>
            <div className="text-sm text-red-50">{c.provider_alert.reason}</div>
          </div>
        </div>
      )}
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-base font-semibold text-slate-900">Care plan</h2>
        <span className="text-xs text-slate-500">
          by {cp.by} · {when(cp.at)}
        </span>
      </div>
      <p className="mt-1 text-slate-800">{cp.outcome}</p>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <div className="rounded-lg bg-slate-50 p-3">
          <div className="mb-1 text-xs font-semibold uppercase text-slate-500">Patient instructions</div>
          <ul className="list-disc space-y-0.5 pl-4 text-slate-700">
            {cp.instructions.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </div>
        <div className="rounded-lg bg-rose-50 p-3">
          <div className="mb-1 text-xs font-semibold uppercase text-rose-700">Warning signs</div>
          <ul className="list-disc space-y-0.5 pl-4 text-rose-900">
            {cp.warning_signs.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </div>
      </div>

      <h3 className="mb-2 mt-5 flex items-center gap-2 font-semibold text-slate-900">
        Providers
        <span className="text-xs font-normal text-slate-500">deadline missed → chase → re-route in network → coordinator</span>
      </h3>
      <ul className="space-y-2">
        {legs.map((l) => (
          <LegRow key={l.id} leg={l} caseId={c.id} busy={busy} act={act} closed={closed} />
        ))}
      </ul>

      <h3 className="mb-2 mt-5 font-semibold text-slate-900">Recovery check-ins</h3>
      <ul className="grid gap-2 sm:grid-cols-2">
        {cks.map((k) => (
          <li key={k.id} className={`rounded-lg p-3 ring-1 ring-inset ${k.concern ? "bg-red-50 ring-red-200" : k.status === "done" ? "bg-emerald-50/60 ring-emerald-200" : "ring-slate-200"}`}>
            <div className="flex justify-between text-xs text-slate-500">
              <span>{k.day ? `Day ${k.day}` : "Extra check-in"}</span>
              <span>{k.status === "done" ? `${k.channel === "voice" ? "📞 call" : "WhatsApp"} · ${when(k.done_at)}` : k.status === "sent" ? "Sent, awaiting reply" : k.status === "cancelled" ? "Not needed: loop closed" : `Due ${ago(k.due_at)}`}</span>
            </div>
            {k.answers && (
              <p className="mt-1 text-slate-800">
                Feeling <b>{k.answers.feeling}</b>
                {k.answers.following_plan !== null && <> · {k.answers.following_plan ? "following the plan" : "not following the plan"}</>}
                {k.answers.warning_signs ? <span className="font-semibold text-red-700"> · ⚠ {k.answers.warning_signs}</span> : " · no warning signs"}
              </p>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}

/** What proves the loop closed. Completed is refused until it is all in. */
export function EvidencePanel({ c, ev, busy, act }: { c: Case; ev: Evidence; busy: boolean; act: Act }) {
  const closed = c.status.startsWith("closed_");
  const [note, setNote] = useState("");
  async function download() {
    const r = await fetch(`${getApiBase()}/fhir/Bundle/${c.id}/evidence`, { headers: { Authorization: `Bearer ${getToken()}`, "ngrok-skip-browser-warning": "1" } });
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${c.id}-evidence.fhir.json`;
    a.click();
  }
  const done = ev.items.filter((i) => i.ok).length;
  return (
    <Card className={`p-5 text-sm ${ev.complete ? "border-emerald-300 ring-2 ring-emerald-100" : ""}`}>
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold text-slate-900">Clinical evidence</h2>
        <span className={`rounded-full px-2.5 py-0.5 text-xs font-bold ${ev.complete ? "bg-emerald-600 text-white" : "bg-slate-100 text-slate-600"}`}>
          {ev.complete ? "Loop closed with evidence" : `${done}/${ev.items.length}`}
        </span>
      </div>
      <ol className="mt-3 space-y-2">
        {ev.items.map((i) => (
          <li key={i.key} className="flex gap-2.5">
            <span className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full text-[11px] font-bold ${i.ok ? "bg-emerald-600 text-white" : i.required ? "bg-white text-slate-400 ring-1 ring-slate-300" : "bg-slate-100 text-slate-400"}`}>
              {i.ok ? "✓" : ""}
            </span>
            <span className="min-w-0">
              <span className={`block font-medium ${i.ok ? "text-slate-900" : "text-slate-500"}`}>
                {i.label}
                {!i.required && <span className="font-normal text-slate-400"> (optional)</span>}
              </span>
              {(i.detail || i.at) && (
                <span className="block truncate text-xs text-slate-500" title={i.detail}>
                  {i.detail}
                  {i.at && i.ok ? ` · ${when(i.at)}` : ""}
                </span>
              )}
            </span>
          </li>
        ))}
      </ol>
      <div className="mt-4 flex flex-wrap gap-2 border-t border-slate-100 pt-4">
        <Button onClick={download}>⬇ FHIR evidence bundle</Button>
      </div>
      {!closed && c.status === "follow_up" && (
        <div className="mt-3 rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200">
          {ev.ready_to_close ? (
            <>
              <p className="mb-2 font-medium text-slate-800">All evidence is in. Clinician sign-off closes the loop.</p>
              <input className={inputCls} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Sign-off note, e.g. Treated, test of cure negative, routine recall" />
              <Button
                variant="primary"
                className="mt-2 w-full"
                disabled={busy || !isClinician()}
                title={isClinician() ? "" : "A clinician signs off"}
                onClick={() => act(() => post(`/api/cases/${c.id}/status`, { status: "closed_completed", note: note || "Loop closed with evidence" }))}
              >
                ✓ Sign off and close
              </Button>
            </>
          ) : (
            <p className="text-slate-600">
              <b>Cannot close yet.</b> Missing: {ev.missing.join("; ")}.
            </p>
          )}
        </div>
      )}
    </Card>
  );
}
