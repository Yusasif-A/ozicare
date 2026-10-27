"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { clearSession, getToken, getUser, type User } from "@/lib/api";

const NAV = [
  { href: "/", label: "Case board" },
  { href: "/cases/new", label: "New case" },
  { href: "/metrics", label: "Metrics" },
];

export default function Shell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const path = usePathname();
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    setUser(getUser());
  }, [router]);

  if (!user) return null;

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-6 px-4 py-3">
          <Link href="/" className="flex items-center gap-2">
            <span className="grid h-8 w-8 place-items-center rounded-lg bg-teal-700 text-sm font-bold text-white">OC</span>
            <span className="font-semibold text-slate-900">OziCare</span>
          </Link>
          <nav className="flex gap-1">
            {NAV.map((n) => {
              const active = n.href === "/" ? path === "/" || path === "/case" || path === "/case/" : path.startsWith(n.href);
              return (
                <Link
                  key={n.href}
                  href={n.href}
                  className={`rounded-lg px-3 py-1.5 text-sm font-medium ${active ? "bg-teal-50 text-teal-800" : "text-slate-600 hover:bg-slate-100"}`}
                >
                  {n.label}
                </Link>
              );
            })}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm">
            <span className="hidden text-slate-600 sm:inline">
              {user.name} <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">{user.role}</span>
            </span>
            <button
              className="text-slate-500 hover:text-slate-800"
              onClick={() => {
                clearSession();
                router.replace("/login");
              }}
            >
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
    </div>
  );
}
