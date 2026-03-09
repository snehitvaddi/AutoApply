"use client";

import { useEffect, useState } from "react";

export default function SettingsPage() {
  const [profile, setProfile] = useState<Record<string, string | number | boolean | null>>({});
  const [preferences, setPreferences] = useState<Record<string, string | number | boolean | string[] | null>>({});
  const [telegramChatId, setTelegramChatId] = useState("");
  const [tier, setTier] = useState("free");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    Promise.all([
      fetch("/api/settings/profile").then((r) => r.json()),
      fetch("/api/settings/preferences").then((r) => r.json()),
    ]).then(([profileData, prefsData]) => {
      setProfile(profileData.data?.profile || {});
      setPreferences(prefsData.data?.preferences || {});
      setTier(prefsData.data?.tier || "free");
      setTelegramChatId(profileData.data?.telegram_chat_id || "");
      setLoading(false);
    });
  }, []);

  async function saveProfile() {
    setSaving(true);
    await fetch("/api/settings/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(profile),
    });
    setMessage("Profile saved!");
    setSaving(false);
    setTimeout(() => setMessage(""), 3000);
  }

  async function saveTelegram() {
    setSaving(true);
    await fetch("/api/settings/telegram", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: telegramChatId }),
    });
    setMessage("Telegram connected!");
    setSaving(false);
    setTimeout(() => setMessage(""), 3000);
  }

  if (loading) return <div className="p-8">Loading settings...</div>;

  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-bold mb-6">Settings</h1>

      {message && (
        <div className="mb-4 p-3 bg-green-50 text-green-700 rounded-lg text-sm">{message}</div>
      )}

      {/* Profile Section */}
      <section className="bg-white rounded-xl border p-6 mb-6">
        <h2 className="font-semibold mb-4">Profile</h2>
        <div className="grid grid-cols-2 gap-4">
          <input
            placeholder="First Name"
            value={(profile.first_name as string) || ""}
            onChange={(e) => setProfile({ ...profile, first_name: e.target.value })}
            className="px-3 py-2 border rounded-lg"
          />
          <input
            placeholder="Last Name"
            value={(profile.last_name as string) || ""}
            onChange={(e) => setProfile({ ...profile, last_name: e.target.value })}
            className="px-3 py-2 border rounded-lg"
          />
        </div>
        <input
          placeholder="Phone"
          value={(profile.phone as string) || ""}
          onChange={(e) => setProfile({ ...profile, phone: e.target.value })}
          className="w-full px-3 py-2 border rounded-lg mt-4"
        />
        <input
          placeholder="LinkedIn URL"
          value={(profile.linkedin_url as string) || ""}
          onChange={(e) => setProfile({ ...profile, linkedin_url: e.target.value })}
          className="w-full px-3 py-2 border rounded-lg mt-4"
        />
        <button onClick={saveProfile} disabled={saving} className="mt-4 px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50">
          {saving ? "Saving..." : "Save Profile"}
        </button>
      </section>

      {/* Telegram Section */}
      <section className="bg-white rounded-xl border p-6 mb-6">
        <h2 className="font-semibold mb-4">Telegram Notifications</h2>
        <p className="text-sm text-gray-500 mb-4">
          Message @AutoApplyBot with /start, then enter your chat ID below.
        </p>
        <div className="flex gap-4">
          <input
            placeholder="Telegram Chat ID"
            value={telegramChatId}
            onChange={(e) => setTelegramChatId(e.target.value)}
            className="flex-1 px-3 py-2 border rounded-lg"
          />
          <button onClick={saveTelegram} disabled={saving} className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50">
            Connect
          </button>
        </div>
      </section>

      {/* Billing Section */}
      <section className="bg-white rounded-xl border p-6">
        <h2 className="font-semibold mb-4">Billing</h2>
        <p className="text-sm text-gray-500 mb-4">
          Current plan: <span className="font-medium capitalize">{tier}</span>
        </p>
        <div className="flex gap-4">
          <a href="/api/stripe/checkout?tier=starter" className="px-4 py-2 border border-brand-600 text-brand-600 rounded-lg text-sm font-medium hover:bg-brand-50">
            Upgrade to Starter ($15/mo)
          </a>
          <a href="/api/stripe/checkout?tier=pro" className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700">
            Upgrade to Pro ($29/mo)
          </a>
        </div>
      </section>
    </div>
  );
}
