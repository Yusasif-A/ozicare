"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { Button, Card, ErrorNote, Field, inputCls } from "@/components/ui";
import { api, post, type Case, type Meta } from "@/lib/api";

const URGENCY_HELP: Record<string, string> = {
  routine: "Contact within hours; reminders over days.",
  soon: "Contact within the hour; reminders within a day.",
  urgent: "Contact now. If not acknowledged within minutes, auto-escalates to a clinician.",
};

export default function NewCase() {
  const router = useRouter();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [form, setForm] = useState({
    display_name: "",
    phone: "",
    language: "en",
    screening_type: "general_abnormal",
    urgency: "soon",
    result_summary: "",
    source: "demo",
    location: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [csvResult, setCsvResult] = useState<string | null>(null);

  useEffect(() => {
    api<Meta>("/api/meta").then(setMeta).catch(() => {});
  }, []);

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setForm({ ...form, [k]: e.target.value });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const c = await post<Case>("/api/cases", form);
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

  return (
    <Shell>
      <div className="mx-auto grid max-w-5xl gap-6 lg:grid-cols-[1fr_320px]">
        <Card className="p-6">
          <h1 className="text-xl font-semibold text-slate-900">New actionable result</h1>
          <p className="mt-1 text-sm text-slate-500">The patient is messaged on WhatsApp as soon as you save.</p>
          <form onSubmit={submit} className="mt-6 space-y-5">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Patient name">
                <input className={inputCls} value={form.display_name} onChange={set("display_name")} required placeholder="Grace Okafor" />
              </Field>
              <Field label="WhatsApp number" hint="International format, e.g. +234 803 000 0000">
                <input className={inputCls} value={form.phone} onChange={set("phone")} required placeholder="+234…" />
              </Field>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Screening type">
                <select className={inputCls} value={form.screening_type} onChange={set("screening_type")}>
                  {Object.entries(meta?.screening_types ?? { general_abnormal: "health screening" }).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v.charAt(0).toUpperCase() + v.slice(1)}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Patient language" hint="Messages and calls use this language. The patient can switch any time.">
                <select className={inputCls} value={form.language} onChange={set("language")}>
                  <option value="en">English</option>
                  <option value="ar">Arabic</option>
                </select>
              </Field>
            </div>
            <Field label="Urgency">
              <div className="grid grid-cols-3 gap-2">
                {["routine", "soon", "urgent"].map((u) => (
                  <button
                    type="button"
                    key={u}
                    onClick={() => setForm({ ...form, urgency: u })}
                    className={`rounded-lg px-3 py-2 text-sm font-semibold capitalize ring-1 ring-inset ${
                      form.urgency === u
                        ? u === "urgent"
                          ? "bg-red-600 text-white ring-red-600"
                          : u === "soon"
                            ? "bg-amber-100 text-amber-900 ring-amber-400"
                            : "bg-teal-700 text-white ring-teal-700"
                        : "bg-white text-slate-600 ring-slate-300 hover:bg-slate-50"
                    }`}
                  >
                    {u}
                  </button>
                ))}
              </div>
              <span className="mt-1 block text-xs text-slate-500">{URGENCY_HELP[form.urgency]}</span>
            </Field>
            <Field label="Note for the patient (optional)" hint="Plain language, approved for the patient to read. No raw lab values or diagnoses.">
              <textarea className={inputCls} rows={3} value={form.result_summary} onChange={set("result_summary")} placeholder="Your repeat check is recommended within 2 weeks." />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Source">
                <select className={inputCls} value={form.source} onChange={set("source")}>
                  <option value="demo">Demo</option>
                  <option value="lab">Lab</option>
                  <option value="phc">Primary health centre</option>
                  <option value="camp">Screening camp</option>
                </select>
              </Field>
              <Field label="Location (optional)">
                <input className={inputCls} value={form.location} onChange={set("location")} placeholder="Riverside PHC" />
              </Field>
            </div>
            <ErrorNote text={error} />
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => router.back()}>
                Cancel
              </Button>
              <Button variant="primary" disabled={busy}>
                {busy ? "Creating…" : "Create case & message patient"}
              </Button>
            </div>
          </form>
        </Card>

        <div className="space-y-4">
          <Card className="p-5">
            <h2 className="font-semibold text-slate-900">Bulk import</h2>
            <p className="mt-1 text-sm text-slate-500">
              CSV with columns <code className="rounded bg-slate-100 px-1 text-xs">phone, display_name, screening_type, urgency, language, result_summary</code>
            </p>
            <label className="mt-3 inline-flex cursor-pointer items-center rounded-lg bg-white px-3 py-2 text-sm font-medium text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50">
              Upload CSV
              <input type="file" accept=".csv" className="hidden" onChange={upload} />
            </label>
            {csvResult && <p className="mt-3 text-sm text-slate-700">{csvResult}</p>}
          </Card>
          <Card className="p-5 text-sm text-slate-600">
            <h2 className="mb-2 font-semibold text-slate-900">What happens next</h2>
            <ol className="list-decimal space-y-1.5 pl-4">
              <li>WhatsApp goes out within a minute.</li>
              <li>Patient confirms identity before any detail is shared.</li>
              <li>They can get an explanation, book, or ask for a call.</li>
              <li>Silence triggers reminders; urgent cases escalate to a clinician.</li>
              <li>You close the case with evidence.</li>
            </ol>
          </Card>
        </div>
      </div>
    </Shell>
  );
}
