"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { api, post } from "@/lib/api";
import { LEG_STATUS, ago, when } from "@/lib/format";

type View = {
  case_id: string;
  patient: string;
  urgency: string;
  reason: string;
  care_plan: string;
  referred_by: string;
  label: string;
  kind: "report" | "visit" | "result";
  status: string;
  level: number;
  facility_name: string;
  result: string;
  normal: boolean | null;
  requested_at: string | null;
  due_at: string | null;
  actions: { at: string; text: string }[];
};

export default function ProviderPage() {
  return (
    <Suspense fallback={null}>
      <ProviderView />
    </Suspense>
  );
}

/** The referral desk's page: one provider step, opened from the WhatsApp link. No login. */
function ProviderView() {
  const token = useSearchParams().get("t") ?? "";
  const [v, setV] = useState<View | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [normal, setNormal] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api<View>(`/api/provider/${token}`)
      .then(setV)
      .catch((e) => setErr(e instanceof Error ? e.message : "Link not recognised"));
  }, [token]);
  useEffect(load, [load]);

  async function send(action: "accept" | "done") {
    setBusy(true);
    setErr(null);
    try {
      setV(await post<View>(`/api/provider/${token}`, { action, result: text, normal: v?.kind === "result" ? normal : null }));
      setText("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not save");
    } finally {
      setBusy(false);
    }
  }

  const done = v?.status === "done";
  const late = v?.due_at && !done && new Date(v.due_at).getTime() < Date.now();
  const doneLabel = v?.kind === "report" ? "Send report" : v?.kind === "visit" ? "Mark visit done" : "Send result";

  return (
    <div className="min-h-screen bg-[#f6f7f5] px-4 py-8">
      <div className="mx-auto max-w-lg">
        <div className="mb-6 flex items-center gap-2.5">
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-teal-600 to-teal-800 text-sm font-extrabold text-white">OC</span>
          <span>
            <span className="block font-extrabold text-slate-900">OziCare</span>
            <span className="block text-xs text-slate-500">Referral desk</span>
          </span>
        </div>
        {err && !v && <p className="rounded-xl bg-red-50 p-4 text-sm text-red-700">{err}</p>}
        {v && (
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">{v.facility_name}</div>
            <h1 className="mt-1 text-xl font-extrabold text-slate-900">{v.label}</h1>
            <div className="mt-2 flex flex-wrap gap-2 text-xs">
              <span className="rounded-full bg-slate-100 px-2.5 py-0.5 font-semibold text-slate-700">Patient {v.patient}</span>
              <span className="rounded-full bg-slate-100 px-2.5 py-0.5 font-semibold text-slate-700">Case {v.case_id}</span>
              <span className={`rounded-full px-2.5 py-0.5 font-bold uppercase ${v.urgency === "urgent" ? "bg-red-600 text-white" : v.urgency === "soon" ? "bg-amber-100 text-amber-800" : "bg-slate-100 text-slate-600"}`}>{v.urgency}</span>
              <span className={`rounded-full px-2.5 py-0.5 font-semibold ${done ? "bg-emerald-100 text-emerald-800" : late ? "bg-red-50 text-red-700" : "bg-sky-50 text-sky-700"}`}>
                {done ? "Done" : late ? `Overdue ${ago(v.due_at)}` : LEG_STATUS[v.status]}
              </span>
            </div>
            <dl className="mt-4 space-y-2 text-sm">
              <div>
                <dt className="text-xs font-semibold uppercase text-slate-400">Screening finding</dt>
                <dd className="text-slate-800">{v.reason}</dd>
              </div>
              {v.care_plan && (
                <div>
                  <dt className="text-xs font-semibold uppercase text-slate-400">Care plan ({v.referred_by})</dt>
                  <dd className="text-slate-800">{v.care_plan}</dd>
                </div>
              )}
              {v.requested_at && (
                <div>
                  <dt className="text-xs font-semibold uppercase text-slate-400">Requested</dt>
                  <dd className="text-slate-800">{when(v.requested_at)}</dd>
                </div>
              )}
            </dl>

            {done ? (
              <div className="mt-5 rounded-xl bg-emerald-50 p-4 text-sm text-emerald-900">
                <b>Thank you.</b> Recorded{v.result ? `: ${v.result}` : ""}. The patient&apos;s care team can see it now.
              </div>
            ) : v.status === "waiting" ? (
              <p className="mt-5 rounded-xl bg-slate-50 p-4 text-sm text-slate-600">This step starts when the earlier step is complete.</p>
            ) : (
              <div className="mt-5 space-y-3">
                {v.status === "requested" && (
                  <button disabled={busy} onClick={() => send("accept")} className="w-full rounded-xl bg-white px-4 py-3 text-sm font-bold text-teal-800 ring-1 ring-inset ring-teal-300 hover:bg-teal-50 disabled:opacity-50">
                    ✓ Accept referral
                  </button>
                )}
                <textarea
                  className="w-full rounded-xl border-0 px-3 py-2.5 text-sm ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-teal-600"
                  rows={3}
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder={v.kind === "report" ? "Report summary, e.g. CIN2 on biopsy: treatment advised" : v.kind === "visit" ? "Outcome of the visit" : "Result"}
                />
                {v.kind === "result" && (
                  <div className="flex gap-2 text-sm">
                    {[true, false].map((n) => (
                      <button key={String(n)} onClick={() => setNormal(n)} className={`flex-1 rounded-lg px-3 py-2 font-semibold ring-1 ring-inset ${normal === n ? "bg-teal-700 text-white ring-teal-700" : "ring-slate-300"}`}>
                        {n ? "Normal / resolved" : "Not resolved"}
                      </button>
                    ))}
                  </div>
                )}
                <button
                  disabled={busy || !text.trim() || (v.kind === "result" && normal === null)}
                  onClick={() => send("done")}
                  className="w-full rounded-xl bg-teal-700 px-4 py-3 text-sm font-bold text-white shadow hover:bg-teal-800 disabled:opacity-50"
                >
                  {doneLabel}
                </button>
              </div>
            )}
            {err && <p className="mt-3 text-sm text-red-700">{err}</p>}
            {v.actions.length > 0 && (
              <ol className="mt-5 space-y-1 border-t border-slate-100 pt-4 text-xs text-slate-500">
                {v.actions.map((a, i) => (
                  <li key={i}>
                    {when(a.at)} · {a.text}
                  </li>
                ))}
              </ol>
            )}
          </div>
        )}
        <p className="mt-6 text-center text-xs text-slate-400">In a full deployment this is a FHIR Task update in the facility&apos;s own system.</p>
      </div>
    </div>
  );
}
