"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, clearSession, getToken, getUser, post, type Meta, type User } from "@/lib/api";

const NAV = [
  { href: "/board", label: "Case board", icon: "▦", match: (p: string) => p.startsWith("/board") || p.startsWith("/case") && !p.startsWith("/cases") },
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
