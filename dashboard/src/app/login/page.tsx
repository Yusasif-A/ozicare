"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getApiBase, post, saveSession, setApiBase, type User } from "@/lib/api";
import { Button, ErrorNote, Field, inputCls } from "@/components/ui";

export default function Login() {
  const router = useRouter();
  const [email, setEmail] = useState("admin@ozicare.demo");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [apiBase, setApiBaseInput] = useState("");
  const [showApi, setShowApi] = useState(false);

  useEffect(() => setApiBaseInput(getApiBase()), []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setApiBase(apiBase);
    try {
      const res = await post<{ token: string; user: User }>("/api/auth/login", { email, password });
      saveSession(res.token, res.user);
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-screen place-items-center bg-gradient-to-br from-teal-50 via-white to-slate-100 px-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-5 rounded-2xl border border-slate-200 bg-white p-8 shadow-lg">
        <div className="flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-teal-700 font-bold text-white">OC</span>
          <div>
            <h1 className="text-lg font-semibold text-slate-900">OziCare</h1>
            <p className="text-sm text-slate-500">Screening-to-care follow-up</p>
          </div>
        </div>
        <Field label="Email">
          <input className={inputCls} type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </Field>
        <Field label="Password">
          <input className={inputCls} type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoFocus />
        </Field>
        <ErrorNote text={error} />
        <Button variant="primary" className="w-full" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </Button>
        <div className="text-center text-xs text-slate-500">
          {showApi ? (
            <Field label="API server" hint="The OziCare backend, e.g. your ngrok https URL. Remembered in this browser.">
              <input className={inputCls} value={apiBase} onChange={(e) => setApiBaseInput(e.target.value)} placeholder="https://…" />
            </Field>
          ) : (
            <button type="button" className="hover:text-slate-800" onClick={() => setShowApi(true)}>
              Server: {apiBase.replace(/^https?:\/\//, "")} · change
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
