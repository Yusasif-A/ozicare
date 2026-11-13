"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { OverduePill, RiskPill, StatusPill, UrgencyPill } from "@/components/ui";
import { api, type Case } from "@/lib/api";
import { PATHWAY_LABEL, REGION_LABEL, ago, apptLabel, isClosed, maskPhone } from "@/lib/format";

const FILTERS = [
  { key: "open", label: "All open", query: "open=true" },
  { key: "urgent", label: "Urgent", query: "open=true&urgency=urgent" },
  { key: "overdue", label: "Overdue", query: "open=true&overdue=true" },
  { key: "escalated", label: "Escalated", query: "status=escalated" },
  { key: "risk", label: "At risk", query: "open=true" },
  { key: "mine", label: "Mine", query: "open=true&mine=true" },
  { key: "closed", label: "Closed", query: "status=closed_completed,closed_declined,closed_lost,closed_transferred" },
  { key: "all", label: "Everything", query: "" },
];

// One colour per care pathway, used for the row marker and the pathway chip.
const PATHWAY_TONE: Record<string, string> = {
  hypertension: "bg-rose-50 text-rose-700 ring-rose-200",
  diabetes: "bg-amber-50 text-amber-800 ring-amber-200",
  obesity: "bg-orange-50 text-orange-700 ring-orange-200",
  cervical: "bg-fuchsia-50 text-fuchsia-700 ring-fuchsia-200",
  colorectal: "bg-violet-50 text-violet-700 ring-violet-200",
  breast: "bg-pink-50 text-pink-700 ring-pink-200",
  general: "bg-slate-100 text-slate-600 ring-slate-200",
};

// The loop, left to right, for the pipeline strip.
const STAGES = [
  { key: "new", label: "New result" },
  { key: "contacted", label: "Contacted" },
  { key: "acknowledged", label: "Engaged" },
  { key: "booked", label: "Booked" },
  { key: "in_care", label: "Attended" },
  { key: "closed_completed", label: "Completed" },
];

