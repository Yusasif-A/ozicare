import Link from "next/link";

// The loop, as the first thing anyone sees: this is what OziCare is.
const LOOP = [
  { n: "01", icon: "🧪", title: "Result arrives", body: "From the lab, screening unit or health record, often days after the visit." },
  { n: "02", icon: "🩺", title: "Risk & referral", body: "Clinical rules set urgency. Referred to the right clinic, in network." },
  { n: "03", icon: "💬", title: "Patient reached", body: "WhatsApp in English or Arabic, with their own secure page." },
  { n: "04", icon: "📞", title: "AI call & booking", body: "Explains in plain words, answers questions, books on the call." },
  { n: "05", icon: "✅", title: "Outcome verified", body: "Attendance recorded, case closed with evidence. Nobody lost." },
];

const MEASURES = [
  ["Referral completion", "Did the person reach the recommended service?"],
  ["Time to assessment", "How quickly did follow-up happen?"],
  ["Treatment completion", "Did the person complete the next care step?"],
  ["Lost-to-follow-up risk", "Who needs outreach or a care-team alert?"],
];

const SAFE = [
  ["Identity first", "Nothing about a result is shared until the person confirms who they are, on WhatsApp, on the call or by signing in."],
  ["Never diagnoses", "A safety guard blocks diagnosis, medicine names and doses, in English and Arabic. Clinicians decide."],
  ["Emergencies escalate", "Chest pain, breathing trouble and other red flags trigger urgent guidance and alert a clinician at once."],
  ["Full audit trail", "Every message, call, referral and status change is recorded, with the reason, and can be exported."],
];

