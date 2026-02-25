'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

type Language = { id: number; lang: string; lang_code?: string };
type Topic = { id: number; topics_name: string };
type Prefs = { language_id?: number | null; topic_ids?: number[] | null };

export default function PreferencesPage() {
  const router = useRouter();
  const [languages, setLanguages] = useState<Language[]>([]);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [selectedLanguageId, setSelectedLanguageId] = useState<number | ''>('');
  const [selectedTopicIds, setSelectedTopicIds] = useState<number[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    async function load() {
      try {
        setLoading(true);
        setError(null);
        const [langsRes, topicsRes, prefsRes] = await Promise.all([
          fetch('/api/preferences/languages', { credentials: 'include', cache: 'no-store' }),
          fetch('/api/preferences/topics', { credentials: 'include', cache: 'no-store' }),
          fetch('/api/preferences', { credentials: 'include', cache: 'no-store' }),
        ]);
        if (!langsRes.ok) {
          const j = await langsRes.json().catch(() => ({}));
          throw new Error(j?.message || 'Failed to load languages');
        }
        if (!topicsRes.ok) {
          const j = await topicsRes.json().catch(() => ({}));
          throw new Error(j?.message || 'Failed to load topics');
        }
        if (!prefsRes.ok) {
          // preferences may not exist yet; treat non-200 as empty
          console.warn('No existing preferences found');
        }
        const langs = await langsRes.json();
        const tops = await topicsRes.json();
        const prefs: Prefs = prefsRes.ok
          ? await prefsRes.json().catch(() => ({} as Prefs))
          : ({} as Prefs);
        if (!mounted) return;
        setLanguages(langs || []);
        setTopics(tops || []);
        if (prefs && typeof prefs === 'object') {
          const langId = prefs.language_id;
          const topicIds = Array.isArray(prefs.topic_ids) ? prefs.topic_ids as number[] : [];
          setSelectedLanguageId(typeof langId === 'number' ? langId : '');
          setSelectedTopicIds(topicIds);
        }
        // If no saved language, default to English if present
        try {
          const hasLang = prefs && typeof prefs.language_id === 'number';
          if (!hasLang && Array.isArray(langs)) {
            const english = (langs as Array<{id:number; lang:string}>).find(
              (l) => typeof l?.lang === 'string' && l.lang.trim().toLowerCase() === 'english'
            );
            if (english && typeof english.id === 'number') {
              setSelectedLanguageId(english.id);
            }
          }
        } catch {}
      } catch (e) {
        if (!mounted) return;
        setError(e instanceof Error ? e.message : 'Failed to load preferences');
      } finally {
        if (mounted) setLoading(false);
      }
    }
    load();
    return () => {
      mounted = false;
    };
  }, []);

  const canSelectMore = selectedTopicIds.length < 5;

  const toggleTopic = (id: number) => {
    setSelectedTopicIds((prev) => {
      if (prev.includes(id)) {
        return prev.filter((x) => x !== id);
      }
      if (prev.length >= 5) return prev; // enforce max 5
      return [...prev, id];
    });
  };

  const submit = async () => {
    try {
      setSaving(true);
      setError(null);
      const payload = {
        language_id: selectedLanguageId === '' ? null : selectedLanguageId,
        topic_ids: selectedTopicIds,
      };
      const res = await fetch('/api/preferences', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data?.message || 'Failed to save preferences');
      }
      // Go to feed after saving
      router.push('/feed');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save preferences');
    } finally {
      setSaving(false);
    }
  };

  const selectedCount = selectedTopicIds.length;

  return (
    <div className="min-h-screen bg-[var(--color-background)]">
      <div className="max-w-3xl mx-auto px-4 py-10">
        <h1 className="text-2xl font-semibold text-[var(--color-foreground)]">Set your preferences</h1>
        <p className="mt-1 text-sm text-gray-600">Choose your language and interests to personalize your experience.</p>

        {error && (
          <div className="mt-4 bg-red-50 border border-red-200 text-red-700 rounded p-3">{error}</div>
        )}

        {loading ? (
          <div className="mt-8 text-gray-600">Loading...</div>
        ) : (
          <>
            <section className="mt-8">
              <h2 className="text-lg font-medium text-gray-800">Language</h2>
              <p className="text-sm text-gray-500">Select exactly one language (or skip for now).</p>
              <div className="mt-3">
                <select
                  className="w-full max-w-md border border-gray-300 rounded-md px-3 py-2 text-gray-900 focus:outline-none focus:ring-2 focus:ring-[var(--color-secondary)] focus:border-[var(--color-secondary)]"
                  value={selectedLanguageId}
                  onChange={(e) => setSelectedLanguageId(e.target.value ? Number(e.target.value) : '')}
                >
                  <option value="">No preference (skip)</option>
                  {languages.map((l) => (
                    <option key={l.id} value={l.id}>{l.lang}</option>
                  ))}
                </select>
              </div>
            </section>

            <section className="mt-10">
              <div className="flex items-baseline gap-3">
                <h2 className="text-lg font-medium text-gray-800">Interests</h2>
                <span className="text-sm text-gray-500">Select up to 5 (selected {selectedCount}/5)</span>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {topics.map((t) => {
                  const active = selectedTopicIds.includes(t.id);
                  return (
                    <button
                      key={t.id}
                      type="button"
                      onClick={() => toggleTopic(t.id)}
                      className={
                        `px-3 py-1 rounded-full border text-sm transition ` +
                        (active
                          ? 'bg-[var(--color-primary)] text-white border-[var(--color-primary)]'
                          : (canSelectMore
                              ? 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
                              : 'bg-gray-100 text-gray-400 border-gray-200 cursor-not-allowed'))
                      }
                      disabled={!active && !canSelectMore}
                      aria-pressed={active}
                    >
                      {t.topics_name}
                    </button>
                  );
                })}
              </div>
            </section>

            <div className="mt-10 flex gap-3">
              <button
                type="button"
                onClick={submit}
                disabled={saving}
                className={`inline-flex items-center px-4 py-2 rounded-md text-sm font-medium btn-primary ${saving ? 'opacity-50 cursor-not-allowed' : ''}`}
              >
                {saving ? 'Saving...' : 'Save and continue'}
              </button>
              <button
                type="button"
                onClick={() => router.push('/')}
                className="inline-flex items-center px-4 py-2 rounded-md text-sm font-medium btn-outline"
              >
                Skip for now
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
