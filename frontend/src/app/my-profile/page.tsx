"use client";

import { useEffect, useState } from "react";

export default function MyProfilePage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [userName, setUserName] = useState("");
  const [savingName, setSavingName] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [savingPassword, setSavingPassword] = useState(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  useEffect(() => {
    let aborted = false;
    async function loadMe() {
      try {
        setLoading(true);
        const resp = await fetch("/api/auth/me", { cache: "no-store" });
        if (!resp.ok) {
          const t = await resp.text();
          throw new Error(t || `Failed to load profile (${resp.status})`);
        }
        const data = await resp.json();
        if (!aborted) {
          setUserName(data?.user_name || "");
        }
      } catch (e: unknown) {
        if (!aborted) setError(e instanceof Error ? e.message : "Failed to load profile");
      } finally {
        if (!aborted) setLoading(false);
      }
    }
    loadMe();
    return () => {
      aborted = true;
    };
  }, []);

  async function submitName(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSuccessMsg(null);
    try {
      setSavingName(true);
      const resp = await fetch("/api/auth/me/name", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_name: userName }),
      });
      if (!resp.ok) {
        const t = await resp.text();
        throw new Error(t || `Failed to update name (${resp.status})`);
      }
      setSuccessMsg("Name updated successfully");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to update name");
    } finally {
      setSavingName(false);
    }
  }

  async function submitPassword(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSuccessMsg(null);
    try {
      setSavingPassword(true);
      const resp = await fetch("/api/auth/me/password", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      if (!resp.ok) {
        const t = await resp.text();
        throw new Error(t || `Failed to update password (${resp.status})`);
      }
      setCurrentPassword("");
      setNewPassword("");
      setSuccessMsg("Password updated successfully");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to update password");
    } finally {
      setSavingPassword(false);
    }
  }

  return (
    <div className="container mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold text-white mb-6">My Profile</h1>

      {loading ? (
        <div className="text-gray-300">Loading…</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
          <form onSubmit={submitName} className="bg-gray-800 border border-gray-700 rounded p-6">
            <h2 className="text-lg font-semibold text-white mb-4">Update First Name</h2>
            {error && <div className="text-red-400 mb-3">{error}</div>}
            {successMsg && <div className="text-green-400 mb-3">{successMsg}</div>}
            <label className="block text-gray-300 text-sm mb-2">First Name</label>
            <input
              type="text"
              className="w-full px-3 py-2 rounded bg-gray-900 text-white border border-gray-700 focus:outline-none focus:ring-2 focus:ring-indigo-600"
              value={userName}
              onChange={(e) => setUserName(e.target.value)}
              minLength={2}
              maxLength={100}
              required
            />
            <button
              type="submit"
              disabled={savingName}
              className="mt-4 px-4 py-2 rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-60"
            >
              {savingName ? "Saving…" : "Save Name"}
            </button>
          </form>

          <form onSubmit={submitPassword} className="bg-gray-800 border border-gray-700 rounded p-6">
            <h2 className="text-lg font-semibold text-white mb-4">Update Password</h2>
            {error && <div className="text-red-400 mb-3">{error}</div>}
            {successMsg && <div className="text-green-400 mb-3">{successMsg}</div>}
            <label className="block text-gray-300 text-sm mb-2">Current Password</label>
            <input
              type="password"
              className="w-full px-3 py-2 rounded bg-gray-900 text-white border border-gray-700 focus:outline-none focus:ring-2 focus:ring-indigo-600"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              minLength={8}
              required
            />
            <label className="block text-gray-300 text-sm mt-4 mb-2">New Password</label>
            <input
              type="password"
              className="w-full px-3 py-2 rounded bg-gray-900 text-white border border-gray-700 focus:outline-none focus:ring-2 focus:ring-indigo-600"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              minLength={8}
              required
            />
            <button
              type="submit"
              disabled={savingPassword}
              className="mt-4 px-4 py-2 rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-60"
            >
              {savingPassword ? "Saving…" : "Change Password"}
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
