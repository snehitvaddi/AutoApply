"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";

const STATS = [
  { value: "900+", label: "Applications submitted" },
  { value: "85%", label: "ATS pass rate" },
  { value: "30-60/day", label: "On autopilot" },
  { value: "6", label: "Job sources" },
];

const STEPS = [
  {
    num: "01",
    title: "Upload your resume",
    desc: "Drop your PDF. AI parses your skills, experience, and preferences in seconds.",
    icon: (
      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
      </svg>
    ),
  },
  {
    num: "02",
    title: "Set your preferences",
    desc: "Target roles, salary, location, excluded companies. You control everything.",
    icon: (
      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 6h9.75M10.5 6a1.5 1.5 0 11-3 0m3 0a1.5 1.5 0 10-3 0M3.75 6H7.5m3 12h9.75m-9.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-3.75 0H7.5m9-6h3.75m-3.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-9.75 0h9.75" />
      </svg>
    ),
  },
  {
    num: "03",
    title: "AI applies for you",
    desc: "Scans 370+ company boards, fills forms, tailors resumes, submits — 24/7.",
    icon: (
      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
      </svg>
    ),
  },
  {
    num: "04",
    title: "Get screenshot proof",
    desc: "Every application logged with screenshots. Track status via Telegram or dashboard.",
    icon: (
      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M6.827 6.175A2.31 2.31 0 015.186 7.23c-.38.054-.757.112-1.134.175C2.999 7.58 2.25 8.507 2.25 9.574V18a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9.574c0-1.067-.75-1.994-1.802-2.169a47.865 47.865 0 00-1.134-.175 2.31 2.31 0 01-1.64-1.055l-.822-1.316a2.192 2.192 0 00-1.736-1.039 48.774 48.774 0 00-5.232 0 2.192 2.192 0 00-1.736 1.039l-.821 1.316z" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 12.75a4.5 4.5 0 11-9 0 4.5 4.5 0 019 0z" />
      </svg>
    ),
  },
];

const FEATURES = [
  { title: "Learns As You Use It", desc: "Correct it once, it remembers forever. By day 3, it runs nearly fully autonomous — tailored to your style." },
  { title: "Smart Resume Matching", desc: "Picks the right resume per job. AI Engineer? GenAI resume. Data Analyst? DS resume. Auto-tailored per application." },
  { title: "Gmail OTP Verification", desc: "Reads security codes from your email automatically. Handles Greenhouse 8-character codes no other bot can." },
  { title: "6 Job Sources", desc: "Greenhouse, Ashby, Indeed, Himalayas, Google Jobs, LinkedIn. 500+ company boards scanned every 30 minutes." },
  { title: "Telegram Proof", desc: "Screenshot of every submission sent to your phone. Full visibility, zero guesswork." },
  { title: "End-to-End Setup", desc: "DM us. We set up everything on a call: profile, resume, preferences, integrations. You just watch it run." },
];

const ATS_PLATFORMS = [
  { name: "Greenhouse", count: "346+ companies" },
  { name: "Ashby", count: "168+ companies" },
  { name: "Indeed", count: "All companies" },
  { name: "Himalayas", count: "Remote focused" },
  { name: "Google Jobs", count: "Fresh postings" },
  { name: "LinkedIn", count: "Public search" },
];

const ACTIVITY_FEED = [
  { company: "Stripe", role: "ML Engineer", status: "submitted", time: "12s ago", ats: "Greenhouse" },
  { company: "Anthropic", role: "AI Engineer", status: "submitted", time: "2m ago", ats: "Greenhouse" },
  { company: "Notion", role: "Data Scientist", status: "submitted", time: "4m ago", ats: "Ashby" },
  { company: "Ramp", role: "ML Platform", status: "submitted", time: "7m ago", ats: "Ashby" },
  { company: "Coinbase", role: "Applied Scientist", status: "submitted", time: "11m ago", ats: "Greenhouse" },
  { company: "Figma", role: "Research Engineer", status: "submitted", time: "15m ago", ats: "Greenhouse" },
];

