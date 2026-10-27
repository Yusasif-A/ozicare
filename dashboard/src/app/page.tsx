"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { Card, OverduePill, StatusPill, UrgencyPill } from "@/components/ui";
import { api, type Case } from "@/lib/api";
import { SCREENING_LABEL, ago, isClosed, maskPhone } from "@/lib/format";

const FILTERS = [
  { key: "open", label: "All open", query: "open=true" },
  { key: "urgent", label: "Urgent", query: "open=true&urgency=urgent" },
  { key: "overdue", label: "Overdue", query: "open=true&overdue=true" },
  { key: "escalated", label: "Escalated", query: "status=escalated" },
  { key: "mine", label: "Mine", query: "open=true&mine=true" },
  { key: "closed", label: "Closed", query: "status=closed_completed,closed_declined,closed_lost,closed_transferred" },
  { key: "all", label: "Everything", query: "" },
];

export default function Board() {
  const [filter, setFilter] = useState("open");
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<Case[] | null>(null);
  const [alerts, setAlerts] = useState<Case[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const f = FILTERS.find((x) => x.key === filter)!;
    const params = [f.query, q ? `q=${encodeURIComponent(q)}` : ""].filter(Boolean).join("&");
    try {
      const [list, esc] = await Promise.all([
        api<Case[]>(`/api/cases${params ? `?${params}` : ""}`),
        api<Case[]>(`/api/cases?status=escalated`),
      ]);
      setRows(list);
      setAlerts(esc.filter((c) => c.urgency === "urgent" || c.escalation?.reason?.toLowerCase().includes("emergency")));
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

  return (
    <Shell>
      {alerts.length > 0 && (
        <div className="mb-5 space-y-2">
          {alerts.map((c) => (
            <Link
              key={c.id}
              href={`/case?id=${c.id}`}
              className="flex items-center gap-3 rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-900 shadow-sm hover:bg-red-100"
            >
              <span className="grid h-7 w-7 shrink-0 animate-pulse place-items-center rounded-full bg-red-600 text-xs font-bold text-white">!</span>
              <span className="font-semibold">Urgent escalation · {c.patient_name}</span>
              <span className="truncate text-red-800">{c.escalation?.reason}</span>
              <span className="ml-auto shrink-0 text-red-700">
                {c.owner_name ? `→ ${c.owner_name}` : "unassigned"} · {ago(c.escalation?.at)}
              </span>
            </Link>
          ))}
        </div>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h1 className="mr-2 text-xl font-semibold text-slate-900">Case board</h1>
        <div className="flex flex-wrap gap-1 rounded-lg bg-white p-1 ring-1 ring-slate-200">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={`rounded-md px-3 py-1.5 text-sm font-medium ${filter === f.key ? "bg-teal-700 text-white" : "text-slate-600 hover:bg-slate-100"}`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search name, phone or case id"
          className="ml-auto w-64 rounded-lg border-0 px-3 py-2 text-sm ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-teal-600"
        />
        <Link href="/cases/new" className="rounded-lg bg-teal-700 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-teal-800">
          + New case
        </Link>
      </div>

      {error && <p className="mb-3 text-sm text-red-600">{error}</p>}

      <Card className="overflow-hidden">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3">Patient</th>
              <th className="px-4 py-3">Screening</th>
              <th className="px-4 py-3">Urgency</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Owner</th>
              <th className="px-4 py-3">Next step</th>
              <th className="px-4 py-3">Created</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows?.map((c) => {
              const loud = !isClosed(c.status) && (c.overdue || c.urgency === "urgent" || c.status === "escalated");
              return (
                <tr key={c.id} className={`group cursor-pointer ${loud ? "bg-red-50/40" : ""} hover:bg-teal-50/50`}>
                  <td className="px-4 py-3">
                    <Link href={`/case?id=${c.id}`} className="block">
                      <div className="flex items-center gap-2">
                        {loud && <span className="h-2 w-2 shrink-0 rounded-full bg-red-500" />}
                        <span className="font-medium text-slate-900 group-hover:text-teal-800">{c.patient_name}</span>
                        <span className="rounded bg-slate-100 px-1.5 text-[10px] font-semibold uppercase text-slate-500">{c.language}</span>
                      </div>
                      <div className="text-xs text-slate-500">
                        {c.id} · {maskPhone(c.phone)}
                      </div>
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-slate-700">{SCREENING_LABEL[c.screening_type] ?? c.screening_type}</td>
                  <td className="px-4 py-3">
                    <UrgencyPill urgency={c.urgency} />
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <StatusPill status={c.status} />
                      {c.overdue && !isClosed(c.status) && <OverduePill />}
                      {c.callback_requested_at && !isClosed(c.status) && (
                        <span className="rounded-full bg-violet-50 px-2 py-0.5 text-xs font-medium text-violet-700 ring-1 ring-inset ring-violet-200">Call requested</span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-slate-700">{c.owner_name ?? <span className="text-red-600">Unassigned</span>}</td>
                  <td className="px-4 py-3 text-slate-600">
                    {c.appointment ? (
                      <span className="text-teal-800">{c.appointment.label}</span>
                    ) : isClosed(c.status) ? (
                      <span className="text-slate-400">—</span>
                    ) : (
                      <span>{c.sla_due_at ? `SLA ${ago(c.sla_due_at)}` : "—"}</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-slate-500">{ago(c.created_at)}</td>
                </tr>
              );
            })}
            {rows?.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-12 text-center text-slate-500">
                  No cases here.{" "}
                  <Link href="/cases/new" className="font-medium text-teal-700 hover:underline">
                    Create one
                  </Link>
                </td>
              </tr>
            )}
            {rows === null && (
              <tr>
                <td colSpan={7} className="px-4 py-12 text-center text-slate-400">
                  Loading…
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>
    </Shell>
  );
}
