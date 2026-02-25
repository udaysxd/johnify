"use client";

import { useEffect, useMemo, useState, ChangeEvent } from "react";
import { useAuth } from "@/contexts/AuthContext";

export default function MyProfilePage() {
  const { user, loading: authLoading } = useAuth();
  const [loading, setLoading] = useState(true);
  // Page-level error (e.g., not signed in)
  const [pageError, setPageError] = useState<string | null>(null);
  const [userName, setUserName] = useState("");
  const [savingName, setSavingName] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [savingPassword, setSavingPassword] = useState(false);
  // Success messages (separate per section)
  const [successLanguageMsg, setSuccessLanguageMsg] = useState<string | null>(null);
  const [successNameMsg, setSuccessNameMsg] = useState<string | null>(null);
  const [successPasswordMsg, setSuccessPasswordMsg] = useState<string | null>(null);
  // Error messages (separate per section)
  const [errorLanguageMsg, setErrorLanguageMsg] = useState<string | null>(null);
  const [errorNameMsg, setErrorNameMsg] = useState<string | null>(null);
  const [errorPasswordMsg, setErrorPasswordMsg] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  // Preferences state
  const [languageId, setLanguageId] = useState<number | null>(null);
  const [topicIds, setTopicIds] = useState<number[]>([]);
  const [languages, setLanguages] = useState<Array<{ id: number; lang: string; lang_code?: string }>>([]);
  const [topics, setTopics] = useState<Array<{ id: number; topics_name: string }>>([]);
  // Profile picture URL
  const [profilePicUrl, setProfilePicUrl] = useState<string>("");
  const [savingPic, setSavingPic] = useState(false);
  const [successPicMsg, setSuccessPicMsg] = useState<string | null>(null);
  const [errorPicMsg, setErrorPicMsg] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    setLoading(true);
    if (user) {
      setUserName(user.user_name || user.user_email || "");
      // Clear any previous errors when user context becomes available
      setPageError(null);
      setErrorLanguageMsg(null);
      setErrorNameMsg(null);
      setErrorPasswordMsg(null);
      // Load preferences + master lists
      (async () => {
        try {
          const [prefsRes, langsRes, topsRes] = await Promise.all([
            fetch("/api/preferences", { credentials: "include", cache: "no-store" }),
            fetch("/api/preferences/languages", { credentials: "include", cache: "no-store" }),
            fetch("/api/preferences/topics", { credentials: "include", cache: "no-store" }),
          ]);

          // Also fetch current profile details (profile_pic_url)
          try {
            const meResp = await fetch("/api/users/me", { credentials: "include", cache: "no-store" });
            if (meResp.ok) {
              const me = await meResp.json().catch(() => ({}));
              if (typeof me?.profile_pic_url === 'string') setProfilePicUrl(me.profile_pic_url);
            }
          } catch {}

          if (prefsRes.ok) {
            const prefs = await prefsRes.json().catch(() => ({}));
            setLanguageId(typeof prefs?.language_id === "number" ? prefs.language_id : null);
            setTopicIds(Array.isArray(prefs?.topic_ids) ? prefs.topic_ids : []);
          }
          if (langsRes.ok) {
            const l = await langsRes.json().catch(() => []);
            setLanguages(Array.isArray(l) ? l : []);
          }
          if (topsRes.ok) {
            const t = await topsRes.json().catch(() => []);
            setTopics(Array.isArray(t) ? t : []);
          }
        } catch (e) {
          // Non-fatal for profile page
        } finally {
          setLoading(false);
        }
      })();
    } else if (!authLoading) {
      setPageError("Not signed in");
      setLoading(false);
    }
  }, [user, authLoading]);

  // Upload handler (component scope)
  async function handleUploadFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setErrorPicMsg(null);
    setSuccessPicMsg(null);
    try {
      setUploading(true);
      const form = new FormData();
      form.append('file', file);
      const resp = await fetch('/api/users/me/profile-pic/upload', {
        method: 'POST',
        body: form,
        credentials: 'include',
      });
      if (!resp.ok) {
        const t = await resp.text();
        throw new Error(t || `Upload failed (${resp.status})`);
      }
      const data = await resp.json().catch(() => ({}));
      if (typeof data?.profile_pic_url === 'string') {
        setProfilePicUrl(data.profile_pic_url);
        setSuccessPicMsg('Profile picture uploaded');
      } else {
        setSuccessPicMsg('Uploaded');
      }
    } catch (err: any) {
      setErrorPicMsg(err?.message || 'Upload failed');
    } finally {
      setUploading(false);
      // reset the input so same file can be reselected
      e.target.value = '' as any;
    }
  }

  async function submitName(e: React.FormEvent) {
    e.preventDefault();
    setErrorNameMsg(null);
    setSuccessNameMsg(null);
    // Clear other sections' success to avoid multiple banners at once
    setSuccessLanguageMsg(null);
    setSuccessPasswordMsg(null);
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
      setSuccessNameMsg("Name updated successfully");
    } catch (e: unknown) {
      setErrorNameMsg(e instanceof Error ? e.message : "Failed to update name");
    } finally {
      setSavingName(false);
    }
  }

  async function submitPassword(e: React.FormEvent) {
    e.preventDefault();
    setErrorPasswordMsg(null);
    setSuccessPasswordMsg(null);
    // Clear other sections' success to avoid multiple banners at once
    setSuccessLanguageMsg(null);
    setSuccessNameMsg(null);
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
      setSuccessPasswordMsg("Password updated successfully");
    } catch (e: unknown) {
      setErrorPasswordMsg(e instanceof Error ? e.message : "Failed to update password");
    } finally {
      setSavingPassword(false);
    }
  }

  async function handleDeactivate() {
    try {
      if (deleting) return;
      const confirm1 = window.confirm(
        "Are you sure you want to delete your account? This will deactivate your account and you will not be able to sign in."
      );
      if (!confirm1) return;
      const confirm2 = window.confirm(
        "Final confirmation: Proceed to deactivate your account?"
      );
      if (!confirm2) return;
      setDeleting(true);
      const resp = await fetch("/api/auth/me/deactivate", {
        method: "POST",
        credentials: "include",
        headers: { Accept: "application/json" },
      });
      if (!resp.ok) {
        const t = await resp.text();
        throw new Error(t || `Failed to deactivate account (${resp.status})`);
      }
      // Redirect to signin with a message flag
      window.location.href = "/auth/signin?deactivated=1";
    } catch (e: unknown) {
      setPageError(e instanceof Error ? e.message : "Failed to deactivate account");
    } finally {
      setDeleting(false);
    }
  }

  async function submitLanguage(e: React.FormEvent) {
    e.preventDefault();
    setErrorLanguageMsg(null);
    setSuccessLanguageMsg(null);
    // Clear other sections' success to avoid multiple banners at once
    setSuccessNameMsg(null);
    setSuccessPasswordMsg(null);
    try {
      const payload = {
        language_id: languageId,
        // preserve current topic selections even though we're hiding the UI
        topic_ids: topicIds,
      };
      const resp = await fetch("/api/preferences", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(payload),
        credentials: "include",
      });
      if (!resp.ok) {
        const t = await resp.text();
        throw new Error(t || `Failed to save language (${resp.status})`);
      }
      setSuccessLanguageMsg("Language updated successfully");
    } catch (e: unknown) {
      setErrorLanguageMsg(e instanceof Error ? e.message : "Failed to update language");
    }
  }

  async function submitProfilePic(e: React.FormEvent) {
    e.preventDefault();
    setErrorPicMsg(null);
    setSuccessPicMsg(null);
    try {
      setSavingPic(true);
      const resp = await fetch("/api/users/me/profile-pic", {
        method: "PUT",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        credentials: "include",
        body: JSON.stringify({ profile_pic_url: profilePicUrl }),
      });
      if (!resp.ok) {
        const t = await resp.text();
        throw new Error(t || `Failed to update profile picture (${resp.status})`);
      }
      setSuccessPicMsg("Profile picture updated");
    } catch (e: unknown) {
      setErrorPicMsg(e instanceof Error ? e.message : "Failed to update profile picture");
    } finally {
      setSavingPic(false);
    }
  }

  return (
    <div className="container mx-auto px-4 py-8 bg-[var(--color-background)]">
      <h1 className="text-2xl font-bold text-[var(--color-foreground)] mb-6">My Profile</h1>
      {pageError && (
        <div className="mb-4 rounded border border-red-200 bg-red-50 text-red-700 p-3">{pageError}</div>
      )}

      {loading || authLoading ? (
        <div className="text-gray-600">Loading…</div>
      ) : (
        <div className="space-y-10">
          {/* Profile Picture */}
          <section className="rounded border border-gray-200 bg-white p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Profile Picture</h2>
            {errorPicMsg && <div className="text-red-600 mb-3">{errorPicMsg}</div>}
            {successPicMsg && <div className="text-green-700 mb-3">{successPicMsg}</div>}
            <div className="flex items-start gap-6">
              <div className="w-20 h-20 rounded-full bg-gray-100 overflow-hidden flex items-center justify-center border border-gray-200">
                {profilePicUrl ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={profilePicUrl} alt="Profile" className="w-full h-full object-cover" />
                ) : (
                  <span className="text-gray-400 text-sm">No image</span>
                )}
              </div>
              <div className="flex-1 flex flex-col gap-3">
                <div className="flex items-center gap-3">
                  <input
                    type="file"
                    accept="image/jpeg,image/png,image/webp"
                    onChange={handleUploadFile}
                    className="text-sm"
                  />
                  <button
                    type="button"
                    disabled={uploading}
                    onClick={() => { /* no-op; input change triggers upload */ }}
                    className="px-3 py-2 rounded text-sm font-medium btn-secondary disabled:opacity-60"
                  >
                    {uploading ? 'Uploading…' : 'Upload from device'}
                  </button>
                </div>
              </div>
            </div>
            <p className="text-xs text-gray-500 mt-2">Images are served from <code>https://storage.googleapis.com/assets-johnify/userprofile/</code>. Uploads are enabled in production; in development, this control will return an error.</p>
          </section>

          {/* Language update (Preferences hidden) */}
          <section className="rounded border border-gray-200 bg-white p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Language</h2>
            {errorLanguageMsg && <div className="text-red-600 mb-3">{errorLanguageMsg}</div>}
            {successLanguageMsg && <div className="text-green-700 mb-3">{successLanguageMsg}</div>}
            <form onSubmit={submitLanguage} className="flex items-center gap-3">
              <select
                className="min-w-[220px] px-3 py-2 rounded bg-white text-gray-900 border border-gray-300 focus:outline-none focus:ring-2 focus:ring-[var(--color-secondary)] focus:border-[var(--color-secondary)]"
                value={languageId ?? ''}
                onChange={(e) => setLanguageId(e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">Select language</option>
                {languages.map((l) => (
                  <option key={l.id} value={l.id}>{l.lang}</option>
                ))}
              </select>
              <button
                type="submit"
                className="px-4 py-2 rounded text-sm font-medium btn-primary"
              >
                Save Language
              </button>
            </form>
          </section>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
          <form onSubmit={submitName} className="rounded border border-gray-200 bg-white p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Update First Name</h2>
            {errorNameMsg && <div className="text-red-600 mb-3">{errorNameMsg}</div>}
            {successNameMsg && <div className="text-green-700 mb-3">{successNameMsg}</div>}
            <label className="block text-gray-700 text-sm mb-2">First Name</label>
            <input
              type="text"
              className="w-full px-3 py-2 rounded bg-white text-gray-900 border border-gray-300 focus:outline-none focus:ring-2 focus:ring-[var(--color-secondary)] focus:border-[var(--color-secondary)]"
              value={userName}
              onChange={(e) => setUserName(e.target.value)}
              minLength={2}
              maxLength={100}
              required
            />
            <button
              type="submit"
              disabled={savingName}
              className="mt-4 px-4 py-2 rounded text-sm font-medium btn-primary disabled:opacity-60"
            >
              {savingName ? "Saving…" : "Save Name"}
            </button>
          </form>

          <form onSubmit={submitPassword} className="rounded border border-gray-200 bg-white p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Update Password</h2>
            {errorPasswordMsg && <div className="text-red-600 mb-3">{errorPasswordMsg}</div>}
            {successPasswordMsg && <div className="text-green-700 mb-3">{successPasswordMsg}</div>}
            <label className="block text-gray-700 text-sm mb-2">Current Password</label>
            <input
              type="password"
              className="w-full px-3 py-2 rounded bg-white text-gray-900 border border-gray-300 focus:outline-none focus:ring-2 focus:ring-[var(--color-secondary)] focus:border-[var(--color-secondary)]"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              minLength={8}
              required
            />
            <label className="block text-gray-700 text-sm mt-4 mb-2">New Password</label>
            <input
              type="password"
              className="w-full px-3 py-2 rounded bg-white text-gray-900 border border-gray-300 focus:outline-none focus:ring-2 focus:ring-[var(--color-secondary)] focus:border-[var(--color-secondary)]"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              minLength={8}
              required
            />
            <button
              type="submit"
              disabled={savingPassword}
              className="mt-4 px-4 py-2 rounded text-sm font-medium btn-primary disabled:opacity-60"
            >
              {savingPassword ? "Saving…" : "Change Password"}
            </button>
          </form>
          </div>

          {/* Danger Zone */}
          <section className="rounded border border-red-200 bg-white p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-3">Danger Zone</h2>
            <p className="text-sm text-gray-700 mb-4">
              Deleting your account will immediately deactivate it. You will no longer be able to sign in.
            </p>
            <button
              onClick={handleDeactivate}
              disabled={deleting}
              className="px-4 py-2 rounded bg-red-600 text-white hover:bg-red-700 disabled:opacity-60"
            >
              {deleting ? "Deleting…" : "Delete account"}
            </button>
          </section>
        </div>
      )}
    </div>
  );
}
