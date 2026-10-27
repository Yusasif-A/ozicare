"use client";

import { useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { Card } from "@/components/ui";
import { api } from "@/lib/api";
import { STATUS_LABEL } from "@/lib/format";

type Metrics = {
  total_cases: number;
  time_to_first_contact_min: { median: number | null; avg: number | null };
  acknowledgement_rate: number | null;
  booking_rate: number | null;
  closure_rate: number | null;
  closed_by_reason: Record<string, number>;
  open_overdue: number;
  urgent_open: number;
  by_status: Record<string, number>;
};

const REASON_LABEL: Record<string, string> = {
  completed: "Completed",
  declined: "Declined",
  lost_to_follow_up: "Lost to follow-up",
  transferred: "Transferred",
};

function fmtMinutes(m: number | null) {
  if (m === null) return "—";
  if (m < 1) return `${Math.round(m * 60)}s`;
  if (m < 60) return `${m.toFixed(1)}m`;
  return `${(m / 60).toFixed(1)}h`;
}

function Kpi({ label, value, sub, tone = "default" }: { label: string; value: string; sub?: string; tone?: "default" | "alert" }) {
  return (
    <Card className={`p-5 ${tone === "alert" ? "border-red-200 bg-red-50" : ""}`}>
      <div className={`text-sm font-medium ${tone === "alert" ? "text-red-700" : "text-slate-500"}`}>{label}</div>
      <div className={`mt-2 text-3xl font-semibold tabular-nums ${tone === "alert" ? "text-red-700" : "text-slate-900"}`}>{value}</div>
      {sub && <div className="mt-1 text-xs text-slate-500">{sub}</div>}
    </Card>
  );
}

function Bars({ data, labels }: { data: Record<string, number>; labels: Record<string, string> }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...entries.map(([, v]) => v));
  if (!entries.length) return <p className="text-sm text-slate-400">No data yet.</p>;
  return (
    <div className="space-y-2.5">
      {entries.map(([k, v]) => (
        <div key={k} className="grid grid-cols-[160px_1fr_40px] items-center gap-3 text-sm">
          <span className="truncate text-slate-600">{labels[k] ?? k}</span>
          <div className="h-2.5 rounded-full bg-slate-100">
            <div className="h-2.5 rounded-full bg-teal-600" style={{ width: `${(v / max) * 100}%` }} />
          </div>
          <span className="text-right font-medium tabular-nums text-slate-800">{v}</span>
        </div>
      ))}
    </div>
  );
}

const pct = (v: number | null) => (v === null ? "—" : `${v}%`);

export default function MetricsPage() {
  const [m, setM] = useState<Metrics | null>(null);

  useEffect(() => {
    const load = () => api<Metrics>("/api/metrics").then(setM).catch(() => {});
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  return (
    <Shell>
      <h1 className="mb-5 text-xl font-semibold text-slate-900">Loop metrics</h1>
      {m && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Kpi label="Time to first contact" value={fmtMinutes(m.time_to_first_contact_min.median)} sub={`median · avg ${fmtMinutes(m.time_to_first_contact_min.avg)}`} />
            <Kpi label="Acknowledgement rate" value={pct(m.acknowledgement_rate)} sub="of contacted patients" />
            <Kpi label="Booking rate" value={pct(m.booking_rate)} sub="of contacted patients" />
            <Kpi label="Closure rate" value={pct(m.closure_rate)} sub={`of ${m.total_cases} cases`} />
          </div>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <Kpi label="Open & overdue" value={String(m.open_overdue)} tone={m.open_overdue ? "alert" : "default"} sub="SLA broken, still open" />
            <Kpi label="Urgent & open" value={String(m.urgent_open)} tone={m.urgent_open ? "alert" : "default"} />
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <Card className="p-5">
              <h2 className="mb-4 font-semibold text-slate-900">Cases by status</h2>
              <Bars data={m.by_status} labels={STATUS_LABEL} />
            </Card>
            <Card className="p-5">
              <h2 className="mb-4 font-semibold text-slate-900">Closed by reason</h2>
              <Bars data={m.closed_by_reason} labels={REASON_LABEL} />
            </Card>
          </div>
        </>
      )}
    </Shell>
  );
}
