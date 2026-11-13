import Link from "next/link";

const STEPS = [
  { n: "01", title: "Result received", body: "Screening results arrive from the lab, the screening unit or the health record, in FHIR, CSV or by hand." },
  { n: "02", title: "Risk identified", body: "Agreed criteria for hypertension, diabetes, obesity and cancer screening set the pathway and urgency, with the reason recorded." },
  { n: "03", title: "Referral sent", body: "The right service, at a facility in the person's region that takes their insurance. The receiving clinician accepts or declines." },
  { n: "04", title: "Care completed", body: "WhatsApp messages and voice calls in English and Arabic explain the result, book the visit, remind, and re-book after a missed appointment." },
  { n: "05", title: "Outcome tracked", body: "Every case has an owner and a deadline, and closes with evidence. People at risk of being lost are flagged for outreach." },
];

const MEASURES = [
  ["Referral completion", "Did the person reach the recommended service?"],
  ["Time to assessment", "How quickly did follow-up happen?"],
  ["Treatment completion", "Did the person complete the next care step?"],
  ["Lost-to-follow-up risk", "Who needs an outreach reminder or care-team alert?"],
];

export default function Home() {
  return (
    <div className="min-h-screen bg-white text-slate-900">
      <header className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-5 sm:px-6">
        <span className="grid h-9 w-9 place-items-center rounded-xl bg-teal-700 text-sm font-bold text-white">OC</span>
        <span className="text-lg font-semibold">OziCare</span>
        <Link href="/p" className="ml-auto rounded-lg bg-teal-700 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-teal-800">
          Patient sign in
        </Link>
        <Link href="/login" className="rounded-lg px-3 py-2 text-sm font-medium text-teal-800 ring-1 ring-inset ring-teal-200 hover:bg-teal-50">
          Staff sign in
        </Link>
      </header>

      <section className="bg-gradient-to-b from-teal-50 to-white">
        <div className="mx-auto grid max-w-6xl items-center gap-10 px-4 py-14 sm:px-6 lg:grid-cols-[1.1fr_1fr] lg:py-20">
          <div>
            <p className="text-sm font-semibold uppercase tracking-wide text-teal-700">Screening-to-care</p>
            <h1 className="mt-3 text-4xl font-semibold leading-tight tracking-tight sm:text-5xl">No screened person lost between steps.</h1>
            <p className="mt-5 max-w-xl text-lg leading-relaxed text-slate-600">
              OziCare turns every actionable screening result into timely contact, the right referral, an attended appointment and a recorded outcome, on WhatsApp and by phone, in English and Arabic.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link href="/login" className="rounded-lg bg-teal-700 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-teal-800">
                Open the care team dashboard
              </Link>
              <a href="#integrate" className="rounded-lg px-4 py-2.5 text-sm font-semibold text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50">
                How it integrates
              </a>
            </div>
          </div>

          {/* A phone showing the patient's page, so the patient side is visible on the landing page. */}
          <div className="mx-auto w-full max-w-[320px] rounded-[2.2rem] bg-slate-900 p-3 shadow-2xl">
            <div className="overflow-hidden rounded-[1.7rem] bg-slate-50">
              <div className="bg-teal-700 px-5 pb-5 pt-6 text-white">
                <div className="text-xs opacity-80">OziCare</div>
                <div className="mt-1 text-lg font-semibold">Hello Mariam</div>
                <div className="text-sm opacity-90">Your cervical screening follow-up</div>
              </div>
              <div className="space-y-3 p-4 text-sm">
                <div className="flex justify-between text-[11px] font-medium text-slate-500">
                  {["Result", "Referral", "Booked", "Visit", "Done"].map((s, i) => (
                    <span key={s} className="flex flex-col items-center gap-1">
                      <span className={`h-2.5 w-2.5 rounded-full ${i < 3 ? "bg-teal-600" : "bg-slate-300"}`} />
                      {s}
                    </span>
                  ))}
                </div>
                <div className="rounded-xl bg-white p-3 ring-1 ring-slate-200">
                  <div className="text-xs font-medium text-slate-500">Your appointment</div>
                  <div className="mt-0.5 font-semibold">Tue 3 Nov · 09:30</div>
                  <div className="text-slate-600">Al Ain Regional Hospital · Colposcopy</div>
                </div>
                <div className="rounded-xl bg-white p-3 ring-1 ring-slate-200">
                  <div className="text-xs font-medium text-slate-500">What to bring</div>
                  <div className="text-slate-700">Your ID and your WhatsApp message.</div>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <span className="rounded-lg bg-teal-700 py-2 text-center text-xs font-semibold text-white">Call me</span>
                  <span className="rounded-lg bg-white py-2 text-center text-xs font-semibold text-slate-700 ring-1 ring-slate-300">Ask a question</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
        <h2 className="text-2xl font-semibold tracking-tight">The loop, end to end</h2>
        <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {STEPS.map((s) => (
            <div key={s.n} className="rounded-xl border border-slate-200 p-5">
              <div className="text-sm font-semibold text-teal-700">{s.n}</div>
              <div className="mt-1 font-semibold">{s.title}</div>
              <p className="mt-2 text-sm leading-relaxed text-slate-600">{s.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="bg-slate-50">
        <div className="mx-auto grid max-w-6xl gap-10 px-4 py-16 sm:px-6 lg:grid-cols-2">
          <div>
            <h2 className="text-2xl font-semibold tracking-tight">For patients</h2>
            <ul className="mt-5 space-y-3 text-slate-700">
              <li>• A WhatsApp message in their language, with nothing shared until they confirm who they are.</li>
              <li>• Their own OziCare page from that message: the result in plain words, the referral, booking and reminders.</li>
              <li>• A voice assistant on WhatsApp or a phone call for anyone who would rather talk.</li>
              <li>• A person whenever they ask, and straight away if they describe an emergency.</li>
            </ul>
          </div>
          <div>
            <h2 className="text-2xl font-semibold tracking-tight">For care teams</h2>
            <ul className="mt-5 space-y-3 text-slate-700">
              <li>• One board: every open result, its owner, its deadline, and who is at risk of being lost.</li>
              <li>• Referrals that clinicians accept or decline, with consult notes between clinicians.</li>
              <li>• Attendance and outcomes recorded, with a full audit trail for every change.</li>
              <li>• The four loop measures, live:</li>
            </ul>
            <div className="mt-4 grid gap-2 sm:grid-cols-2">
              {MEASURES.map(([t, q]) => (
                <div key={t} className="rounded-lg bg-white p-3 ring-1 ring-slate-200">
                  <div className="text-sm font-semibold">{t}</div>
                  <div className="text-xs text-slate-500">{q}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section id="integrate" className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
        <h2 className="text-2xl font-semibold tracking-tight">Built to plug into existing health apps</h2>
        <p className="mt-3 max-w-3xl text-slate-600">
          OziCare is the follow-up engine, not another app to download. It speaks HL7 FHIR R4, so a national health app or shared health record can send results in and show the loop back to the patient. The OziCare patient page shows what that looks like.
        </p>
        <div className="mt-8 grid gap-4 md:grid-cols-3">
          <div className="rounded-xl border border-slate-200 p-5">
            <div className="text-xs font-semibold uppercase text-teal-700">In</div>
            <div className="mt-1 font-semibold">Screening results</div>
            <p className="mt-2 text-sm text-slate-600">
              <code className="rounded bg-slate-100 px-1">Bundle</code> with Patient (Emirates ID), LOINC Observations and Coverage.
            </p>
          </div>
          <div className="rounded-xl border border-slate-200 p-5">
            <div className="text-xs font-semibold uppercase text-teal-700">Out</div>
            <div className="mt-1 font-semibold">Referral, booking, progress</div>
            <p className="mt-2 text-sm text-slate-600">
              <code className="rounded bg-slate-100 px-1">ServiceRequest</code>, <code className="rounded bg-slate-100 px-1">Appointment</code> and <code className="rounded bg-slate-100 px-1">Task</code> for the app to display.
            </p>
          </div>
          <div className="rounded-xl border border-slate-200 p-5">
            <div className="text-xs font-semibold uppercase text-teal-700">Back</div>
            <div className="mt-1 font-semibold">Visit outcome</div>
            <p className="mt-2 text-sm text-slate-600">
              An <code className="rounded bg-slate-100 px-1">Encounter</code> from the facility marks the visit attended, or a no-show, and the loop reacts.
            </p>
          </div>
        </div>
      </section>

      <footer className="border-t border-slate-200">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-4 px-4 py-6 text-sm text-slate-500 sm:px-6">
          <span>OziCare · Screening-to-care follow-up</span>
          <span className="ml-auto">Guidance only, not a diagnosis. In an emergency, call emergency services.</span>
        </div>
      </footer>
    </div>
  );
}
