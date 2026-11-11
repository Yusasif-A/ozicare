"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { Button, Card, ErrorNote, Field, UrgencyPill, inputCls } from "@/components/ui";
import { api, post, type Assessment, type Case, type Meta } from "@/lib/api";
import { PATHWAY_LABEL } from "@/lib/format";

const URGENCY_HELP: Record<string, string> = {
  routine: "Contact within hours; reminders over days.",
  soon: "Contact within the hour; reminders within a day.",
  urgent: "Contact now. If not acknowledged within minutes, auto-escalates to a clinician.",
};

// Grouped so the form reads like a screening record.
const READING_GROUPS: { title: string; keys: string[]; placeholder: Record<string, string> }[] = [
  { title: "Blood pressure", keys: ["systolic", "diastolic"], placeholder: { systolic: "168", diastolic: "102" } },
  { title: "Blood sugar", keys: ["hba1c", "fasting_glucose", "random_glucose"], placeholder: { hba1c: "7.2", fasting_glucose: "130", random_glucose: "" } },
  { title: "Weight", keys: ["bmi"], placeholder: { bmi: "32" } },
  { title: "Cancer screening", keys: ["cervical_cytology", "fit", "birads"], placeholder: { cervical_cytology: "HSIL", fit: "positive", birads: "4" } },
];