export default function Home() {
  return (
    <div className="min-h-screen bg-[#f6f5f1] text-slate-900">
      {/* Nav */}
      <header className="sticky top-0 z-30 border-b border-black/5 bg-[#f6f5f1]/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-3 sm:px-6">
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-teal-600 to-teal-800 text-sm font-extrabold text-white">OC</span>
          <span className="text-lg font-bold">OziCare</span>
          <nav className="ml-8 hidden gap-6 text-sm font-medium text-slate-600 md:flex">
            <a href="#loop" className="hover:text-slate-900">The loop</a>
            <a href="#patients" className="hover:text-slate-900">Patients</a>
            <a href="#teams" className="hover:text-slate-900">Care teams</a>
            <a href="#integrate" className="hover:text-slate-900">Integration</a>
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <Link href="/p" className="hidden rounded-full px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-black/5 sm:inline-block">
              Patient sign in
            </Link>
            <Link href="/login" className="rounded-full bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800">
              Staff sign in
            </Link>
          </div>
        </div>
      </header>

      {/* Hero: the problem, the promise, and the loop straight away */}
      <section className="mx-auto max-w-6xl px-4 pb-10 pt-12 sm:px-6 lg:pt-16">
        <div className="grid items-center gap-10 lg:grid-cols-[1.05fr_1fr]">
          <div>
            <p className="inline-flex items-center gap-2 rounded-full bg-teal-50 px-3 py-1 text-xs font-semibold text-teal-800 ring-1 ring-teal-200">
              <span className="h-2 w-2 rounded-full bg-teal-500" /> Screening-to-care follow-up · English & العربية
            </p>
            <h1 className="mt-5 text-4xl font-bold leading-[1.08] tracking-tight sm:text-6xl">
              Every screening result,
              <br />
              <span className="text-teal-700">followed through to care.</span>
            </h1>
            <p className="mt-5 max-w-xl text-lg leading-relaxed text-slate-600">
              Results often come back after people have gone home, and many are never acted on. OziCare reaches each person on WhatsApp, explains their
              result, books their follow-up on a call, and tracks it until care is given.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link href="/login" className="rounded-full bg-teal-700 px-6 py-3 text-sm font-semibold text-white shadow-sm hover:bg-teal-800">
                Open the care-team dashboard
              </Link>
              <a href="#loop" className="rounded-full bg-white px-6 py-3 text-sm font-semibold text-slate-800 ring-1 ring-black/10 hover:bg-slate-50">
                See how the loop works
              </a>
            </div>
          </div>
          <div className="relative">
            <img src="/img/care-talk.jpg" alt="A clinician talking with a patient about her results" className="h-[420px] w-full rounded-[28px] object-cover object-[60%_30%] shadow-xl" />
            <div className="absolute -bottom-10 -left-4 w-[150px] overflow-hidden rounded-[22px] border-[6px] border-slate-900 bg-slate-900 shadow-2xl sm:-left-10 sm:w-[175px]">
              <img src="/img/wa-booked.jpg" alt="WhatsApp booking confirmation from OziCare" className="block w-full" />
            </div>
            <div className="absolute -right-2 top-6 rounded-2xl bg-white px-4 py-3 shadow-lg ring-1 ring-black/5 sm:-right-6">
              <div className="text-xs font-semibold text-slate-500">Booked on the call</div>
              <div className="text-sm font-bold text-teal-700">✓ Mon 16 Nov · 09:30</div>
            </div>
          </div>
        </div>

        {/* The loop, right under the hero */}
        <div id="loop" className="mt-16 scroll-mt-24 rounded-[28px] bg-white p-5 shadow-sm ring-1 ring-black/5 sm:p-8">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.18em] text-teal-700">The screening-to-care loop</p>
              <h2 className="mt-1 text-2xl font-bold tracking-tight sm:text-3xl">From result to care, with no one lost between steps</h2>
            </div>
            <p className="text-sm text-slate-500">Every step has an owner, a deadline and an audit trail.</p>
          </div>
          <ol className="mt-8 grid gap-4 md:grid-cols-5">
            {LOOP.map((s, i) => (
              <li key={s.n} className="relative">
                <div className={`h-full rounded-2xl p-5 ${i === 3 ? "bg-teal-700 text-white" : "bg-[#f3f6f5]"}`}>
                  <div className="flex items-center justify-between">
                    <span className={`text-xs font-bold ${i === 3 ? "text-teal-100" : "text-teal-700"}`}>STEP {s.n}</span>
                    <span className="text-2xl">{s.icon}</span>
                  </div>
                  <h3 className="mt-4 font-bold">{s.title}</h3>
                  <p className={`mt-1.5 text-sm leading-relaxed ${i === 3 ? "text-teal-50" : "text-slate-600"}`}>{s.body}</p>
                </div>
                {i < LOOP.length - 1 && <span className="absolute -right-3 top-1/2 z-10 hidden -translate-y-1/2 text-xl text-teal-600 md:block">›</span>}
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* Patients */}
      <section id="patients" className="mx-auto max-w-6xl scroll-mt-24 px-4 py-14 sm:px-6">
        <div className="grid items-center gap-10 rounded-[28px] bg-white p-6 shadow-sm ring-1 ring-black/5 sm:p-10 lg:grid-cols-2">
          <div className="flex justify-center gap-4">
            <div className="w-[46%] max-w-[230px] overflow-hidden rounded-[24px] border-[6px] border-slate-900 bg-slate-900 shadow-xl">
              <img src="/img/wa-message.jpg" alt="OziCare WhatsApp message with options and a link to the patient page" className="block w-full" />
            </div>
            <div className="mt-10 w-[46%] max-w-[230px] overflow-hidden rounded-[24px] border-[6px] border-slate-900 bg-white shadow-xl">
              <img src="/img/patient-page.jpg" alt="The OziCare patient page showing the appointment and progress" className="block w-full" />
            </div>
          </div>
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-teal-700">For patients</p>
            <h2 className="mt-2 text-3xl font-bold tracking-tight">A personal reason, and a one-tap next step</h2>
            <p className="mt-4 leading-relaxed text-slate-600">
              Not a generic reminder: a message about their own result, in their language, on the WhatsApp they already use.
            </p>
            <ul className="mt-6 space-y-3 text-slate-700">
              {[
                "Their result explained in plain words, never a diagnosis",
                "Tap “Talk to us” and the AI assistant answers their questions",
                "Booked during the call, confirmed on WhatsApp straight away",
                "Their own secure page: progress, referral and appointment",
                "Reminders, and kind re-booking if they miss the visit",
              ].map((t) => (
                <li key={t} className="flex gap-3">
                  <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-teal-100 text-xs font-bold text-teal-800">✓</span>
                  {t}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* Care teams */}
      <section id="teams" className="mx-auto max-w-6xl scroll-mt-24 px-4 py-6 sm:px-6">
        <div className="grid gap-6 lg:grid-cols-[1fr_1.3fr]">
          <div className="overflow-hidden rounded-[28px] bg-white shadow-sm ring-1 ring-black/5">
            <img src="/img/consult.jpg" alt="Two clinicians reviewing patient results on a screen" className="h-56 w-full object-cover" />
            <div className="p-6 sm:p-8">
              <p className="text-xs font-bold uppercase tracking-[0.18em] text-teal-700">For care teams</p>
              <h2 className="mt-2 text-2xl font-bold tracking-tight">One live board, not a spreadsheet</h2>
              <p className="mt-3 leading-relaxed text-slate-600">
                Every result has an owner and a deadline. Urgent, overdue and at-risk patients rise to the top. Clinicians accept referrals, and the case
                updates by itself when the patient signs in, books and attends.
              </p>
            </div>
          </div>
          <div className="flex flex-col gap-6">
            <div className="overflow-hidden rounded-[28px] bg-white p-3 shadow-sm ring-1 ring-black/5">
              <img src="/img/case.jpg" alt="The OziCare case view with the prioritisation reason and referral" className="w-full rounded-[20px]" />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              {MEASURES.map(([t, q]) => (
                <div key={t} className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-black/5">
                  <div className="text-sm font-bold text-teal-800">{t}</div>
                  <div className="mt-1 text-sm text-slate-500">{q}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Safety */}
      <section className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
        <div className="grid items-center gap-10 lg:grid-cols-[1fr_1.15fr]">
          <img src="/img/hands.jpg" alt="Holding hands, a gesture of care" className="h-[360px] w-full rounded-[28px] object-cover shadow-sm" />
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-teal-700">Safe by design</p>
            <h2 className="mt-2 text-3xl font-bold tracking-tight">AI reaches out and explains. Clinicians decide and care.</h2>
            <div className="mt-6 grid gap-4 sm:grid-cols-2">
              {SAFE.map(([t, d]) => (
                <div key={t} className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-black/5">
                  <div className="font-bold">{t}</div>
                  <p className="mt-1.5 text-sm leading-relaxed text-slate-600">{d}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Integration */}
      <section id="integrate" className="scroll-mt-24 bg-[#0b1514] text-white">
        <div className="mx-auto grid max-w-6xl items-center gap-10 px-4 py-16 sm:px-6 lg:grid-cols-[1.1fr_1fr]">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-teal-300">Not another app</p>
            <h2 className="mt-2 text-3xl font-bold tracking-tight sm:text-4xl">Built to plug straight into Sahatna</h2>
            <p className="mt-4 max-w-xl leading-relaxed text-slate-300">
              OziCare is the follow-up engine behind the health apps people already use. It speaks HL7 FHIR R4, so results flow in, and the referral,
              booking and progress flow back for the patient to see.
            </p>
            <div className="mt-8 grid gap-3 sm:grid-cols-3">
              {[
                ["In", "Screening results", "Bundle: Patient, LOINC results, Coverage"],
                ["Out", "Referral & booking", "ServiceRequest, Appointment, Task"],
                ["Back", "Visit outcome", "Encounter marks attended or no-show"],
              ].map(([k, t, d]) => (
                <div key={k} className="rounded-2xl bg-white/5 p-4 ring-1 ring-white/10">
                  <div className="text-xs font-bold uppercase text-teal-300">{k}</div>
                  <div className="mt-1 font-semibold">{t}</div>
                  <div className="mt-1 text-xs text-slate-400">{d}</div>
                </div>
              ))}
            </div>
          </div>
          <div className="relative">
            <img src="/img/lab.jpg" alt="A laboratory scientist reviewing a sample" className="h-[340px] w-full rounded-[28px] object-cover opacity-90" />
            <div className="absolute -bottom-5 left-6 right-6 rounded-2xl bg-white p-4 text-slate-900 shadow-xl">
              <div className="text-xs font-semibold text-slate-500">Lab result received · HL7 FHIR</div>
              <div className="mt-1 text-sm font-bold">Cervical cytology: HSIL, HPV 16 → colposcopy, soon</div>
            </div>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="mx-auto max-w-6xl px-4 py-16 text-center sm:px-6">
        <h2 className="mx-auto max-w-3xl text-3xl font-bold tracking-tight sm:text-4xl">Early detection only helps when it leads to care.</h2>
        <p className="mx-auto mt-3 max-w-xl text-slate-600">OziCare makes sure every screened person reaches the clinician who can help, and proves it happened.</p>
        <div className="mt-8 flex flex-wrap justify-center gap-3">
          <Link href="/login" className="rounded-full bg-teal-700 px-6 py-3 text-sm font-semibold text-white hover:bg-teal-800">
            Staff sign in
          </Link>
          <Link href="/p" className="rounded-full bg-white px-6 py-3 text-sm font-semibold text-slate-800 ring-1 ring-black/10 hover:bg-slate-50">
            Patient sign in
          </Link>
        </div>
      </section>

      <footer className="border-t border-black/5">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-4 px-4 py-6 text-sm text-slate-500 sm:px-6">
          <span className="font-semibold text-slate-700">OziCare</span>
          <span>Screening-to-care follow-up</span>
          <span className="ml-auto">Guidance only, not a diagnosis. In an emergency, call emergency services.</span>
        </div>
      </footer>
    </div>
  );
}
