"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { Card, ErrorNote, UrgencyPill } from "@/components/ui";
import { api, type ProviderRow } from "@/lib/api";
import { LEG_STATUS, LEVEL_LABEL, LEVEL_STYLE, ago, when } from "@/lib/format";

type Data = { rows: ProviderRow[]; counts: { open: number; chased: number; rerouted: number; escalated: number; blocked: number } };

function waited(h: number): string {
  if (!h) return "—";
  return h < 48 ? `${Math.round(h)}h` : `${Math.round(h / 24)} days`;
}

/** Every provider a care plan depends on, across all patients: who is late, and what OziCare did about it. */
export default function Providers() {
  const [d, setD] = useState<Data | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [show, setShow] = useState<"open" | "delayed" | "all">("open");

  useEffect(() => {
    const load = () =>
      api<Data>("/api/providers")
        .then(setD)
        .catch((e) => setErr(e instanceof Error ? e.message : "Could not load"));
    load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, []);

  const rows = (d?.rows ?? []).filter((r) => (show === "all" ? true : show === "open" ? r.status !== "done" : r.status !== "done" && (r.level > 0 || r.overdue || r.blocked_by)));
  const k = d?.counts;

  return (
    <Shell>
      <div className="mb-6">
        <h1 className="text-2xl font-extrabold text-slate-900">Referral monitor</h1>
        <p className="mt-1 text-sm text-slate-500">
          Every lab, clinic and test a patient&apos;s care depends on. When a provider misses its deadline OziCare acts on its own: it chases the provider, then re-routes to the next
          in-network provider and tells the patient, then hands it to the care coordinator.
        </p>
      </div>

      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-5">
        {[
          { label: "Open provider steps", value: k?.open, tone: "text-slate-900" },
          { label: "Chased automatically", value: k?.chased, tone: "text-amber-700" },
          { label: "Re-routed", value: k?.rerouted, tone: "text-violet-700" },
          { label: "With coordinator", value: k?.escalated, tone: "text-red-600" },
          { label: "Blocked by a late step", value: k?.blocked, tone: "text-orange-600" },
        ].map((x) => (
          <Card key={x.label} className="p-4">
            <div className={`text-3xl font-extrabold tabular-nums ${x.tone}`}>{x.value ?? "–"}</div>
            <div className="text-xs font-semibold text-slate-500">{x.label}</div>
          </Card>
        ))}
      </div>

      <div className="mb-3 flex gap-1 rounded-xl border border-slate-200 bg-slate-100/70 p-1 text-sm sm:w-fit">
        {(["open", "delayed", "all"] as const).map((s) => (
          <button key={s} onClick={() => setShow(s)} className={`rounded-lg px-3 py-1.5 font-semibold capitalize ${show === s ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"}`}>
            {s === "delayed" ? "Delayed only" : s}
          </button>
        ))}
      </div>
      <ErrorNote text={err} />

      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-sm">
            <thead className="bg-slate-50 text-left text-xs font-semibold uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">Patient</th>
                <th className="px-4 py-3">Provider step</th>
                <th className="px-4 py-3">Waiting</th>
                <th className="px-4 py-3">Escalation</th>
                <th className="px-4 py-3">What OziCare did</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((r) => {
                const last = r.actions[r.actions.length - 1];
                return (
                  <tr key={r.id} className={r.level >= 3 && r.status !== "done" ? "bg-red-50/60" : r.status === "done" ? "opacity-60" : ""}>
                    <td className="px-4 py-3 align-top">
                      <Link href={`/case?id=${r.case_id}`} className="font-semibold text-slate-900 hover:text-teal-700">
                        {r.patient_name}
                      </Link>
                      <div className="mt-1 flex items-center gap-1.5 text-xs text-slate-500">
                        <UrgencyPill urgency={r.urgency} /> {r.case_id}
                      </div>
                    </td>
                    <td className="px-4 py-3 align-top">
                      <div className="font-medium text-slate-900">{r.label}</div>
                      <div className="text-slate-600">{r.facility_name}</div>
                      <div className="text-xs text-slate-500">
                        {r.kind === "referral" ? "First referral, awaiting acceptance" : LEG_STATUS[r.status]}
                        {r.status === "done" && r.result ? `: ${r.result}` : ""}
                      </div>
                    </td>
                    <td className="px-4 py-3 align-top">
                      <div className={`font-semibold tabular-nums ${r.overdue ? "text-red-600" : "text-slate-800"}`}>{r.status === "waiting" ? "—" : waited(r.hours_waiting)}</div>
                      {r.due_at && <div className="text-xs text-slate-500">{r.overdue ? "overdue" : "due"} {ago(r.due_at)}</div>}
                      {r.blocked_by && <div className="mt-1 text-xs font-semibold text-orange-700">Blocked by {r.blocked_by}</div>}
                    </td>
                    <td className="px-4 py-3 align-top">
                      {r.status !== "done" && (
                        <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-bold ring-1 ring-inset ${LEVEL_STYLE[r.level] ?? LEVEL_STYLE[0]}`}>{LEVEL_LABEL[r.level] ?? "On track"}</span>
                      )}
                      {r.status !== "done" && (
                        <div className="mt-1.5 flex gap-1">
                          {[1, 2, 3].map((l) => (
                            <span key={l} className={`h-1.5 w-6 rounded-full ${r.level >= l ? (l === 3 ? "bg-red-500" : l === 2 ? "bg-violet-500" : "bg-amber-400") : "bg-slate-200"}`} />
                          ))}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 align-top text-xs text-slate-600">
                      {last ? (
                        <>
                          <div>{last.text}</div>
                          <div className="text-slate-400">{when(last.at)}</div>
                        </>
                      ) : (
                        <span className="text-slate-400">Nothing needed yet</span>
                      )}
                    </td>
                  </tr>
                );
              })}
              {d && rows.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-10 text-center text-slate-400">
                    Nothing here.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </Shell>
  );
}
