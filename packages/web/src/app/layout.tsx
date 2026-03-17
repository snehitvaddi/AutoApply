import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "AutoApply — Automated Job Applications",
  description:
    "AI-powered job application engine. AutoApply fills out applications, tailors resumes, and writes cover letters while you sleep.",
  openGraph: {
    title: "AutoApply — Stop Applying Manually. Start Getting Interviews.",
    description:
      "AI-powered job application engine that fills out applications, tailors resumes, and writes cover letters while you sleep.",
    type: "website",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="scroll-smooth">
      <body>{children}</body>
    </html>
  );
}
