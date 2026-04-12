/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        // ApplyLoop brand blue. Anchored on the desktop app's primary
        // accent (#3b82f6 → #1e40af gradient), so every surface — web
        // landing, dashboard, desktop app, favicon, OG card, Dock icon —
        // pulls from the same palette. Every existing `bg-brand-*` /
        // `text-brand-*` class across the web instantly flips to blue
        // when this file changes; no component edits required.
        brand: {
          50: "#eff6ff",
          100: "#dbeafe",
          200: "#bfdbfe",
          300: "#93c5fd",
          400: "#60a5fa",
          500: "#3b82f6",  // desktop UI --primary
          600: "#2563eb",
          700: "#1d4ed8",
          800: "#1e40af",  // desktop icon.svg gradient endpoint
          900: "#1e3a8a",
          950: "#172554",
        },
      },
      fontFamily: {
        display: ['Sora', 'system-ui', '-apple-system', 'sans-serif'],
        body: ['DM Sans', 'system-ui', '-apple-system', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
