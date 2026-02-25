"use client";

import { useEffect, useRef, useState, Suspense, useCallback } from "react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";

type BookTopicInput = {
  topic: string;
};

type ApiResponse = {
  ok?: boolean;
  message?: string;
  submitted?: number;
  ts?: number;
};

type GridVideo = { id: string; title: string; videoUrl: string; thumbnailUrl: string; createdAt: string; type?: string };

function BooksPageContent() {
  const router = useRouter();
  const { user, loading: isAuthLoading } = useAuth();
  const isAuthenticated = !!user;

  const [item, setItem] = useState<BookTopicInput>({ topic: "" });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [progressPct, setProgressPct] = useState<number>(0);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [jobDirs, setJobDirs] = useState<string[]>([]);
  const [myVideos, setMyVideos] = useState<GridVideo[]>([]);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [selectedVideo, setSelectedVideo] = useState<GridVideo | null>(null);
  const formRef = useRef<HTMLDivElement | null>(null);

  const fetchMyVideos = useCallback(async () => {
    try {
      const resp = await fetch('/api/videos/my-videos?type=all', { method: 'GET', headers: { 'Accept': 'application/json' }, cache: 'no-store' });
      if (!resp.ok) return;
      const data = await resp.json();
      if (Array.isArray(data)) {
        const isObj = (x: unknown): x is Record<string, unknown> => x !== null && typeof x === 'object';
        const mapped: GridVideo[] = data
          .map((v) => {
            if (!isObj(v)) return null;
            const id = 'id' in v ? String(v.id ?? '') : '';
            const title = 'title' in v ? String(v.title ?? 'Untitled Video') : 'Untitled Video';
            const videoUrl = 'videoUrl' in v ? String((v as Record<string, unknown>).videoUrl ?? '') : ('url' in v ? String((v as Record<string, unknown>).url ?? '') : '');
            const thumbnailUrl = 'thumbnailUrl' in v ? String((v as Record<string, unknown>).thumbnailUrl ?? '') : ('thumbnail' in v ? String((v as Record<string, unknown>).thumbnail ?? '') : '');
            const createdAt = 'createdAt' in v ? String(v.createdAt ?? new Date().toISOString()) : new Date().toISOString();
            const type = 'type' in v && typeof v.type === 'string' ? (v.type as string).toLowerCase() : undefined;
            const out: GridVideo = { id, title, videoUrl, thumbnailUrl, createdAt, type };
            const okType = out.type === 'mlites_books';
            return okType && out.videoUrl ? out : null;
          })
          .filter((v): v is GridVideo => v !== null);
        mapped.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
        setMyVideos(mapped);
      }
    } catch {}
  }, []);

  useEffect(() => {
    if (!isAuthLoading && !isAuthenticated) {
      router.push("/auth/signin");
    }
  }, [isAuthLoading, isAuthenticated, router]);

  useEffect(() => {
    if (!isAuthLoading && isAuthenticated) {
      fetchMyVideos();
    }
  }, [isAuthLoading, isAuthenticated, fetchMyVideos]);

  const jobDirsKey = jobDirs.join('|');

  // SSE subscribe: reuse mlites stream; refresh on any books completion event
  useEffect(() => {
    if (!user || !user.user_id) return;
    let es: EventSource | null = null;
    try {
      es = new EventSource(`/api/mlites/stream?user_id=${encodeURIComponent(user.user_id)}` );
      type SSEPayload = { type?: string };
      const onAny: EventListener = (ev: Event) => {
        try {
          const msg = ev as MessageEvent;
          const raw = (msg && typeof msg.data === 'string') ? msg.data : '{}';
          const parsed: unknown = JSON.parse(raw);
          if (!parsed || typeof parsed !== 'object') return;
          const t = (parsed as SSEPayload).type ?? '';
          if (String(t).toLowerCase().includes('mlites_books')) {
            // Books pipeline done: refresh
            fetchMyVideos();
            setSuccess('Your Books video is ready!');
            setProgressPct(100);
            setIsGenerating(false);
          }
        } catch {}
      };
      // Fallback: some brokers send as 'message' events
      es.addEventListener('message', onAny);
      es.addEventListener('mlites_books_done', onAny);
    } catch {
      // swallow
    }
    return () => { try { es?.close(); } catch {} };
  }, [user?.user_id, jobDirsKey, fetchMyVideos]);

  useEffect(() => {
    if (!isGenerating) return;
    let pct = progressPct || 0;
    const id = setInterval(() => {
      pct = Math.min(98, pct + Math.max(1, Math.floor((100 - pct) * 0.03)));
      setProgressPct(pct);
    }, 800);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isGenerating]);

  const canSubmit = () => {
    if (isAuthLoading || !isAuthenticated || isSubmitting) return false;
    return item.topic.trim().length > 0;
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit()) return;
    setIsSubmitting(true);
    setError(null);
    setSuccess(null);
    try {
      if (!user || !user.user_id) throw new Error('Not authenticated');

      const genPayload = {
        user_id: user.user_id,
        topics: [{ topic: item.topic.trim() }],
      };
      const resp = await fetch('/api/mlites/books', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(genPayload),
      });
      const ct = resp.headers.get('content-type') || '';
      let data: ApiResponse | null = null;
      if (ct.includes('application/json')) {
        data = await resp.json().catch(() => null);
      }
      if (!resp.ok) {
        const errMsg = (data && typeof data === 'object' && 'message' in (data as Record<string, unknown>) && typeof (data as Record<string, unknown>).message === 'string')
          ? String((data as Record<string, unknown>).message)
          : 'Failed to start books generation';
        throw new Error(errMsg);
      }
      setJobDirs([]);
      setIsGenerating(true);
      setProgressPct(5);
      fetchMyVideos();
    } catch (err: unknown) {
      let message = 'Something went wrong';
      if (err instanceof Error) message = err.message;
      else if (err && typeof err === 'object' && 'message' in err && typeof (err as Record<string, unknown>).message === 'string') {
        message = String((err as Record<string, unknown>).message);
      }
      setError(message);
      setIsGenerating(false);
    } finally {
      setIsSubmitting(false);
    }
  };

  const scrollToForm = () => {
    try {
      formRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch {
      try { window?.scrollTo?.({ top: 0, behavior: 'smooth' } as ScrollToOptions); } catch {}
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="py-12 px-4 sm:px-6 lg:px-8">
        <div className="max-w-3xl mx-auto">
          <div className="flex items-center justify-between mb-4">
            <div></div>
            <button onClick={scrollToForm} className="btn-primary text-sm">
              Create Books Video
            </button>
          </div>

          <div className="text-center mb-8" ref={formRef}>
            <h2 className="text-3xl font-bold text-gray-900 mb-2">Create a 15-minute Book Summary</h2>
            <p className="text-gray-600">Enter a book title or topic to generate a longform vertical video</p>
          </div>

          {isAuthLoading ? (
            <div className="min-h-[200px] flex items-center justify-center">
              <div className="text-center">
                <div className="w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto"></div>
                <p className="mt-4 text-gray-600">Loading...</p>
              </div>
            </div>
          ) : (
            <div className="bg-white shadow rounded-lg p-6">
              <form onSubmit={onSubmit} className="space-y-6">
                <div className="grid grid-cols-1 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Book or Topic</label>
                    <input
                      type="text"
                      value={item.topic}
                      onChange={(e) => setItem((it) => ({ ...it, topic: e.target.value }))}
                      placeholder="e.g., Atomic Habits, Thinking Fast and Slow"
                      className="w-full px-4 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-2 focus:ring-[var(--color-secondary)] focus:border-[var(--color-secondary)]"
                      disabled={isSubmitting}
                      required
                    />
                  </div>
                </div>

                <div className="flex items-center justify-end">
                  <button
                    type="submit"
                    disabled={!canSubmit()}
                    className={`btn-primary text-sm ${!canSubmit() ? 'opacity-50 cursor-not-allowed' : ''}`}
                  >
                    {isSubmitting ? "Starting…" : "Generate Books Video"}
                  </button>
                </div>

                {isGenerating && (
                  <div className="mt-4" aria-live="polite">
                    <div className="w-full bg-gray-200 rounded h-2 overflow-hidden">
                      <div
                        className="h-2 transition-all bg-[var(--color-primary)]"
                        style={{ width: `${Math.round(progressPct || 5)}%` }}
                      />
                    </div>
                    <div className="mt-2 text-xs text-gray-600">
                      Please be patient. It can take a few minutes to generate ~15 minutes of narration.
                    </div>
                  </div>
                )}
                {error && <div className="mt-3 p-3 bg-red-50 text-red-700 rounded-md text-sm" role="alert">{error}</div>}
                {success && <div className="mt-3 p-3 bg-green-50 text-green-700 rounded-md text-sm" role="status">{success}</div>}
              </form>
            </div>
          )}

          {/* Videos */}
          <div className="bg-white shadow rounded-lg p-6 mt-8">
            <div className="flex items-center justify-between mb-3">
              <h4 className="text-base font-semibold text-gray-900">Your Books Videos</h4>
              <button type="button" onClick={() => fetchMyVideos()} className="text-sm text-[var(--color-secondary)] hover:opacity-80">Refresh</button>
            </div>
            {myVideos.length === 0 ? (
              <p className="text-sm text-gray-600">No Books videos yet. Generate one above.</p>
            ) : (
              <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
                {myVideos.map((video) => (
                  <div key={video.id} className="relative bg-white shadow rounded-lg hover:shadow-lg transition-shadow duration-200 cursor-pointer overflow-visible z-10" onClick={() => { setSelectedVideo(video); setIsModalOpen(true); }}>
                    <div className="relative pb-[177.78%] bg-black rounded-t-lg overflow-hidden">{/* 9:16 ratio */}
                      {video.thumbnailUrl ? (
                        <div className="absolute inset-0">
                          <Image src={video.thumbnailUrl} alt={video.title} fill className="object-cover" sizes="(max-width: 768px) 100vw, (max-width: 1200px) 50vw, 33vw" unoptimized />
                        </div>
                      ) : (
                        <div className="w-full h-full bg-gradient-to-br from-indigo-600 to-fuchsia-600 flex items-center justify-center text-white p-4 text-center">
                          <div className="relative w-16 h-16 mb-4">
                            <div className="absolute inset-0 bg-white/20 rounded-full animate-ping"></div>
                            <div className="absolute inset-0 flex items-center justify-center">
                              <svg className="w-10 h-10" fill="currentColor" viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg"><path d="M6.3 2.841A1.5 1.5 0 004 4.11v11.78a1.5 1.5 0 002.3 1.269l9.344-5.89a1.5 1.5 0 000-2.538L6.3 2.84z" /></svg>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                    <div className="mx-4 border-t border-gray-300" />
                    <div className="px-4 pb-3 pt-3 relative">
                      <div className="flex items-start justify-between gap-2">
                        <h3 className="text-base font-medium text-gray-900 truncate">{video.title}</h3>
                      </div>
                      <p className="mt-1 text-sm text-gray-500">{new Date(video.createdAt).toLocaleString()}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Video Modal */}
      {isModalOpen && selectedVideo && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" role="dialog" aria-modal="true">
          <div className="absolute inset-0 bg-black/60" onClick={() => { setIsModalOpen(false); setSelectedVideo(null); }} />
          <div className="relative z-10 w-full mx-4 bg-white rounded-lg shadow-lg overflow-hidden max-w-[420px] sm:max-w-[460px] md:max-w-[520px] max-h-[92vh] flex flex-col">
            <div className="flex items-center justify-between px-4 py-3 border-b shrink-0">
              <h3 className="text-lg font-semibold truncate pr-4">{selectedVideo.title}</h3>
              <button onClick={() => { setIsModalOpen(false); setSelectedVideo(null); }} className="p-2 text-gray-500 hover:text-gray-700" aria-label="Close">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5"><path fillRule="evenodd" d="M5.47 5.47a.75.75 0 011.06 0L12 10.94l5.47-5.47a.75.75 0 111.06 1.06L13.06 12l5.47 5.47a.75.75 0 11-1.06 1.06L12 13.06l-5.47 5.47a.75.75 0 01-1.06-1.06L10.94 12 5.47 6.53a.75.75 0 010-1.06z" clipRule="evenodd" /></svg>
              </button>
            </div>
            <div className="relative bg-black overflow-hidden">
              <div className="relative pb-[177.78%]">{/* 9:16 */}
                <video src={selectedVideo.videoUrl} controls className="absolute inset-0 w-full h-full object-contain" autoPlay>
                  Your browser does not support the video tag.
                </video>
              </div>
            </div>
            <div className="px-4 py-3 border-t text-sm text-gray-600 flex items-center justify-between shrink-0">
              <div className="truncate">Generated Books Video</div>
              <div className="text-gray-500">{new Date(selectedVideo.createdAt).toLocaleString()}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function BooksPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-gray-50 flex items-center justify-center"><div className="text-gray-600">Loading…</div></div>}>
      <>
        <BooksPageContent />
      </>
    </Suspense>
  );
}
