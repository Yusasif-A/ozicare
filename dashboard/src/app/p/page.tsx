"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { getApiBase } from "@/lib/api";

type View = {
  language: "en" | "ar";
  first_name: string;
  org: string;
  identity_confirmed: boolean;
  status: string;
  closed: boolean;
  step?: string;
  steps?: string[];
  screening?: string;
  explain?: string;
  note?: string;
  next_steps?: string[];
  bring?: string;
  warning?: string;
  not_diagnosis?: string;
  urgent?: boolean;
  referral?: { service: string; clinic: string; address: string } | null;
  appointment?: { label: string; clinic: string; address: string } | null;
  slots?: { iso: string; label: string }[];
  attended?: boolean;
  callback_requested?: boolean;
};

// The patient page is bilingual: everything the patient reads is EN/AR.
const L = {
  en: {
    hello: "Hello",
    follow: "Your screening follow-up",
    steps: { result: "Result", referral: "Referral", booked: "Booked", visit: "Visit", done: "Done" } as Record<string, string>,
    about: "About your result",
    next: "What to do next",
    referral: "Your referral",
    appt: "Your appointment",
    pick: "Choose a time for your follow-up",
    book: "Book this time",
    bring: "What to bring",
    attended: "Thank you for attending. Your care team will guide you on any next steps.",
    callMe: "Call me",
    called: "A member of our care team will call you soon.",
    ask: "Ask a question",
    askPh: "Type your question…",
    send: "Send",
    closed: "This follow-up is closed. If you need anything, message us on WhatsApp.",
    urgent: "This follow-up is important. Please act today.",
    lang: "العربية",
    loading: "Loading…",
    signIn: "Sign in",
    signInTitle: "Sign in to see your follow-up",
    signInSub: "Use the phone number we messaged and the password from your care team.",
    phone: "Phone number",
    password: "Password",
    signingIn: "Signing in…",
    signOut: "Sign out",
    badLogin: "Wrong phone number or password.",
    private: "Your result is private. We only show it after you sign in.",
  },
  ar: {
    hello: "مرحباً",
    follow: "متابعة فحصك",
    steps: { result: "النتيجة", referral: "الإحالة", booked: "الحجز", visit: "الزيارة", done: "اكتمل" } as Record<string, string>,
    about: "عن نتيجتك",
    next: "الخطوات التالية",
    referral: "إحالتك",
    appt: "موعدك",
    pick: "اختر وقتاً لموعد المتابعة",
    book: "احجز هذا الموعد",
    bring: "ماذا تحضر",
    attended: "شكراً لحضورك. سيرشدك فريق الرعاية بشأن أي خطوات تالية.",
    callMe: "اتصل بي",
    called: "سيتصل بك أحد أعضاء فريق الرعاية قريباً.",
    ask: "اطرح سؤالاً",
    askPh: "اكتب سؤالك…",
    send: "إرسال",
    closed: "اكتملت هذه المتابعة. إذا احتجت أي شيء، راسلنا على واتساب.",
    urgent: "هذه المتابعة مهمة. يرجى التصرف اليوم.",
    lang: "English",
    loading: "جارٍ التحميل…",
    signIn: "تسجيل الدخول",
    signInTitle: "سجّل الدخول لمتابعة نتيجتك",
    signInSub: "استخدم رقم الهاتف الذي راسلناك عليه وكلمة المرور من فريق الرعاية.",
    phone: "رقم الهاتف",
    password: "كلمة المرور",
    signingIn: "جارٍ تسجيل الدخول…",
    signOut: "تسجيل الخروج",
    badLogin: "رقم الهاتف أو كلمة المرور غير صحيحة.",
    private: "نتيجتك خاصة، ولا نعرضها إلا بعد تسجيل الدخول.",
  },
};

const SESSION_KEY = "ozicare.patient";

