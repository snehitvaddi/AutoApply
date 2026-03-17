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
    icon: (
      <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
      </svg>
    ),
  },
  {
    num: "02",
    title: "Set Your Preferences",
    desc: "Target roles, salary range, excluded companies. You control what gets applied to.",
    icon: (
      <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 6h9.75M10.5 6a1.5 1.5 0 11-3 0m3 0a1.5 1.5 0 10-3 0M3.75 6H7.5m3 12h9.75m-9.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-3.75 0H7.5m9-6h3.75m-3.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-9.75 0h9.75" />
      </svg>
    ),
  },
  {
    num: "03",
    title: "AI Applies For You",
    desc: "Our worker scans job boards, fills forms, tailors resumes, and submits — 24/7.",
    icon: (
      <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456z" />
      </svg>
    ),
  },
  {
    num: "04",
    title: "Track & Get Interviews",
    desc: "Monitor every application. See screenshots, statuses, and interview invites in one dashboard.",
    icon: (
      <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
      </svg>
    ),
  },
];

const FEATURES = [
  {
    title: "Smart Resume Tailoring",
    desc: "AI rewrites your resume for each job. Matches keywords, highlights relevant experience, passes ATS filters.",
    gradient: "from-brand-500 to-brand-700",
  },
  {
    title: "Auto Cover Letters",
    desc: "No more generic templates. Every cover letter references the company's mission, recent news, and role requirements.",
    gradient: "from-accent-500 to-accent-700",
  },
  {
    title: "Multi-ATS Support",
    desc: "Works with Greenhouse, Lever, Ashby, SmartRecruiters, and more. One setup, every platform.",
    gradient: "from-brand-600 to-accent-500",
  },
  {
    title: "Smart Form Answers",
    desc: "\"Why do you want to work here?\" — answered intelligently for each company, not copy-pasted.",
    gradient: "from-accent-400 to-brand-500",
  },
  {
    title: "Real-Time Dashboard",
    desc: "See every application: status, screenshots, errors. Know exactly what was submitted and when.",
    gradient: "from-brand-400 to-brand-600",
  },
  {
    title: "Daily Auto-Updates",
    desc: "Your worker stays current. Code, dependencies, and AI models update automatically — zero maintenance.",
    gradient: "from-accent-500 to-brand-600",
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

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-white">
      {/* Navigation */}
      <nav className="fixed top-0 w-full bg-white/80 backdrop-blur-lg border-b border-gray-100 z-50">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-gradient-to-br from-brand-500 to-brand-700 rounded-lg flex items-center justify-center">
              <span className="text-white font-bold text-sm">A</span>
            </div>
            <span className="font-bold text-xl text-surface-900">AutoApply</span>
          </div>
          <div className="hidden md:flex items-center gap-8 text-sm text-gray-600">
            <a href="#how-it-works" className="hover:text-brand-600 transition-colors">How It Works</a>
            <a href="#features" className="hover:text-brand-600 transition-colors">Features</a>
            <a href="#pricing" className="hover:text-brand-600 transition-colors">Pricing</a>
          </div>
          <div className="flex items-center gap-3">
            <Link
              href="/auth/login"
              className="text-sm font-medium text-gray-700 hover:text-brand-600 transition-colors"
            >
              Sign In
            </Link>
            <Link
              href="/auth/login"
              className="text-sm font-semibold px-5 py-2.5 bg-brand-600 text-white rounded-full hover:bg-brand-700 transition-all shadow-sm hover:shadow-md"
            >
              Get Started Free
            </Link>
          </div>
        </div>
      </nav>

      {/* Hero Section */}
      <section className="hero-gradient pt-32 pb-20 px-6">
        <div className="max-w-4xl mx-auto text-center animate-fade-in">
          <div className="inline-flex items-center gap-2 px-4 py-1.5 bg-brand-50 text-brand-700 rounded-full text-sm font-medium mb-8 border border-brand-100">
            <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse-slow" />
            Now auto-applying to 200+ jobs/week
          </div>

          <h1 className="text-5xl md:text-7xl font-extrabold text-surface-950 leading-tight tracking-tight">
            Stop applying manually.
            <br />
            <span className="gradient-text">Start getting interviews.</span>
          </h1>

          <p className="mt-6 text-xl text-gray-500 max-w-2xl mx-auto leading-relaxed">
            AutoApply fills out job applications, tailors your resume, and writes cover
            letters while you sleep. Powered by AI. Built for results.
          </p>

          <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link
              href="/auth/login"
              className="px-8 py-4 bg-brand-600 text-white font-semibold rounded-full text-lg hover:bg-brand-700 transition-all shadow-lg hover:shadow-xl hover:-translate-y-0.5"
            >
              Start Applying Free
            </Link>
            <a
              href="#how-it-works"
              className="px-8 py-4 border-2 border-gray-200 text-gray-700 font-semibold rounded-full text-lg hover:border-brand-300 hover:text-brand-600 transition-all"
            >
              See How It Works
            </a>
          </div>

          {/* Stats */}
          <div className="mt-16 grid grid-cols-2 md:grid-cols-4 gap-6 max-w-3xl mx-auto">
            {STATS.map((s) => (
              <div key={s.label} className="text-center">
                <p className="text-3xl md:text-4xl font-extrabold text-brand-600">{s.value}</p>
                <p className="text-sm text-gray-500 mt-1">{s.label}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Social Proof */}
      <section className="py-12 border-y border-gray-100 bg-surface-50">
        <div className="max-w-4xl mx-auto px-6 text-center">
          <p className="text-sm font-medium text-gray-400 uppercase tracking-widest mb-6">
            Trusted by job seekers applying to
          </p>
          <div className="flex flex-wrap items-center justify-center gap-x-10 gap-y-4 text-gray-300 font-semibold text-lg">
            {["Google", "Amazon", "Meta", "Stripe", "Coinbase", "Netflix", "Airbnb", "Uber"].map((co) => (
              <span key={co} className="hover:text-gray-500 transition-colors">{co}</span>
            ))}
          </div>
        </div>
      </section>

      {/* How It Works */}
      <section id="how-it-works" className="py-24 px-6">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-16">
            <p className="text-sm font-semibold text-accent-500 uppercase tracking-widest mb-3">How It Works</p>
            <h2 className="text-4xl md:text-5xl font-extrabold text-surface-950">
              Four steps to autopilot
            </h2>
            <p className="mt-4 text-lg text-gray-500 max-w-2xl mx-auto">
              Set it up once. Let AI handle the rest. You focus on interviews.
            </p>
          </div>

          <div className="grid md:grid-cols-2 gap-6">
            {STEPS.map((step) => (
              <div
                key={step.num}
                className="card-hover bg-white rounded-2xl border border-gray-100 p-8 flex gap-5"
              >
                <div className="flex-shrink-0">
                  <div className="w-14 h-14 bg-brand-50 text-brand-600 rounded-xl flex items-center justify-center">
                    {step.icon}
                  </div>
                </div>
                <div>
                  <span className="text-xs font-bold text-brand-400 uppercase tracking-widest">Step {step.num}</span>
                  <h3 className="text-xl font-bold text-surface-900 mt-1">{step.title}</h3>
                  <p className="text-gray-500 mt-2 leading-relaxed">{step.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Features */}
      <section id="features" className="py-24 px-6 bg-surface-950 text-white">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-16">
            <p className="text-sm font-semibold text-accent-400 uppercase tracking-widest mb-3">Features</p>
            <h2 className="text-4xl md:text-5xl font-extrabold">
              Everything you need to land interviews
            </h2>
            <p className="mt-4 text-lg text-gray-400 max-w-2xl mx-auto">
              No fluff. No generic templates. Just tools that get results.
            </p>
          </div>

          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
            {FEATURES.map((f) => (
              <div
                key={f.title}
                className="card-hover bg-surface-900 rounded-2xl border border-surface-800 p-7"
              >
                <div className={`w-10 h-10 rounded-lg bg-gradient-to-br ${f.gradient} flex items-center justify-center mb-4`}>
                  <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                  </svg>
                </div>
                <h3 className="text-lg font-bold text-white">{f.title}</h3>
                <p className="text-gray-400 mt-2 leading-relaxed text-sm">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing */}
      <section id="pricing" className="py-24 px-6">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-16">
            <p className="text-sm font-semibold text-brand-600 uppercase tracking-widest mb-3">Pricing</p>
            <h2 className="text-4xl md:text-5xl font-extrabold text-surface-950">
              Simple, transparent pricing
            </h2>
            <p className="mt-4 text-lg text-gray-500">
              Start free. Upgrade when you&apos;re ready to go all-in.
            </p>
          </div>

          <div className="grid md:grid-cols-3 gap-6">
            {PRICING.map((plan) => (
              <div
                key={plan.name}
                className={`rounded-2xl border p-8 flex flex-col ${
                  plan.highlighted
                    ? "border-brand-600 bg-brand-50 shadow-lg glow-blue relative"
                    : "border-gray-200 bg-white"
                }`}
              >
                {plan.highlighted && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-4 py-1 bg-brand-600 text-white text-xs font-bold rounded-full uppercase tracking-wider">
                    Most Popular
                  </div>
                )}
                <h3 className="text-xl font-bold text-surface-900">{plan.name}</h3>
                <p className="text-sm text-gray-500 mt-1">{plan.desc}</p>
                <div className="mt-6">
                  {plan.price === "Custom" ? (
                    <p className="text-4xl font-extrabold text-surface-900">Custom</p>
                  ) : (
                    <p className="text-4xl font-extrabold text-surface-900">
                      ${plan.price}
                      <span className="text-lg font-normal text-gray-400">/mo</span>
                    </p>
                  )}
                </div>
                <ul className="mt-6 space-y-3 flex-1">
                  {plan.features.map((feat) => (
                    <li key={feat} className="flex items-start gap-2 text-sm text-gray-600">
                      <svg className="w-4 h-4 text-brand-600 mt-0.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                      </svg>
                      {feat}
                    </li>
                  ))}
                </ul>
                <Link
                  href="/auth/login"
                  className={`mt-8 block text-center py-3 rounded-full font-semibold text-sm transition-all ${
                    plan.highlighted
                      ? "bg-brand-600 text-white hover:bg-brand-700 shadow-md hover:shadow-lg"
                      : "border-2 border-gray-200 text-gray-700 hover:border-brand-300 hover:text-brand-600"
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
      <section className="py-24 px-6 bg-gradient-to-br from-brand-600 to-brand-800">
        <div className="max-w-3xl mx-auto text-center">
          <h2 className="text-4xl md:text-5xl font-extrabold text-white">
            Ready to stop applying manually?
          </h2>
          <p className="mt-4 text-xl text-brand-100">
            Join job seekers who went from 200 applications with 3 responses
            to 80 applications with 12 interviews.
          </p>
          <Link
            href="/auth/login"
            className="mt-10 inline-block px-10 py-4 bg-white text-brand-700 font-bold rounded-full text-lg hover:bg-brand-50 transition-all shadow-xl hover:shadow-2xl hover:-translate-y-0.5"
          >
            Get Started Free
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="py-12 px-6 bg-surface-950 text-gray-400">
        <div className="max-w-5xl mx-auto flex flex-col md:flex-row items-center justify-between gap-6">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 bg-gradient-to-br from-brand-500 to-brand-700 rounded-lg flex items-center justify-center">
              <span className="text-white font-bold text-xs">A</span>
            </div>
            <span className="font-bold text-white">AutoApply</span>
          </div>
          <div className="flex gap-8 text-sm">
            <a href="#features" className="hover:text-white transition-colors">Features</a>
            <a href="#pricing" className="hover:text-white transition-colors">Pricing</a>
            <Link href="/auth/login" className="hover:text-white transition-colors">Dashboard</Link>
          </div>
          <p className="text-sm">&copy; {new Date().getFullYear()} AutoApply. All rights reserved.</p>
        </div>
      </footer>
    </div>
  );
}
