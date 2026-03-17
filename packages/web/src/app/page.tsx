import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "AutoApply — Stop Applying Manually. Start Getting Interviews.",
  description:
    "AI-powered job application engine. AutoApply fills out applications, tailors resumes, and writes cover letters while you sleep.",
};

const STATS = [
  { value: "10x", label: "Faster than manual" },
  { value: "85%", label: "ATS pass rate" },
  { value: "200+", label: "Applications/week" },
  { value: "3x", label: "More interviews" },
];

const STEPS = [
  {
    num: "01",
    title: "Upload Your Resume",
    desc: "Drop your PDF. Our AI parses skills, experience, and preferences instantly.",
  },
  {
    num: "02",
    title: "Set Your Preferences",
    desc: "Target roles, salary range, excluded companies. You control what gets applied to.",
  },
  {
    num: "03",
    title: "AI Applies For You",
    desc: "Our worker scans job boards, fills forms, tailors resumes, and submits — 24/7.",
  },
  {
    num: "04",
    title: "Track & Get Interviews",
    desc: "Monitor every application. See screenshots, statuses, and interview invites.",
  },
];

const FEATURES = [
  {
    title: "Smart Resume Tailoring",
    desc: "AI rewrites your resume for each job. Matches keywords, highlights relevant experience, passes ATS filters.",
  },
  {
    title: "Auto Cover Letters",
    desc: "Every cover letter references the company's mission, recent news, and role requirements. Never generic.",
  },
  {
    title: "Multi-ATS Support",
    desc: "Works with Greenhouse, Lever, Ashby, SmartRecruiters, and more. One setup, every platform.",
  },
  {
    title: "Smart Form Answers",
    desc: "\"Why do you want to work here?\" — answered intelligently for each company, not copy-pasted.",
  },
  {
    title: "Real-Time Dashboard",
    desc: "See every application: status, screenshots, errors. Know exactly what was submitted and when.",
  },
  {
    title: "Telegram Notifications",
    desc: "Send a job link. Get a screenshot proof 90 seconds later. Track everything from your phone.",
  },
];

const PRICING = [
  {
    name: "Starter",
    price: "15",
    desc: "For casual job seekers",
    features: [
      "25 applications/day",
      "Resume tailoring",
      "Basic form filling",
      "Email notifications",
      "Dashboard access",
    ],
    cta: "Get Started",
    highlighted: false,
  },
  {
    name: "Pro",
    price: "29",
    desc: "For serious job hunters",
    features: [
      "Unlimited applications",
      "Smart cover letters",
      "AI form answers",
      "Resume tailoring per job",
      "Priority support",
      "Gmail integration",
      "Telegram alerts",
    ],
    cta: "Start Free Trial",
    highlighted: true,
  },
  {
    name: "Enterprise",
    price: "Custom",
    desc: "For career services & agencies",
    features: [
      "Everything in Pro",
      "Multi-user management",
      "Custom ATS integrations",
      "Dedicated support",
      "SLA guarantees",
      "White-label option",
    ],
    cta: "Contact Sales",
    highlighted: false,
  },
];