export default function NewCase() {
  const router = useRouter();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [form, setForm] = useState({
    display_name: "",
    phone: "",
    emirates_id: "",
    language: "en",
    region: "abu_dhabi",
    insurance: "Thiqa",
    screening_type: "",
    urgency: "",
    result_summary: "",
    source: "phc",
    location: "",
  });
  const [readings, setReadings] = useState<Record<string, string>>({});
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [manual, setManual] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [csvResult, setCsvResult] = useState<string | null>(null);

  useEffect(() => {
    api<Meta>("/api/meta").then(setMeta).catch(() => {});
  }, []);

  // Live preview of the agreed criteria as readings are typed.
  useEffect(() => {
    const filled = Object.fromEntries(Object.entries(readings).filter(([, v]) => v.trim()));
    if (!Object.keys(filled).length) {
      setAssessment(null);
      return;
    }
    const t = setTimeout(() => post<Assessment>("/api/assess", { readings: filled }).then(setAssessment).catch(() => {}), 250);
    return () => clearTimeout(t);
  }, [readings]);

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setForm({ ...form, [k]: e.target.value });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const filled = Object.fromEntries(Object.entries(readings).filter(([, v]) => v.trim()));
      const body = { ...form, readings: filled, screening_type: manual ? form.screening_type || "general_abnormal" : "", urgency: manual ? form.urgency || "soon" : form.urgency };
      const c = await post<Case>("/api/cases", body);
      router.push(`/case?id=${c.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create case");
      setBusy(false);
    }
  }

  async function upload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    try {
      const res = await api<{ created: string[]; errors: { line: number; error: string }[] }>("/api/cases/import", { method: "POST", body: fd });
      setCsvResult(
        `${res.created.length} case(s) created.` + (res.errors.length ? ` ${res.errors.length} row(s) rejected: ` + res.errors.map((x) => `line ${x.line}: ${x.error}`).join("; ") : ""),
      );
    } catch (err) {
      setCsvResult(err instanceof Error ? err.message : "Import failed");
    }
    e.target.value = "";
  }

  const noFinding = assessment && !assessment.actionable && !manual;
  const service = assessment?.pathway && meta ? referralPreview(meta, assessment, form.region, form.insurance) : null;

  return (
    <Shell>
      <div className="mx-auto grid max-w-6xl gap-6 lg:grid-cols-[1fr_340px]">
        <Card className="p-6">
          <h1 className="text-xl font-semibold text-slate-900">New screening result</h1>
          <p className="mt-1 text-sm text-slate-500">Enter the readings: the agreed criteria set the pathway, urgency and referral. The patient is messaged as soon as you save.</p>
          <form onSubmit={submit} className="mt-6 space-y-5">
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="Patient name">
                <input className={inputCls} value={form.display_name} onChange={set("display_name")} required placeholder="Mariam Al Mansoori" />
              </Field>
              <Field label="WhatsApp number" hint="International format">
                <input className={inputCls} value={form.phone} onChange={set("phone")} required placeholder="+971 50 000 0000" />
              </Field>
              <Field label="Emirates ID (optional)">
                <input className={inputCls} value={form.emirates_id} onChange={set("emirates_id")} placeholder="784-1985-1234567-1" />
              </Field>
            </div>
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="Region">
                <select className={inputCls} value={form.region} onChange={set("region")}>
                  {Object.entries(meta?.regions ?? { abu_dhabi: "Abu Dhabi" }).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Insurance">
                <select className={inputCls} value={form.insurance} onChange={set("insurance")}>
                  {(meta?.insurances ?? ["Thiqa"]).map((i) => (
                    <option key={i}>{i}</option>
                  ))}
                </select>
              </Field>
              <Field label="Patient language" hint="The patient can switch any time.">
                <select className={inputCls} value={form.language} onChange={set("language")}>
                  <option value="en">English</option>
                  <option value="ar">Arabic</option>
                </select>
              </Field>
            </div>

            <div className="rounded-xl bg-slate-50 p-4 ring-1 ring-slate-200">
              <h2 className="mb-3 text-sm font-semibold text-slate-800">Screening readings</h2>
              <div className="grid gap-4 sm:grid-cols-2">
                {READING_GROUPS.map((g) => (
                  <div key={g.title}>
                    <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-500">{g.title}</div>
                    <div className="grid grid-cols-2 gap-2">
                      {g.keys.map((k) => (
                        <label key={k} className="block">
                          <span className="mb-0.5 block text-xs text-slate-600">{meta?.readings[k] ?? k}</span>
                          <input className={inputCls} value={readings[k] ?? ""} onChange={(e) => setReadings({ ...readings, [k]: e.target.value })} placeholder={g.placeholder[k]} />
                        </label>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <label className="flex items-center gap-2 text-sm text-slate-600">
              <input type="checkbox" checked={manual} onChange={(e) => setManual(e.target.checked)} />
              No readings: set screening type and urgency by hand
            </label>
            {manual && (
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Screening type">
                  <select className={inputCls} value={form.screening_type || "general_abnormal"} onChange={set("screening_type")}>
                    {Object.entries(meta?.screening_types ?? { general_abnormal: "health screening" }).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v.charAt(0).toUpperCase() + v.slice(1)}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Urgency" hint={URGENCY_HELP[form.urgency || "soon"]}>
                  <div className="grid grid-cols-3 gap-2">
                    {["routine", "soon", "urgent"].map((u) => (
                      <button
                        type="button"
                        key={u}
                        onClick={() => setForm({ ...form, urgency: u })}
                        className={`rounded-lg px-3 py-2 text-sm font-semibold capitalize ring-1 ring-inset ${
                          (form.urgency || "soon") === u ? (u === "urgent" ? "bg-red-600 text-white ring-red-600" : u === "soon" ? "bg-amber-100 text-amber-900 ring-amber-400" : "bg-teal-700 text-white ring-teal-700") : "bg-white text-slate-600 ring-slate-300 hover:bg-slate-50"
                        }`}
                      >
                        {u}
                      </button>
                    ))}
                  </div>
                </Field>
              </div>
            )}

            <Field label="Note for the patient (optional)" hint="Plain language, approved for the patient to read. No raw lab values or diagnoses.">
              <textarea className={inputCls} rows={2} value={form.result_summary} onChange={set("result_summary")} placeholder="A repeat check is recommended within 2 weeks." />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Source">
                <select className={inputCls} value={form.source} onChange={set("source")}>
                  <option value="phc">Primary health centre</option>
                  <option value="lab">Lab</option>
                  <option value="camp">Screening camp</option>
                  <option value="health_app">Health app (FHIR)</option>
                  <option value="demo">Demo</option>
                </select>
              </Field>
              <Field label="Screening location (optional)">
                <input className={inputCls} value={form.location} onChange={set("location")} placeholder="Al Ain mobile screening unit" />
              </Field>
            </div>
            <ErrorNote text={error} />
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => router.back()}>
                Cancel
              </Button>
              <Button variant="primary" disabled={busy || Boolean(noFinding) || (!manual && !assessment)}>
                {busy ? "Creating…" : "Create case, refer & message patient"}
              </Button>
            </div>
          </form>
        </Card>

        <div className="space-y-4">
          <Card className={`p-5 text-sm ${assessment?.urgency === "urgent" ? "border-red-300 ring-2 ring-red-100" : ""}`}>
            <h2 className="mb-2 font-semibold text-slate-900">Risk assessment</h2>
            {!assessment && <p className="text-slate-500">Type readings to see which agreed criteria apply.</p>}
            {noFinding && <p className="text-emerald-700">Within agreed criteria. No actionable finding, so no case will open.</p>}
            {assessment?.actionable && (
              <>
                <div className="flex items-center gap-2">
                  <span className="font-medium">{PATHWAY_LABEL[assessment.pathway!]}</span>
                  <UrgencyPill urgency={assessment.urgency!} />
                </div>
                <ul className="mt-2 space-y-1 text-slate-700">
                  {assessment.findings.map((f) => (
                    <li key={f.pathway}>
                      • <b>{PATHWAY_LABEL[f.pathway]}</b>: {f.reason}
                    </li>
                  ))}
                </ul>
                {service && (
                  <div className="mt-3 rounded-lg bg-teal-50 p-3 text-teal-900">
                    <div className="text-xs font-medium uppercase text-teal-700">Referral</div>
                    {service}
                  </div>
                )}
              </>
            )}
          </Card>
          <Card className="p-5">
            <h2 className="font-semibold text-slate-900">Bulk import</h2>
            <p className="mt-1 text-sm text-slate-500">
              CSV with <code className="rounded bg-slate-100 px-1 text-xs">phone, display_name, language, region, insurance, emirates_id</code> and reading columns (
              <code className="rounded bg-slate-100 px-1 text-xs">systolic, diastolic, hba1c, bmi, fit, birads…</code>).
            </p>
            <label className="mt-3 inline-flex cursor-pointer items-center rounded-lg bg-white px-3 py-2 text-sm font-medium text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50">
              Upload CSV
              <input type="file" accept=".csv" className="hidden" onChange={upload} />
            </label>
            {csvResult && <p className="mt-3 text-sm text-slate-700">{csvResult}</p>}
          </Card>
        </div>
      </div>
    </Shell>
  );
}

// Mirrors referrals.choose_facility closely enough for a preview; the server decides.
const ROUTING: Record<string, string> = {
  "hypertension:urgent": "urgent_bp",
  hypertension: "pc_bp_review",
  "diabetes:routine": "pc_diabetes_prevention",
  diabetes: "endocrinology",
  obesity: "healthy_weight",
  cervical: "colposcopy",
  colorectal: "colonoscopy",
  breast: "breast_diagnostic",
  general: "pc_review",
};

function referralPreview(meta: Meta, a: Assessment, region: string, insurance: string): string {
  const svc = ROUTING[`${a.pathway}:${a.urgency}`] ?? ROUTING[a.pathway!] ?? "pc_review";
  const options = meta.facilities.filter((f) => f.services.includes(svc));
  const best = options.find((f) => f.region === region && f.networks.includes(insurance)) ?? options.find((f) => f.networks.includes(insurance)) ?? options[0];
  return `${meta.services[svc]} → ${best ? `${best.name} (${best.region_label})` : "no facility"}`;
}