export default function Board() {
  const [filter, setFilter] = useState("open");
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<Case[] | null>(null);
  const [all, setAll] = useState<Case[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const f = FILTERS.find((x) => x.key === filter)!;
    const params = [f.query, q ? `q=${encodeURIComponent(q)}` : ""].filter(Boolean).join("&");
    try {
      const [list, everything] = await Promise.all([api<Case[]>(`/api/cases${params ? `?${params}` : ""}`), api<Case[]>(`/api/cases`)]);
      setRows(filter === "risk" ? list.filter((c) => c.loss_risk?.level === "high" || c.loss_risk?.level === "medium").sort((a, b) => b.loss_risk.score - a.loss_risk.score) : list);
      setAll(everything);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load cases");
    }
  }, [filter, q]);

  useEffect(() => {
    load();
    // Live board for the demo: patient replies move cases without a refresh.
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [load]);

  const open = all.filter((c) => !isClosed(c.status));
  const alerts = open.filter((c) => c.status === "escalated");
  const count = (fn: (c: Case) => boolean) => all.filter(fn).length;
  const stage = Object.fromEntries(STAGES.map((s) => [s.key, count((c) => c.status === s.key)]));
  const kpis = [
    { label: "Open results", value: open.length, sub: `${count((c) => c.urgency === "urgent" && !isClosed(c.status))} urgent` },
    { label: "Needs attention", value: count((c) => !isClosed(c.status) && (c.overdue || c.status === "escalated")), sub: "overdue or escalated", tone: "alert" },
    { label: "At risk of loss", value: open.filter((c) => c.loss_risk?.level === "high" || c.loss_risk?.level === "medium").length, sub: "flagged for outreach", tone: "warn" },
    { label: "Booked & attending", value: count((c) => c.status === "booked" || c.status === "in_care"), sub: "appointment in place" },
    { label: "Loop closed", value: count((c) => c.status === "closed_completed"), sub: `of ${all.length} results`, tone: "ok" },
  ];

  return (
    <Shell>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight text-slate-900">Case board</h1>
          <p className="mt-1 text-sm text-slate-500">Every actionable screening result, its owner, its deadline and where it is in the loop.</p>
        </div>
        <Link href="/cases/new" className="rounded-lg bg-teal-700 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-teal-800">
          + New result
        </Link>
      </div>

      {alerts.length > 0 && (
        <div className="mb-5 space-y-2">
          {alerts.map((c) => (
            <Link
              key={c.id}
              href={`/case?id=${c.id}`}
              className="flex items-center gap-3 rounded-xl border border-red-200 bg-gradient-to-r from-red-50 to-white px-4 py-3 text-sm text-red-900 shadow-sm hover:from-red-100"
            >
              <span className="grid h-8 w-8 shrink-0 animate-pulse place-items-center rounded-full bg-red-600 text-xs font-bold text-white">!</span>
              <span className="font-bold">Escalated · {c.patient_name}</span>
              <span className="truncate text-red-800">{c.escalation?.reason}</span>
              <span className="ml-auto shrink-0 text-xs font-semibold text-red-700">
                {c.owner_name ? `→ ${c.owner_name}` : "unassigned"} · {ago(c.escalation?.at)}
              </span>
            </Link>
          ))}
        </div>
      )}

      <div className="mb-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        {kpis.map((k) => (
          <div
            key={k.label}
            className={`rounded-2xl border bg-white p-5 shadow-sm ${
              k.tone === "alert" && k.value ? "border-red-200" : k.tone === "warn" && k.value ? "border-amber-200" : k.tone === "ok" ? "border-emerald-200" : "border-slate-200"
            }`}
          >
            <div className="text-xs font-semibold text-slate-500">{k.label}</div>
            <div className={`mt-2 text-3xl font-extrabold tabular-nums ${k.tone === "alert" && k.value ? "text-red-600" : k.tone === "warn" && k.value ? "text-amber-600" : k.tone === "ok" ? "text-emerald-600" : "text-slate-900"}`}>
              {k.value}
            </div>
            <div className="mt-1 text-xs text-slate-400">{k.sub}</div>
          </div>
        ))}
      </div>

      <div className="mb-6 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="mb-3 text-xs font-bold uppercase tracking-wide text-slate-400">The loop right now</div>
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
          {STAGES.map((s, i) => (
            <div key={s.key} className="relative">
              <div className={`rounded-xl px-3 py-3 ${i === STAGES.length - 1 ? "bg-emerald-50" : "bg-teal-50/60"}`}>
                <div className={`text-2xl font-extrabold tabular-nums ${i === STAGES.length - 1 ? "text-emerald-700" : "text-teal-900"}`}>{stage[s.key] ?? 0}</div>
                <div className="text-xs font-semibold text-slate-600">{s.label}</div>
              </div>
              {i < STAGES.length - 1 && <span className="absolute -right-2 top-1/2 z-10 hidden -translate-y-1/2 text-slate-300 sm:block">›</span>}
            </div>
          ))}
        </div>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="flex flex-wrap gap-1 rounded-xl border border-slate-200 bg-slate-100/70 p-1">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={`rounded-lg px-3 py-1.5 text-sm font-semibold transition ${filter === f.key ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-800"}`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search name, phone or case id"
          className="ml-auto w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-teal-600 focus:ring-4 focus:ring-teal-50 sm:w-72"
        />
      </div>

      {error && <p className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-left text-sm">
            <thead className="border-b border-slate-200 text-[11px] uppercase tracking-wider text-slate-400">
              <tr>
                <th className="px-5 py-3 font-bold">Patient</th>
                <th className="px-5 py-3 font-bold">Pathway & referral</th>
                <th className="px-5 py-3 font-bold">Urgency</th>
                <th className="px-5 py-3 font-bold">Status</th>
                <th className="px-5 py-3 font-bold">Owner</th>
                <th className="px-5 py-3 font-bold">Next step</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows?.map((c) => {
                const loud = !isClosed(c.status) && (c.overdue || c.urgency === "urgent" || c.status === "escalated");
                const pw = c.pathway ?? "general";
                return (
                  <tr key={c.id} className="group transition hover:bg-teal-50/40">
                    <td className={`border-l-4 px-5 py-3.5 ${loud ? "border-l-red-500" : "border-l-transparent"}`}>
                      <Link href={`/case?id=${c.id}`} className="flex items-center gap-3">
                        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-slate-100 text-xs font-bold text-slate-600">
                          {c.patient_name
                            .split(" ")
                            .slice(0, 2)
                            .map((w) => w[0])
                            .join("")}
                        </span>
                        <span className="min-w-0">
                          <span className="flex items-center gap-2">
                            <span className="truncate font-semibold text-slate-900 group-hover:text-teal-800">{c.patient_name}</span>
                            <span className="rounded bg-slate-100 px-1.5 text-[10px] font-bold uppercase text-slate-500">{c.language}</span>
                          </span>
                          <span className="block text-xs text-slate-400">
                            {REGION_LABEL[c.region ?? ""] ?? "Abu Dhabi"} · {maskPhone(c.phone)} · {ago(c.created_at)}
                          </span>
                        </span>
                      </Link>
                    </td>
                    <td className="px-5 py-3.5">
                      <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ${PATHWAY_TONE[pw]}`}>{PATHWAY_LABEL[pw] ?? pw}</span>
                      {c.referral && <div className="mt-1 max-w-[260px] truncate text-xs text-slate-500">→ {c.referral.service_label}</div>}
                    </td>
                    <td className="px-5 py-3.5">
                      <UrgencyPill urgency={c.urgency} />
                    </td>
                    <td className="px-5 py-3.5">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <StatusPill status={c.status} />
                        {c.overdue && !isClosed(c.status) && <OverduePill />}
                        {!isClosed(c.status) && <RiskPill risk={c.loss_risk} />}
                        {c.callback_requested_at && !isClosed(c.status) && (
                          <span className="rounded-full bg-violet-50 px-2 py-0.5 text-xs font-medium text-violet-700 ring-1 ring-inset ring-violet-200">Call requested</span>
                        )}
                      </div>
                    </td>
                    <td className="px-5 py-3.5 text-slate-700">{c.owner_name ?? <span className="font-semibold text-red-600">Unassigned</span>}</td>
                    <td className="px-5 py-3.5 text-slate-600">
                      {c.appointment ? (
                        <span className="font-medium text-teal-800">📅 {apptLabel(c.appointment)}</span>
                      ) : isClosed(c.status) ? (
                        <span className="text-slate-400">{c.closed_reason?.replaceAll("_", " ")}</span>
                      ) : (
                        <span className={c.overdue ? "font-semibold text-red-600" : ""}>{c.sla_due_at ? `Due ${ago(c.sla_due_at)}` : "—"}</span>
                      )}
                    </td>
                  </tr>
                );
              })}
              {rows?.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-5 py-16 text-center text-slate-500">
                    No cases match this view.
                  </td>
                </tr>
              )}
              {rows === null && (
                <tr>
                  <td colSpan={6} className="px-5 py-16 text-center text-slate-400">
                    Loading…
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </Shell>
  );
}