const COMPANIES = ["Stripe", "Anthropic", "Coinbase", "Airbnb", "Notion", "Figma", "Ramp", "Vercel", "Linear", "Cursor", "OpenAI", "Netflix"];

const PRICING = [
  {
    name: "Monthly",
    desc: "Full access. Cancel anytime.",
    features: [
      "30-60 applications/day (varies by role availability)",
      "6 job sources, 500+ company boards",
      "AI learns your preferences — autopilot by day 3",
      "Resume tailoring per job",
      "Gmail OTP + security codes",
      "Telegram screenshot proof",
      "End-to-end setup by us",
      "Priority support",
    ],
    cta: "DM for Setup",
    dark: true,
  },
  {
    name: "Lifetime",
    desc: "Own it forever. One-time payment.",
    features: [
      "Everything in Monthly",
      "Full infrastructure setup on a call",
      "Profile + resume + preferences configured",
      "Gmail + Telegram + all integrations wired",
      "Test application together live",
      "Lifetime updates — bot gets smarter",
      "Community access",
    ],
    cta: "DM for Setup",
    dark: false,
  },
];

function ScrollObserver() {
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("visible");
          }
        });
      },
      { threshold: 0.1, rootMargin: "0px 0px -40px 0px" }
    );
    document.querySelectorAll(".animate-on-scroll").forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, []);
  return null;
}

