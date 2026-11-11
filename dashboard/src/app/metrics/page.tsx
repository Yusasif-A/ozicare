"use client";

import { useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { Card, RiskPill } from "@/components/ui";
import { api, type LossRisk } from "@/lib/api";
import Link from "next/link";
import { PATHWAY_LABEL, REGION_LABEL, STATUS_LABEL } from "@/lib/format";

type Metrics = {
  total_cases: number;
  referral_completion_rate: number | null;
  time_to_assessment_hours: { median: number | null; avg: number | null };
  treatment_completion_rate: number | null;
  loss_risk: { high: number; medium: number; low: number; top: ({ id: string; patient_name: string; urgency: string; status: string } & LossRisk)[] };
  time_to_first_contact_min: { median: number | null; avg: number | null };
  acknowledgement_rate: number | null;
  booking_rate: number | null;
  attendance_rate: number | null;
  no_shows: number;
  closure_rate: number | null;
  referrals: { sent: number; accepted: number; declined: number };
  closed_by_reason: Record<string, number>;
  open_overdue: number;
  urgent_open: number;
  by_status: Record<string, number>;
  by_pathway: Record<string, { cases: number; attended: number; completed: number; lost: number }>;
  by_region: Record<string, { cases: number; attended: number; open: number }>;
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

function fmtHours(h: number | null) {
  if (h === null) return "—";
  if (h < 1) return `${Math.round(h * 60)}m`;
  if (h < 48) return `${h.toFixed(1)}h`;
  return `${(h / 24).toFixed(1)}d`;
}

function Kpi({ label, value, sub, tone = "default", question }: { label: string; value: string; sub?: string; tone?: "default" | "alert" | "hero"; question?: string }) {
  const box = tone === "alert" ? "border-red-200 bg-red-50" : tone === "hero" ? "border-teal-200 bg-teal-50/60" : "";
  return (
    <Card className={`p-5 ${box}`}>
      <div className={`text-sm font-medium ${tone === "alert" ? "text-red-700" : tone === "hero" ? "text-teal-800" : "text-slate-500"}`}>{label}</div>
      {question && <div className="text-xs text-slate-500">{question}</div>}
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
      <h1 className="text-xl font-semibold text-slate-900">Loop metrics</h1>
      <p className="mb-5 text-sm text-slate-500">A measurable care loop: did every screened person receive the right intervention at the right time?</p>
      {m && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Kpi tone="hero" label="Referral completion" question="Did the person reach the recommended service?" value={pct(m.referral_completion_rate)} sub={`attended, of ${m.referrals.sent} referrals`} />
            <Kpi tone="hero" label="Time to assessment" question="How quickly did follow-up happen?" value={fmtHours(m.time_to_assessment_hours.median)} sub={`median, result → visit · avg ${fmtHours(m.time_to_assessment_hours.avg)}`} />
            <Kpi tone="hero" label="Treatment completion" question="Did the person complete the next care step?" value={pct(m.treatment_completion_rate)} sub="closed completed, of those who attended" />
            <Kpi
              tone={m.loss_risk.high ? "alert" : "hero"}
              label="Lost-to-follow-up risk"
              question="Who needs an outreach reminder or care-team alert?"
              value={String(m.loss_risk.high + m.loss_risk.medium)}
              sub={`${m.loss_risk.high} high · ${m.loss_risk.medium} medium`}
            />
          </div>

          <div className="mt-4 grid gap-4 sm:grid-cols-3 lg:grid-cols-6">
            <Kpi label="First contact" value={fmtMinutes(m.time_to_first_contact_min.median)} sub="median" />
            <Kpi label="Acknowledged" value={pct(m.acknowledgement_rate)} sub="of contacted" />
            <Kpi label="Booked" value={pct(m.booking_rate)} sub="of contacted" />
            <Kpi label="Attended" value={pct(m.attendance_rate)} sub={`of booked · ${m.no_shows} no-show${m.no_shows === 1 ? "" : "s"}`} />
            <Kpi label="Open & overdue" value={String(m.open_overdue)} tone={m.open_overdue ? "alert" : "default"} />
            <Kpi label="Urgent & open" value={String(m.urgent_open)} tone={m.urgent_open ? "alert" : "default"} />
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <Card className="p-5">
              <h2 className="mb-3 font-semibold text-slate-900">Needs outreach now</h2>
              {m.loss_risk.top.length === 0 && <p className="text-sm text-slate-400">Nobody at risk of being lost.</p>}
              <ul className="divide-y divide-slate-100">
                {m.loss_risk.top.map((r) => (
                  <li key={r.id} className="py-2">
                    <Link href={`/case?id=${r.id}`} className="flex items-center gap-2 text-sm hover:text-teal-800">
                      <span className="font-medium">{r.patient_name}</span>
                      <span className="text-xs text-slate-500">{STATUS_LABEL[r.status]}</span>
                      <span className="ml-auto">
                        <RiskPill risk={r} />
                      </span>
                    </Link>
                    <p className="text-xs text-slate-500">{r.reasons.join(" · ")}</p>
                  </li>
                ))}
              </ul>
            </Card>
            <Card className="p-5">
              <h2 className="mb-3 font-semibold text-slate-900">By care pathway</h2>
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase text-slate-500">
                  <tr>
                    <th className="pb-2">Pathway</th>
                    <th className="pb-2 text-right">Cases</th>
                    <th className="pb-2 text-right">Attended</th>
                    <th className="pb-2 text-right">Completed</th>
                    <th className="pb-2 text-right">Lost</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 tabular-nums">
                  {Object.entries(m.by_pathway).map(([k, v]) => (
                    <tr key={k}>
                      <td className="py-1.5">{PATHWAY_LABEL[k] ?? k}</td>
                      <td className="py-1.5 text-right">{v.cases}</td>
                      <td className="py-1.5 text-right">{v.attended}</td>
                      <td className="py-1.5 text-right">{v.completed}</td>
                      <td className={`py-1.5 text-right ${v.lost ? "text-red-600" : ""}`}>{v.lost}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <h2 className="mb-3 mt-5 font-semibold text-slate-900">By region</h2>
              <Bars data={Object.fromEntries(Object.entries(m.by_region).map(([k, v]) => [k, v.cases]))} labels={REGION_LABEL} />
            </Card>
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <Card className="p-5">
              <h2 className="mb-4 font-semibold text-slate-900">Cases by status</h2>
              <Bars data={m.by_status} labels={STATUS_LABEL} />
            </Card>
            <Card className="p-5">
              <h2 className="mb-4 font-semibold text-slate-900">Closed by reason</h2>
              <Bars data={m.closed_by_reason} labels={REASON_LABEL} />
              <p className="mt-4 text-xs text-slate-500">
                Referrals: {m.referrals.sent} sent · {m.referrals.accepted} accepted · {m.referrals.declined} declined
              </p>
            </Card>
          </div>
        </>
      )}
    </Shell>
  );
}
