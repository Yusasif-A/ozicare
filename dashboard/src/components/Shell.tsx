"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, clearSession, getToken, getUser, post, type Meta, type Notification, type User } from "@/lib/api";
import { ago } from "@/lib/format";

const NAV = [
  { href: "/board", label: "Case board", icon: "▦", match: (p: string) => p.startsWith("/board") || p.startsWith("/case") && !p.startsWith("/cases") },
  { href: "/providers", label: "Referral monitor", icon: "⇄", match: (p: string) => p.startsWith("/providers") },
  { href: "/cases/new", label: "New result", icon: "+", match: (p: string) => p.startsWith("/cases/new") },
  { href: "/metrics", label: "Loop metrics", icon: "◔", match: (p: string) => p.startsWith("/metrics") },
];

const DEMOS = [
  { scenario: "cervical", label: "Cervical screening", sub: "English call" },
  { scenario: "diabetes", label: "Diabetes (HbA1c)", sub: "Arabic call" },
];

/** Sidebar + topbar shell, after the Avalio / SitePay dashboards. */
export default function Shell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const path = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [demoOpen, setDemoOpen] = useState(false);
  const [demoBusy, setDemoBusy] = useState<string | null>(null);
  const [demoErr, setDemoErr] = useState<string | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    setUser(getUser());
    api<Meta>("/api/meta").then(setMeta).catch(() => {});
  }, [router]);

  if (!user) return null;

  async function startDemo(scenario: string) {
    setDemoBusy(scenario);
    setDemoErr(null);
    try {
      const r = await post<{ live_case: string | null }>("/api/demo/reset", { scenario });
      window.location.href = r.live_case ? `/case?id=${r.live_case}` : "/board";
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Demo reset failed";
      setDemoErr(msg === "Not Found" ? "The server is on an older version: redeploy the backend." : msg);
      setDemoBusy(null);
    }
  }

  const ch = meta?.channels;

  return (
    <div className="flex min-h-screen bg-[#f6f7f5]">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-slate-200 bg-white px-4 py-6 md:flex">
        <Link href="/board" className="mb-8 flex items-center gap-2.5 px-2">
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-teal-600 to-teal-800 text-sm font-extrabold text-white shadow-sm">OC</span>
          <span>
            <span className="block text-[1.05rem] font-extrabold leading-tight text-slate-900">OziCare</span>
            <span className="block text-[11px] font-medium text-slate-500">Screening-to-care</span>
          </span>
        </Link>
        <nav className="flex flex-1 flex-col gap-1">
          {NAV.map((n) => {
            const active = n.match(path);
            return (
              <Link
                key={n.href}
                href={n.href}
                className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition ${
                  active ? "bg-teal-50 font-bold text-teal-900" : "font-medium text-slate-500 hover:bg-slate-50 hover:text-slate-900"
                }`}
              >
                <span className={`grid h-6 w-6 place-items-center rounded-md text-xs ${active ? "bg-teal-700 text-white" : "bg-slate-100 text-slate-500"}`}>{n.icon}</span>
                {n.label}
              </Link>
            );
          })}
        </nav>
        <div className="mb-3 rounded-xl bg-slate-50 p-3 text-xs text-slate-500 ring-1 ring-slate-200">
          <div className="font-semibold text-slate-700">{user.name}</div>
          <div className="capitalize">{user.role}</div>
        </div>
        <button
          className="rounded-lg border border-slate-200 px-3 py-2 text-left text-sm font-semibold text-slate-500 hover:border-red-300 hover:text-red-600"
          onClick={() => {
            clearSession();
            router.replace("/login");
          }}
        >
          Sign out
        </button>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-16 shrink-0 items-center gap-3 border-b border-slate-200 bg-white/95 px-4 backdrop-blur md:px-8">
          <Link href="/board" className="flex items-center gap-2 md:hidden">
            <span className="grid h-8 w-8 place-items-center rounded-lg bg-teal-700 text-xs font-extrabold text-white">OC</span>
          </Link>
          <nav className="flex gap-1 overflow-x-auto md:hidden">
            {NAV.map((n) => (
              <Link key={n.href} href={n.href} className={`whitespace-nowrap rounded-md px-2.5 py-1.5 text-xs font-semibold ${n.match(path) ? "bg-teal-50 text-teal-900" : "text-slate-500"}`}>
                {n.label}
              </Link>
            ))}
          </nav>
          <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
            <Bell />
            {ch && (
              <div className="hidden items-center gap-1.5 lg:flex">
                <Chip ok={ch.whatsapp} label="WhatsApp" />
                <Chip ok={ch.whatsapp_call} label="WhatsApp calls" />
                <Chip ok={ch.phone_call} label="Phone calls" />
              </div>
            )}
            {user.role === "admin" && (
              <div className="relative">
                <button
                  onClick={() => setDemoOpen(!demoOpen)}
                  className="rounded-lg bg-slate-900 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800"
                >
                  ▶ Start demo
                </button>
                {demoOpen && (
                  <div className="absolute right-0 top-11 z-30 w-72 rounded-xl border border-slate-200 bg-white p-2 shadow-xl">
                    <p className="px-2 pb-2 pt-1 text-xs text-slate-500">Resets the board with sample patients and creates the live case for your phone. Nothing is sent until you press Notify.</p>
                    {DEMOS.map((d) => (
                      <button
                        key={d.scenario}
                        disabled={demoBusy !== null}
                        onClick={() => startDemo(d.scenario)}
                        className="flex w-full items-center justify-between rounded-lg px-3 py-2.5 text-left hover:bg-teal-50 disabled:opacity-50"
                      >
                        <span>
                          <span className="block text-sm font-semibold text-slate-900">{d.label}</span>
                          <span className="block text-xs text-slate-500">{d.sub}</span>
                        </span>
                        <span className="text-xs font-semibold text-teal-700">{demoBusy === d.scenario ? "Preparing…" : "Start →"}</span>
                      </button>
                    ))}
                    {demoErr && <p className="m-2 rounded-lg bg-red-50 p-2 text-xs text-red-700">{demoErr}</p>}
                  </div>
                )}
              </div>
            )}
          </div>
        </header>
        <main className="w-full max-w-[1400px] flex-1 px-4 py-6 md:px-8 md:py-8">{children}</main>
      </div>
    </div>
  );
}

function Chip({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-bold ${ok ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-emerald-500" : "bg-slate-400"}`} />
      {label}
    </span>
  );
}

const NOTE_TONE: Record<string, string> = {
  danger: "bg-red-500",
  warn: "bg-violet-500",
  info: "bg-sky-400",
  ok: "bg-emerald-500",
};

function noteText(n: Notification): string {
  const p = n.payload as Record<string, string | boolean | undefined>;
  switch (n.type) {
    case "provider_escalated":
      return `Provider delay: ${p.reason}`;
    case "escalated":
      return `Escalated: ${p.reason}`;
    case "provider_rerouted":
      return `${p.service} re-routed from ${p.from} to ${p.to}`;
    case "provider_chased":
      return `${p.facility} chased for ${p.service}`;
    case "checkin_done":
      return p.warning_signs ? `Check-in concern: ${p.warning_signs}` : `Check-in: feeling ${p.feeling}`;
    case "provider_done":
      return `${p.service} done${p.result ? `: ${p.result}` : ""}`;
    case "recovery_verified":
      return `Recovery verified: ${p.result}`;
    case "signed_off":
      return `Loop closed with evidence by ${p.by}`;
    default:
      return n.type.replaceAll("_", " ");
  }
}

/** Staff alerts: escalations, provider delays, check-in concerns, verified recoveries. */
function Bell() {
  const [data, setData] = useState<{ rows: Notification[]; unread: number } | null>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const load = () => api<{ rows: Notification[]; unread: number }>("/api/notifications").then(setData).catch(() => {});
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);
  const unread = data?.unread ?? 0;
  return (
    <div className="relative">
      <button
        aria-label="Notifications"
        onClick={() => {
          setOpen(!open);
          if (!open && unread) post("/api/notifications/seen").then(() => setData((d) => (d ? { ...d, unread: 0 } : d))).catch(() => {});
        }}
        className="relative grid h-9 w-9 place-items-center rounded-lg text-lg text-slate-600 ring-1 ring-inset ring-slate-200 hover:bg-slate-50"
      >
        🔔
        {unread > 0 && (
          <span className="absolute -right-1.5 -top-1.5 grid h-5 min-w-5 place-items-center rounded-full bg-red-600 px-1 text-[11px] font-bold text-white">{unread > 9 ? "9+" : unread}</span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 top-11 z-30 w-[22rem] max-w-[90vw] rounded-xl border border-slate-200 bg-white shadow-xl">
          <div className="border-b border-slate-100 px-4 py-2.5 text-sm font-semibold text-slate-900">Alerts</div>
          <ul className="max-h-[60vh] overflow-y-auto">
            {(data?.rows ?? []).map((n) => (
              <li key={n.id}>
                <Link href={`/case?id=${n.case_id}`} onClick={() => setOpen(false)} className="flex gap-3 px-4 py-2.5 hover:bg-slate-50">
                  <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${NOTE_TONE[n.tone]}`} />
                  <span className="min-w-0 text-sm">
                    <span className="block font-semibold text-slate-900">{n.patient_name}</span>
                    <span className="block text-slate-600">{noteText(n)}</span>
                    <span className="block text-xs text-slate-400">{ago(n.at)}</span>
                  </span>
                </Link>
              </li>
            ))}
            {data && data.rows.length === 0 && <li className="px-4 py-6 text-center text-sm text-slate-400">No alerts</li>}
          </ul>
        </div>
      )}
    </div>
  );
}