/* Simple company logo SVGs for social proof */
const CompanyLogos = () => (
  <div className="flex flex-wrap items-center justify-center gap-x-12 gap-y-6 opacity-40">
    {/* Google */}
    <svg className="h-7" viewBox="0 0 272 92" fill="currentColor">
      <path d="M115.75 47.18c0 12.77-9.99 22.18-22.25 22.18s-22.25-9.41-22.25-22.18C71.25 34.32 81.24 25 93.5 25s22.25 9.32 22.25 22.18zm-9.74 0c0-7.98-5.79-13.44-12.51-13.44S80.99 39.2 80.99 47.18c0 7.9 5.79 13.44 12.51 13.44s12.51-5.55 12.51-13.44z"/>
      <path d="M163.75 47.18c0 12.77-9.99 22.18-22.25 22.18s-22.25-9.41-22.25-22.18c0-12.85 9.99-22.18 22.25-22.18s22.25 9.32 22.25 22.18zm-9.74 0c0-7.98-5.79-13.44-12.51-13.44s-12.51 5.46-12.51 13.44c0 7.9 5.79 13.44 12.51 13.44s12.51-5.55 12.51-13.44z"/>
      <path d="M209.75 26.34v39.82c0 16.38-9.66 23.07-21.08 23.07-10.75 0-17.22-7.19-19.66-13.07l8.48-3.53c1.51 3.61 5.21 7.87 11.17 7.87 7.31 0 11.84-4.51 11.84-13v-3.19h-.34c-2.18 2.69-6.38 5.04-11.68 5.04-11.09 0-21.25-9.66-21.25-22.09 0-12.52 10.16-22.26 21.25-22.26 5.29 0 9.49 2.35 11.68 4.96h.34v-3.61h9.25zm-8.56 20.92c0-7.81-5.21-13.52-11.84-13.52-6.72 0-12.35 5.71-12.35 13.52 0 7.73 5.63 13.36 12.35 13.36 6.63 0 11.84-5.63 11.84-13.36z"/>
      <path d="M225 3v65h-9.5V3h9.5z"/>
      <path d="M262.02 54.48l7.56 5.04c-2.44 3.61-8.32 9.83-18.48 9.83-12.6 0-22.01-9.74-22.01-22.18 0-13.19 9.49-22.18 20.92-22.18 11.51 0 17.14 9.16 18.98 14.11l1.01 2.52-29.65 12.28c2.27 4.45 5.8 6.72 10.75 6.72 4.96 0 8.4-2.44 10.92-6.14zm-23.27-7.98l19.82-8.23c-1.09-2.77-4.37-4.7-8.23-4.7-4.95 0-11.84 4.37-11.59 12.93z"/>
      <path d="M35.29 41.19V32H67c.31 1.64.47 3.58.47 5.68 0 7.06-1.93 15.79-8.15 22.01-6.05 6.3-13.78 9.66-24.02 9.66C16.32 69.35.36 53.89.36 34.91.36 15.93 16.32.47 35.3.47c10.5 0 17.98 4.12 23.6 9.49l-6.64 6.64c-4.03-3.78-9.49-6.72-16.97-6.72-13.86 0-24.7 11.17-24.7 25.03 0 13.86 10.84 25.03 24.7 25.03 8.99 0 14.11-3.61 17.39-6.89 2.66-2.66 4.41-6.46 5.1-11.65l-22.49-.01z"/>
    </svg>
    {/* Amazon */}
    <svg className="h-6" viewBox="0 0 603 182" fill="currentColor">
      <path d="M374.01 142.06c-34.53 25.49-84.6 39.05-127.7 39.05-60.43 0-114.87-22.35-156.05-59.52-3.23-2.92-.34-6.9 3.54-4.63 44.44 25.83 99.35 41.39 156.1 41.39 38.27 0 80.37-7.93 119.07-24.38 5.84-2.48 10.72 3.83 5.04 8.09z"/>
      <path d="M388.42 125.72c-4.41-5.65-29.19-2.67-40.31-1.35-3.38.41-3.9-2.54-.85-4.66 19.74-13.88 52.1-9.88 55.88-5.23 3.78 4.67-.99 37.05-19.52 52.49-2.85 2.37-5.56 1.11-4.3-2.04 4.17-10.42 13.52-33.58 9.1-39.21z"/>
      <path d="M349.19 23.74V7.42c0-2.47 1.88-4.13 4.14-4.13h73.14c2.35 0 4.23 1.69 4.23 4.13v13.97c-.03 2.35-2.01 5.42-5.52 10.28l-37.88 54.1c14.07-.34 28.93 1.76 41.67 8.97 2.87 1.63 3.65 4.01 3.87 6.36v17.42c0 2.38-2.63 5.17-5.39 3.73-22.51-11.81-52.42-13.1-77.27.14-2.53 1.35-5.19-1.38-5.19-3.76v-16.55c0-2.67.03-7.22 2.72-11.28l43.88-62.97H353.36c-2.35 0-4.23-1.66-4.23-4.06z"/>
    </svg>
    {/* Meta */}
    <span className="text-2xl font-bold tracking-tight">Meta</span>
    {/* Stripe */}
    <span className="text-2xl font-bold tracking-tight">Stripe</span>
    {/* Coinbase */}
    <span className="text-2xl font-bold tracking-tight">Coinbase</span>
    {/* Netflix */}
    <span className="text-2xl font-bold tracking-tight">Netflix</span>
    {/* Airbnb */}
    <span className="text-2xl font-bold tracking-tight">Airbnb</span>
  </div>
);

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-white">
      {/* Navigation */}
      <nav className="fixed top-0 w-full bg-white/90 backdrop-blur-md border-b border-gray-100 z-50">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 bg-brand-900 rounded-lg flex items-center justify-center">
              <span className="text-white font-bold text-sm font-display">A</span>
            </div>
            <span className="font-display font-bold text-xl text-brand-950">AutoApply</span>
          </div>
          <div className="hidden md:flex items-center gap-8 text-sm font-medium text-gray-500">
            <a href="#how-it-works" className="hover:text-brand-900 transition-colors">How It Works</a>
            <a href="#features" className="hover:text-brand-900 transition-colors">Features</a>
            <a href="#pricing" className="hover:text-brand-900 transition-colors">Pricing</a>
          </div>
          <div className="flex items-center gap-4">
            <Link
              href="/auth/login"
              className="text-sm font-medium text-gray-600 hover:text-brand-900 transition-colors"
            >
              Sign In
            </Link>
            <Link
              href="/auth/login"
              className="text-sm font-semibold px-5 py-2.5 bg-brand-900 text-white rounded-lg hover:bg-brand-950 transition-colors"
            >
              Get Started Free
            </Link>
          </div>
        </div>
      </nav>

      {/* Hero Section */}
      <section className="pt-32 pb-20 px-6 bg-white">
        <div className="max-w-4xl mx-auto text-center animate-fade-in">
          <div className="inline-flex items-center gap-2 px-4 py-1.5 bg-gray-50 text-gray-600 rounded-full text-sm font-medium mb-8 border border-gray-200">
            <span className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse" />
            Now auto-applying to 200+ jobs/week
          </div>

          <h1 className="font-display text-5xl md:text-7xl font-extrabold text-brand-950 leading-[1.1] tracking-tight">
            Stop applying manually.
            <br />
            <span className="text-brand-500">Start getting interviews.</span>
          </h1>

          <p className="mt-6 text-lg md:text-xl text-gray-500 max-w-2xl mx-auto leading-relaxed font-body">
            AutoApply fills out job applications, tailors your resume, and writes cover
            letters while you sleep. Powered by AI. Built for results.
          </p>

          <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link
              href="/auth/login"
              className="px-8 py-4 bg-brand-900 text-white font-semibold rounded-lg text-base hover:bg-brand-950 transition-colors shadow-sm"
            >
              Start Applying Free
            </Link>
            <a
              href="#how-it-works"
              className="px-8 py-4 border border-gray-200 text-gray-700 font-semibold rounded-lg text-base hover:border-gray-400 hover:text-brand-900 transition-colors"
            >
              See How It Works
            </a>
          </div>

          {/* Stats */}
          <div className="mt-20 grid grid-cols-2 md:grid-cols-4 gap-8 max-w-3xl mx-auto">
            {STATS.map((s) => (
              <div key={s.label} className="text-center">
                <p className="font-display text-3xl md:text-4xl font-extrabold text-brand-900">{s.value}</p>
                <p className="text-sm text-gray-400 mt-1 font-body">{s.label}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Social Proof */}
      <section className="py-14 border-y border-gray-100">
        <div className="max-w-5xl mx-auto px-6 text-center">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-[0.2em] mb-8 font-body">
            Trusted by job seekers applying to
          </p>
          <CompanyLogos />
        </div>
      </section>

      {/* How It Works */}
      <section id="how-it-works" className="py-24 px-6">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-16">
            <p className="text-xs font-semibold text-brand-500 uppercase tracking-[0.2em] mb-3 font-body">How It Works</p>
            <h2 className="font-display text-4xl md:text-5xl font-extrabold text-brand-950">
              Four steps to autopilot
            </h2>
            <p className="mt-4 text-lg text-gray-500 max-w-2xl mx-auto font-body">
              Set it up once. Let AI handle the rest. You focus on interviews.
            </p>
          </div>

          <div className="grid md:grid-cols-2 gap-5">
            {STEPS.map((step) => (
              <div
                key={step.num}
                className="card-hover bg-white rounded-2xl border border-gray-100 p-8 hover:border-gray-200"
              >
                <span className="font-display text-xs font-bold text-brand-400 uppercase tracking-[0.15em]">Step {step.num}</span>
                <h3 className="font-display text-xl font-bold text-brand-950 mt-2">{step.title}</h3>
                <p className="text-gray-500 mt-3 leading-relaxed font-body">{step.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Features */}
      <section id="features" className="py-24 px-6 bg-brand-950">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-16">
            <p className="text-xs font-semibold text-brand-400 uppercase tracking-[0.2em] mb-3 font-body">Features</p>
            <h2 className="font-display text-4xl md:text-5xl font-extrabold text-white">
              Everything you need to land interviews
            </h2>
            <p className="mt-4 text-lg text-brand-300 max-w-2xl mx-auto font-body">
              No fluff. No generic templates. Just tools that get results.
            </p>
          </div>

          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-5">
            {FEATURES.map((f) => (
              <div
                key={f.title}
                className="card-hover bg-brand-900 rounded-2xl border border-brand-800 p-7"
              >
                <div className="w-10 h-10 rounded-lg bg-brand-800 flex items-center justify-center mb-4">
                  <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                  </svg>
                </div>
                <h3 className="font-display text-lg font-bold text-white">{f.title}</h3>
                <p className="text-brand-300 mt-2 leading-relaxed text-sm font-body">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing */}
      <section id="pricing" className="py-24 px-6">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-16">
            <p className="text-xs font-semibold text-brand-500 uppercase tracking-[0.2em] mb-3 font-body">Pricing</p>
            <h2 className="font-display text-4xl md:text-5xl font-extrabold text-brand-950">
              Simple, transparent pricing
            </h2>
            <p className="mt-4 text-lg text-gray-500 font-body">
              Start free. Upgrade when you&apos;re ready to go all-in.
            </p>
          </div>

          <div className="grid md:grid-cols-3 gap-5">
            {PRICING.map((plan) => (
              <div
                key={plan.name}
                className={`rounded-2xl border p-8 flex flex-col ${
                  plan.highlighted
                    ? "border-brand-900 bg-brand-950 text-white shadow-xl relative"
                    : "border-gray-200 bg-white"
                }`}
              >
                {plan.highlighted && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-4 py-1 bg-brand-900 text-white text-xs font-bold rounded-full uppercase tracking-wider font-body">
                    Most Popular
                  </div>
                )}
                <h3 className={`font-display text-xl font-bold ${plan.highlighted ? "text-white" : "text-brand-950"}`}>{plan.name}</h3>
                <p className={`text-sm mt-1 font-body ${plan.highlighted ? "text-brand-300" : "text-gray-500"}`}>{plan.desc}</p>
                <div className="mt-6">
                  {plan.price === "Custom" ? (
                    <p className={`font-display text-4xl font-extrabold ${plan.highlighted ? "text-white" : "text-brand-950"}`}>Custom</p>
                  ) : (
                    <p className={`font-display text-4xl font-extrabold ${plan.highlighted ? "text-white" : "text-brand-950"}`}>
                      ${plan.price}
                      <span className={`text-lg font-normal ${plan.highlighted ? "text-brand-400" : "text-gray-400"}`}>/mo</span>
                    </p>
                  )}
                </div>
                <ul className="mt-6 space-y-3 flex-1">
                  {plan.features.map((feat) => (
                    <li key={feat} className={`flex items-start gap-2.5 text-sm font-body ${plan.highlighted ? "text-brand-200" : "text-gray-600"}`}>
                      <svg className={`w-4 h-4 mt-0.5 flex-shrink-0 ${plan.highlighted ? "text-white" : "text-brand-700"}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                      </svg>
                      {feat}
                    </li>
                  ))}
                </ul>
                <Link
                  href="/auth/login"
                  className={`mt-8 block text-center py-3 rounded-lg font-semibold text-sm transition-colors font-body ${
                    plan.highlighted
                      ? "bg-white text-brand-900 hover:bg-gray-100"
                      : "border border-gray-200 text-gray-700 hover:border-brand-700 hover:text-brand-900"
                  }`}
                >
                  {plan.cta}
                </Link>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-24 px-6 bg-brand-950">
        <div className="max-w-3xl mx-auto text-center">
          <h2 className="font-display text-4xl md:text-5xl font-extrabold text-white">
            Ready to stop applying manually?
          </h2>
          <p className="mt-4 text-xl text-brand-300 font-body">
            Join job seekers who went from 200 applications with 3 responses
            to 80 applications with 12 interviews.
          </p>
          <Link
            href="/auth/login"
            className="mt-10 inline-block px-10 py-4 bg-white text-brand-900 font-bold rounded-lg text-lg hover:bg-gray-100 transition-colors font-body"
          >
            Get Started Free
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="py-12 px-6 bg-brand-950 border-t border-brand-800">
        <div className="max-w-5xl mx-auto flex flex-col md:flex-row items-center justify-between gap-6">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 bg-brand-800 rounded-lg flex items-center justify-center">
              <span className="text-white font-bold text-xs font-display">A</span>
            </div>
            <span className="font-display font-bold text-white">AutoApply</span>
          </div>
          <div className="flex gap-8 text-sm text-brand-400 font-body">
            <a href="#features" className="hover:text-white transition-colors">Features</a>
            <a href="#pricing" className="hover:text-white transition-colors">Pricing</a>
            <Link href="/auth/login" className="hover:text-white transition-colors">Dashboard</Link>
          </div>
          <p className="text-sm text-brand-500 font-body">&copy; {new Date().getFullYear()} AutoApply. All rights reserved.</p>
        </div>
      </footer>
    </div>
  );
}