function LiveActivityFeed() {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const interval = setInterval(() => {
      el.scrollTop += 1;
      if (el.scrollTop >= el.scrollHeight - el.clientHeight) {
        el.scrollTop = 0;
      }
    }, 50);
    return () => clearInterval(interval);
  }, []);

  return (
    <div ref={ref} className="h-[280px] overflow-hidden space-y-3">
      {[...ACTIVITY_FEED, ...ACTIVITY_FEED].map((item, i) => (
        <div key={i} className="flex items-center justify-between bg-white rounded-xl px-5 py-3.5 border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-gray-100 rounded-lg flex items-center justify-center text-xs font-bold text-gray-500 font-display">
              {item.company[0]}
            </div>
            <div>
              <p className="text-sm font-semibold text-gray-900">{item.company}</p>
              <p className="text-xs text-gray-400">{item.role}</p>
            </div>
          </div>
          <div className="text-right">
            <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-full">
              <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full live-pulse" />
              {item.status}
            </span>
            <p className="text-[10px] text-gray-300 mt-0.5">{item.time} via {item.ats}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

// schema.org SoftwareApplication JSON-LD. Rendered inline as a <script>
// on the landing page so Google can show rich results + knowledge-panel
// metadata in search. Keep the name/description in sync with layout.tsx
// metadata so the crawler sees consistent info across both signals.
const STRUCTURED_DATA = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: "ApplyLoop",
  description:
    "AI-powered job application engine. ApplyLoop fills out applications, tailors resumes per role, writes cover letters, and submits them automatically — 30-60 applications per day on autopilot.",
  url: "https://applyloop.vercel.app",
  applicationCategory: "BusinessApplication",
  operatingSystem: "macOS",
  offers: {
    "@type": "Offer",
    price: "0",
    priceCurrency: "USD",
    description: "Early adopter — free during beta",
  },
  creator: {
    "@type": "Organization",
    name: "ApplyLoop",
    url: "https://applyloop.vercel.app",
  },
  featureList: [
    "Automated job scouting across 6+ sources",
    "AI-tailored resumes per role",
    "Auto-generated cover letters",
    "Submits applications to Greenhouse, Lever, Ashby, SmartRecruiters",
    "Telegram notifications with screenshots",
    "Per-job dedup + filtering",
    "Daily application limits + cooldowns",
  ],
};

export default function LandingPage() {
  return (
    <div className="min-h-screen" style={{ backgroundColor: "#f7f7f7" }}>
      {/* schema.org structured data for rich results in Google Search */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(STRUCTURED_DATA) }}
      />
      <ScrollObserver />

      {/* Nav */}
      <nav className="fixed top-0 w-full bg-white/80 backdrop-blur-lg z-50 border-b border-gray-100/80">
        <div className="max-w-6xl mx-auto px-6 h-14 flex items-center justify-between">
          <div className="flex items-center gap-2">
            {/* Brand mark — matches favicon + desktop app icon + OG card.
                The blue gradient + "AL" monogram is the ApplyLoop visual
                identity everywhere across web + desktop surfaces. */}
            <div
              className="w-8 h-8 rounded-lg flex items-center justify-center shadow-sm"
              style={{ background: "linear-gradient(135deg, #3b82f6 0%, #1e40af 100%)" }}
            >
              <span className="text-white font-bold text-[11px] font-display tracking-tight">AL</span>
            </div>
            <span className="font-display font-bold text-lg">ApplyLoop</span>
          </div>
          <div className="hidden md:flex items-center gap-8 text-[13px] font-medium text-gray-400">
            <a href="#how-it-works" className="hover:text-gray-900 transition-colors">How It Works</a>
            <a href="#features" className="hover:text-gray-900 transition-colors">Features</a>
            <a href="#pricing" className="hover:text-gray-900 transition-colors">Pricing</a>
          </div>
          <div className="flex items-center gap-3">
            <Link href="/auth/login" className="text-[13px] font-medium text-gray-500 hover:text-gray-900 transition-colors">
              Sign In
            </Link>
            <Link href="/auth/login" className="text-[13px] font-semibold px-4 py-2 bg-gray-900 text-white rounded-lg hover:bg-black transition-colors">
              Get Started
            </Link>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="pt-28 pb-16 px-6">
        <div className="max-w-4xl mx-auto text-center">
          <div className="fade-in inline-flex items-center gap-2 px-3.5 py-1.5 bg-white text-gray-500 rounded-full text-xs font-medium mb-8 border border-gray-200 shadow-sm">
            <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full live-pulse" />
            50+ jobs applied daily while you sleep
          </div>

          <h1 className="fade-in fade-in-delay-1 font-display text-[3.2rem] md:text-[4.5rem] font-extrabold text-gray-900 leading-[1.05] tracking-tight">
            The world&apos;s best job applier.
            <br />
            <span className="text-gray-300">You sleep. It applies.</span>
          </h1>

          <p className="fade-in fade-in-delay-2 mt-6 text-lg text-gray-400 max-w-xl mx-auto leading-relaxed">
            30-60 applications/day on autopilot. Learns your style — fully autonomous by day 3. We set up everything for you.
          </p>

          {/* Job Sources */}
          <div className="fade-in fade-in-delay-2 mt-6 flex items-center justify-center gap-4 flex-wrap">
            {["Greenhouse", "Ashby", "Indeed", "Himalayas", "Google Jobs", "LinkedIn"].map((src) => (
              <span key={src} className="inline-flex items-center gap-1.5 px-3 py-1 bg-white border border-gray-100 rounded-full text-[11px] font-medium text-gray-400 shadow-sm">
                <span className="w-1.5 h-1.5 bg-emerald-400 rounded-full" />
                {src}
              </span>
            ))}
          </div>

          <div className="fade-in fade-in-delay-3 mt-8 flex flex-col sm:flex-row items-center justify-center gap-3">
            <Link href="/auth/login" className="px-7 py-3 bg-gray-900 text-white font-semibold rounded-lg text-sm hover:bg-black transition-colors">
              Get Started
            </Link>
            <a href="#pricing" className="px-7 py-3 bg-purple-600 text-white font-semibold rounded-lg text-sm hover:bg-purple-700 transition-colors">
              DM for End-to-End Setup
            </a>
          </div>

          <p className="fade-in fade-in-delay-3 mt-3 text-xs text-gray-400">
            We handle the full setup on a call — profile, resume, integrations, first test run.
          </p>
        </div>

        {/* Live Activity + Stats */}
        <div className="max-w-5xl mx-auto mt-16 grid md:grid-cols-2 gap-6">
          {/* Activity Feed */}
          <div className="fade-in fade-in-delay-3 card rounded-2xl p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-display text-sm font-semibold text-gray-900">Live Applications</h3>
              <span className="inline-flex items-center gap-1.5 text-[10px] font-medium text-emerald-600">
                <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full live-pulse" />
                LIVE
              </span>
            </div>
            <LiveActivityFeed />
          </div>

          {/* Stats */}
          <div className="fade-in fade-in-delay-4 grid grid-cols-2 gap-4">
            {STATS.map((s) => (
              <div key={s.label} className="card rounded-2xl p-6 flex flex-col justify-center">
                <p className="font-display text-3xl font-extrabold text-gray-900">{s.value}</p>
                <p className="text-xs text-gray-400 mt-1">{s.label}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Trusted By — Marquee */}
      <section className="py-10 overflow-hidden">
        <p className="text-center text-[10px] font-semibold text-gray-300 uppercase tracking-[0.25em] mb-6">
          Scanning jobs from 370+ companies
        </p>
        <div className="relative">
          <div className="marquee flex items-center gap-12 whitespace-nowrap">
            {[...COMPANIES, ...COMPANIES].map((co, i) => (
              <span key={i} className="text-lg font-semibold text-gray-200 font-display select-none">{co}</span>
            ))}
          </div>
        </div>
      </section>

      {/* How It Works */}
      <section id="how-it-works" className="py-20 px-6">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-14 animate-on-scroll">
            <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-[0.25em] mb-3">How It Works</p>
            <h2 className="font-display text-3xl md:text-4xl font-extrabold text-gray-900">
              Four steps. Fully automated.
            </h2>
          </div>

          <div className="grid md:grid-cols-2 gap-4">
            {STEPS.map((step, i) => (
              <div key={step.num} className={`animate-on-scroll card rounded-2xl p-7`} style={{ transitionDelay: `${i * 100}ms` }}>
                <div className="flex items-start gap-4">
                  <div className="w-10 h-10 bg-gray-50 rounded-xl flex items-center justify-center text-gray-400 flex-shrink-0">
                    {step.icon}
                  </div>
                  <div>
                    <span className="text-[10px] font-bold text-gray-300 uppercase tracking-[0.15em] font-display">Step {step.num}</span>
                    <h3 className="font-display text-base font-bold text-gray-900 mt-1">{step.title}</h3>
                    <p className="text-sm text-gray-400 mt-1.5 leading-relaxed">{step.desc}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ATS Platforms */}
      <section className="py-16 px-6">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-10 animate-on-scroll">
            <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-[0.25em] mb-3">ATS Support</p>
            <h2 className="font-display text-3xl md:text-4xl font-extrabold text-gray-900">
              Works everywhere you apply
            </h2>
          </div>
          <div className="flex flex-wrap justify-center gap-3 animate-on-scroll">
            {ATS_PLATFORMS.map((ats) => (
              <div key={ats.name} className="card rounded-xl px-6 py-4 text-center min-w-[140px]">
                <p className="font-display text-sm font-bold text-gray-900">{ats.name}</p>
                <p className="text-[10px] text-gray-400 mt-0.5">{ats.count}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Features */}
      <section id="features" className="py-20 px-6 bg-gray-900">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-14 animate-on-scroll">
            <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-[0.25em] mb-3">Features</p>
            <h2 className="font-display text-3xl md:text-4xl font-extrabold text-white">
              Built different from every other bot
            </h2>
            <p className="mt-3 text-sm text-gray-500 max-w-lg mx-auto">
              Battle-tested across 900+ real applications. 864 lines of ATS-specific learnings.
            </p>
          </div>

          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
            {FEATURES.map((f, i) => (
              <div key={f.title} className="animate-on-scroll bg-gray-800 rounded-2xl p-6 hover:bg-gray-750 transition-colors" style={{ transitionDelay: `${i * 80}ms` }}>
                <div className="w-9 h-9 bg-gray-700 rounded-lg flex items-center justify-center mb-4">
                  <svg className="w-4.5 h-4.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                  </svg>
                </div>
                <h3 className="font-display text-sm font-bold text-white">{f.title}</h3>
                <p className="text-[13px] text-gray-400 mt-2 leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing */}
      <section id="pricing" className="py-20 px-6">
        <div className="max-w-4xl mx-auto">
          <div className="text-center mb-14 animate-on-scroll">
            <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-[0.25em] mb-3">Pricing</p>
            <h2 className="font-display text-3xl md:text-4xl font-extrabold text-gray-900">
              Pick a plan. We handle setup.
            </h2>
          </div>

          <div className="grid md:grid-cols-2 gap-5 max-w-3xl mx-auto animate-on-scroll">
            {PRICING.map((plan) => (
              <div
                key={plan.name}
                className={`rounded-2xl p-7 flex flex-col ${
                  plan.dark
                    ? "bg-gray-900 text-white"
                    : "card"
                }`}
              >
                <p className={`font-display text-sm font-bold ${plan.dark ? "text-white" : "text-gray-900"}`}>{plan.name}</p>
                <p className={`text-xs mt-0.5 ${plan.dark ? "text-gray-400" : "text-gray-400"}`}>{plan.desc}</p>
                <div className="mt-4" />
                <ul className="mt-5 space-y-2.5 flex-1">
                  {plan.features.map((f) => (
                    <li key={f} className={`flex items-center gap-2 text-[13px] ${plan.dark ? "text-gray-300" : "text-gray-500"}`}>
                      <svg className={`w-3.5 h-3.5 flex-shrink-0 ${plan.dark ? "text-white" : "text-gray-900"}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                      </svg>
                      {f}
                    </li>
                  ))}
                </ul>
                <Link
                  href="/auth/login"
                  className={`mt-6 block text-center py-2.5 rounded-lg font-semibold text-sm transition-colors ${
                    plan.dark
                      ? "bg-white text-gray-900 hover:bg-gray-100"
                      : "bg-gray-900 text-white hover:bg-black"
                  }`}
                >
                  {plan.cta}
                </Link>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-20 px-6">
        <div className="max-w-2xl mx-auto text-center animate-on-scroll">
          <h2 className="font-display text-3xl md:text-4xl font-extrabold text-gray-900">
            Ready to stop applying manually?
          </h2>
          <p className="mt-4 text-base text-gray-400">
            Join job seekers who went from 200 applications with 3 responses to 80 applications with 12 interviews.
          </p>
          <Link href="/auth/login" className="mt-8 inline-block px-8 py-3.5 bg-gray-900 text-white font-semibold rounded-lg text-sm hover:bg-black transition-colors">
            Get Started
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="py-10 px-6 border-t border-gray-200">
        <div className="max-w-5xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 bg-gray-900 rounded flex items-center justify-center">
              <span className="text-white font-bold text-[10px] font-display">A</span>
            </div>
            <span className="font-display font-bold text-sm text-gray-900">ApplyLoop</span>
          </div>
          <div className="flex gap-6 text-xs text-gray-400">
            <a href="#features" className="hover:text-gray-900 transition-colors">Features</a>
            <a href="#pricing" className="hover:text-gray-900 transition-colors">Pricing</a>
            <Link href="/auth/login" className="hover:text-gray-900 transition-colors">Dashboard</Link>
          </div>
          <p className="text-xs text-gray-300">&copy; {new Date().getFullYear()} ApplyLoop</p>
        </div>
      </footer>
    </div>
  );
}