function getSession(): string | null {
  try {
    return localStorage.getItem(SESSION_KEY);
  } catch {
    return null;
  }
}

function setSession(token: string | null) {
  try {
    if (token) localStorage.setItem(SESSION_KEY, token);
    else localStorage.removeItem(SESSION_KEY);
  } catch {}
}

class HttpError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json", "ngrok-skip-browser-warning": "1" };
  const session = getSession();
  if (session) headers.Authorization = `Bearer ${session}`;
  const res = await fetch(`${getApiBase()}/api/p/${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      msg = (await res.json()).detail ?? msg;
    } catch {}
    throw new HttpError(res.status, String(msg));
  }
  return res.json();
}

export default function PatientPage() {
  return (
    <Suspense fallback={null}>
      <Patient />
    </Suspense>
  );
}

function Patient() {
  const token = useSearchParams().get("t") ?? "";
  const [v, setV] = useState<View | null>(null);
  const [lang, setLang] = useState<"en" | "ar" | null>(null);
  const [needLogin, setNeedLogin] = useState(false);
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [slot, setSlot] = useState("");
  const [q, setQ] = useState("");
  const [chat, setChat] = useState<{ who: "me" | "oc"; text: string }[]>([]);

  const load = useCallback(
    async (l?: "en" | "ar" | null) => {
      if (!getSession()) {
        setNeedLogin(true);
        return;
      }
      try {
        setV(await call<View>(`me${l ? `?lang=${l}` : ""}`));
        setNeedLogin(false);
      } catch (e) {
        if (e instanceof HttpError && e.status === 401) setSession(null);
        setNeedLogin(true);
      }
    },
    [],
  );

  useEffect(() => {
    // A WhatsApp link fills in the phone; the link itself shows nothing else.
    if (token) {
      call<{ phone: string; language: "en" | "ar" }>(`link/${token}`)
        .then((info) => {
          setPhone(info.phone);
          setLang((l) => l ?? info.language);
        })
        .catch(() => {});
    }
    load();
  }, [load, token]);

  async function signIn(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const r = await call<{ token: string; language: "en" | "ar" }>("login", { phone, password });
      setSession(r.token);
      setPassword("");
      setLang((l) => l ?? r.language);
      await load(lang ?? r.language);
    } catch {
      setErr(L[lang ?? "en"].badLogin);
    } finally {
      setBusy(false);
    }
  }

  const t = L[lang ?? v?.language ?? "en"];
  const ar = (lang ?? v?.language) === "ar";

  async function act(path: string, body: unknown = {}) {
    setBusy(true);
    setErr(null);
    try {
      await call<View>(`me/${path}`, body);
      await load(lang);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  async function ask(e: React.FormEvent) {
    e.preventDefault();
    const text = q.trim();
    if (!text) return;
    setQ("");
    setChat((c) => [...c, { who: "me", text }]);
    setBusy(true);
    try {
      const r = await call<{ reply: string }>("me/ask", { text, lang: lang ?? v?.language });
      setChat((c) => [...c, { who: "oc", text: r.reply }]);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  const tl = L[lang ?? "en"];
  const arLogin = (lang ?? "en") === "ar";

  if (needLogin) {
    return (
      <Frame ar={arLogin}>
        <div className="bg-teal-700 px-5 pb-8 pt-5 text-white">
          <div className="flex items-center">
            <span className="grid h-7 w-7 place-items-center rounded-lg bg-white/15 text-[11px] font-bold">OC</span>
            <span className="ms-2 text-sm font-medium opacity-90">OziCare</span>
            <button className="ms-auto rounded-full bg-white/15 px-3 py-1 text-xs font-medium hover:bg-white/25" onClick={() => setLang(arLogin ? "en" : "ar")}>
              {tl.lang}
            </button>
          </div>
          <h1 className="mt-5 text-2xl font-semibold">{tl.signInTitle}</h1>
          <p className="mt-1 text-sm opacity-90">{tl.signInSub}</p>
        </div>
        <form onSubmit={signIn} className="space-y-4 p-5">
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-700">{tl.phone}</span>
            <input
              dir="ltr"
              inputMode="tel"
              autoComplete="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="+971 50 000 0000"
              required
              className="w-full rounded-xl px-4 py-3 text-base ring-1 ring-slate-300 focus:outline-none focus:ring-2 focus:ring-teal-600"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-700">{tl.password}</span>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="w-full rounded-xl px-4 py-3 text-base ring-1 ring-slate-300 focus:outline-none focus:ring-2 focus:ring-teal-600"
            />
          </label>
          {err && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</p>}
          <button disabled={busy} className="w-full rounded-xl bg-teal-700 py-3 font-semibold text-white disabled:opacity-50">
            {busy ? tl.signingIn : tl.signIn}
          </button>
          <p className="text-center text-xs text-slate-500">🔒 {tl.private}</p>
        </form>
      </Frame>
    );
  }
  if (!v) {
    return (
      <Frame ar={arLogin}>
        <p className="p-6 text-center text-slate-400">{tl.loading}</p>
      </Frame>
    );
  }

  const header = (
    <div className="bg-teal-700 px-5 pb-6 pt-5 text-white">
      <div className="flex items-center gap-2">
        <span className="grid h-7 w-7 place-items-center rounded-lg bg-white/15 text-[11px] font-bold">OC</span>
        <span className="text-sm font-medium opacity-90">OziCare</span>
        <button
          className="ms-auto rounded-full bg-white/15 px-3 py-1 text-xs font-medium hover:bg-white/25"
          onClick={() => {
            const next = ar ? "en" : "ar";
            setLang(next);
            load(next);
          }}
        >
          {t.lang}
        </button>
        <button
          className="rounded-full bg-white/15 px-3 py-1 text-xs font-medium hover:bg-white/25"
          onClick={() => {
            setSession(null);
            setV(null);
            setNeedLogin(true);
          }}
        >
          {t.signOut}
        </button>
      </div>
      <h1 className="mt-4 text-2xl font-semibold">
        {t.hello} {v.first_name}
      </h1>
      <p className="text-sm opacity-90">{v.screening ?? t.follow}</p>
    </div>
  );

  const stepIdx = v.steps?.indexOf(v.step ?? "") ?? 0;

  return (
    <Frame ar={ar}>
      {header}
      <div className="space-y-4 p-4">
        {!v.closed && (
          <div className="flex justify-between rounded-xl bg-white px-3 py-3 text-[11px] font-medium text-slate-500 ring-1 ring-slate-200">
            {v.steps?.map((s, i) => (
              <span key={s} className="flex flex-1 flex-col items-center gap-1">
                <span className={`h-2.5 w-2.5 rounded-full ${i <= stepIdx ? "bg-teal-600" : "bg-slate-300"}`} />
                <span className={i === stepIdx ? "text-teal-800" : ""}>{t.steps[s]}</span>
              </span>
            ))}
          </div>
        )}

        {v.urgent && !v.closed && <div className="rounded-xl bg-red-50 p-3 text-sm font-medium text-red-800 ring-1 ring-red-200">{t.urgent}</div>}
        {v.closed && <Box>{t.closed}</Box>}
        {v.attended && !v.closed && <Box tone="ok">{t.attended}</Box>}

        {v.appointment ? (
          <Box title={t.appt} tone="ok">
            <div className="text-lg font-semibold text-slate-900">{v.appointment.label}</div>
            <div>{v.appointment.clinic}</div>
            <div className="text-xs text-slate-500">{v.appointment.address}</div>
          </Box>
        ) : (
          v.referral && (
            <Box title={t.referral}>
              <div className="font-semibold text-slate-900">{v.referral.service}</div>
              <div>{v.referral.clinic}</div>
              <div className="text-xs text-slate-500">{v.referral.address}</div>
            </Box>
          )
        )}

        {!v.closed && !v.appointment && (v.slots?.length ?? 0) > 0 && (
          <Box title={t.pick}>
            <div className="space-y-2">
              {v.slots!.map((s) => (
                <label key={s.iso} className={`flex cursor-pointer items-center gap-3 rounded-lg p-3 ring-1 ${slot === s.iso ? "bg-teal-50 ring-teal-500" : "ring-slate-200"}`}>
                  <input type="radio" name="slot" checked={slot === s.iso} onChange={() => setSlot(s.iso)} />
                  <span className="font-medium text-slate-800">{s.label}</span>
                </label>
              ))}
            </div>
            <button disabled={busy || !slot} onClick={() => act("book", { slot_iso: slot })} className="mt-3 w-full rounded-xl bg-teal-700 py-3 font-semibold text-white disabled:opacity-50">
              {t.book}
            </button>
          </Box>
        )}

        {v.explain && (
          <Box title={t.about}>
            <p>{v.explain}</p>
            {v.note && <p className="mt-2">{v.note}</p>}
            <p className="mt-2 text-xs text-slate-500">{v.not_diagnosis}</p>
          </Box>
        )}

        {v.next_steps && (
          <Box title={t.next}>
            <ul className="list-disc space-y-1 ps-5">
              {v.next_steps.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
            <div className="mt-3 text-xs font-semibold uppercase text-slate-500">{t.bring}</div>
            <p>{v.bring}</p>
          </Box>
        )}

        {!v.closed && (
          <>
            {v.callback_requested ? (
              <Box tone="ok">{t.called}</Box>
            ) : (
              <button disabled={busy} onClick={() => act("call")} className="w-full rounded-xl bg-white py-3 font-semibold text-teal-800 ring-1 ring-teal-300 disabled:opacity-50">
                📞 {t.callMe}
              </button>
            )}
            <Box title={t.ask}>
              <div className="space-y-2">
                {chat.map((m, i) => (
                  <div key={i} dir="auto" className={`whitespace-pre-wrap rounded-xl px-3 py-2 text-sm ${m.who === "me" ? "ms-8 bg-teal-700 text-white" : "me-8 bg-slate-100 text-slate-800"}`}>
                    {m.text}
                  </div>
                ))}
              </div>
              <form onSubmit={ask} className="mt-2 flex gap-2">
                <input dir="auto" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t.askPh} className="min-w-0 flex-1 rounded-lg px-3 py-2 text-sm ring-1 ring-slate-300 focus:outline-none focus:ring-2 focus:ring-teal-600" />
                <button disabled={busy || !q.trim()} className="rounded-lg bg-teal-700 px-4 text-sm font-semibold text-white disabled:opacity-50">
                  {t.send}
                </button>
              </form>
            </Box>
          </>
        )}

        {err && <p className="text-center text-sm text-red-600">{err}</p>}
        {v.warning && <p className="px-1 text-xs leading-relaxed text-red-700">{v.warning}</p>}
      </div>
    </Frame>
  );
}

function Frame({ ar, children }: { ar: boolean; children: React.ReactNode }) {
  return (
    <div dir={ar ? "rtl" : "ltr"} lang={ar ? "ar" : "en"} className="min-h-screen bg-slate-100 sm:py-8">
      <div className="mx-auto min-h-screen max-w-md overflow-hidden bg-slate-50 shadow-xl sm:min-h-0 sm:rounded-3xl">{children}</div>
    </div>
  );
}

function Box({ title, tone, children }: { title?: string; tone?: "ok"; children: React.ReactNode }) {
  return (
    <section className={`rounded-xl p-4 text-sm leading-relaxed text-slate-700 ring-1 ${tone === "ok" ? "bg-teal-50 ring-teal-200" : "bg-white ring-slate-200"}`}>
      {title && <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h2>}
      {children}
    </section>
  );
}
