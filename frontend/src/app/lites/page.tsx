"use client";

import { useEffect, useState, Suspense, useRef } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";
import { useAuth } from "@/contexts/AuthContext";

type TopicInput = {
  topic: string;
  minutes_per_day: 1 | 2 | 3 | 4 | 5 | 10 | 15;
};

type ApiResponse = {
  message?: string;
  error?: string;
  detail?: string;
  status?: string;
  count?: number;
  jobs?: { topic: string; dir: string }[];
};

type LitesStatusJob = {
  dir: string;
  status: 'pending' | 'processing' | 'completed' | 'error' | 'invalid';
  video_url?: string;
  thumbnail_url?: string;
};
type LitesStatusResponse = {
  jobs: LitesStatusJob[];
};

type UserTopic = {
  topic_id: number;
  topic: string;
  minutes_per_day: number;
  active: boolean;
};

function LitesPageContent() {
  const router = useRouter();
  const { user, loading: isAuthLoading } = useAuth();
  const isAuthenticated = !!user;

  const [items, setItems] = useState<TopicInput[]>([
    { topic: "", minutes_per_day: 5 },
  ]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [jobDirs, setJobDirs] = useState<string[]>([]); // kept for compatibility; not used for /generate flow
  const [videoUrl, setVideoUrl] = useState<string | null>(null); // kept for compatibility; not used in card view
  const [sseConnected, setSseConnected] = useState<boolean>(false);
  const [isGenerating, setIsGenerating] = useState<boolean>(false);
  const [topics, setTopics] = useState<UserTopic[]>([]);
  const formRef = useRef<HTMLDivElement | null>(null);
  // My videos grid state
  type GridVideo = { id: string; title: string; videoUrl: string; thumbnailUrl: string; createdAt: string; type?: string };
  const [myVideos, setMyVideos] = useState<GridVideo[]>([]);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [selectedVideo, setSelectedVideo] = useState<GridVideo | null>(null);

  const fetchMyVideos = async () => {
    try {
      const resp = await fetch('/api/videos/my-videos', { method: 'GET', headers: { 'Accept': 'application/json' }, cache: 'no-store' });
      if (!resp.ok) return;
      const data = await resp.json();
      if (Array.isArray(data)) {
        const mapped: GridVideo[] = data
          .map((v: any) => ({
            id: String(v.id || ''),
            title: String(v.title || 'Untitled Video'),
            videoUrl: String(v.videoUrl || v.url || ''),
            thumbnailUrl: String(v.thumbnailUrl || v.thumbnail || ''),
            createdAt: String(v.createdAt || new Date().toISOString()),
            type: typeof v.type === 'string' ? v.type.toLowerCase() : 'lites', // Normalize to lowercase
          }))
          .filter(v => !!v.videoUrl)
          .filter(v => v.type === 'lites'); // Now we can do direct comparison
        // Sort newest first
        mapped.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
        setMyVideos(mapped);
      }
    } catch {}
  };

  const fetchTopics = async () => {
    try {
      if (!user?.user_id) return;
      const resp = await fetch(`/api/lites/topics?user_id=${encodeURIComponent(user.user_id)}`, { cache: 'no-store' });
      if (!resp.ok) return;
      const data = await resp.json();
      const arr = Array.isArray(data?.topics) ? data.topics as UserTopic[] : [];
      setTopics(arr);
    } catch {}
  };

  // Redirect to login if not authenticated
  useEffect(() => {
    if (!isAuthLoading && !isAuthenticated) {
      router.push("/auth/signin");
    }
  }, [isAuthLoading, isAuthenticated, router]);

  // Once authenticated, preload user's videos
  useEffect(() => {
    if (!isAuthLoading && isAuthenticated) {
      fetchMyVideos();
      fetchTopics();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthLoading, isAuthenticated]);

  const addItem = () => {
    // Max 3 for now (can increase later without breaking schema)
    if (items.length >= 3) return;
    setItems((prev) => [...prev, { topic: "", minutes_per_day: 5 }]);
  };

  // Subscribe to SSE for real-time updates
  useEffect(() => {
    if (!user || !user.user_id) return;
    let es: EventSource | null = null;
    try {
      es = new EventSource(`/api/lites/stream?user_id=${encodeURIComponent(user.user_id)}`);
      const onOpen = () => setSseConnected(true);
      const onError = () => setSseConnected(false);
      const onLiteVideo = (ev: MessageEvent) => {
        try {
          const payload = JSON.parse(ev.data || '{}');
          if (!payload || typeof payload !== 'object') return;
          // If we have specific jobs, only accept events for those dirs
          if (Array.isArray(jobDirs) && jobDirs.length > 0) {
            if (!payload.dir || !jobDirs.includes(String(payload.dir))) return;
          }
          // On any lite_video event, refresh grid from My Videos
          fetchMyVideos();
          // Some backends may provide direct video_url
          if (payload.video_url && typeof payload.video_url === 'string') {
            setVideoUrl(payload.video_url);
            setSuccess('Your Lite is ready!');
          } else {
            setSuccess('Your Lite is ready!');
          }
          setIsGenerating(false);
        } catch {}
      };
      es.addEventListener('open', onOpen as any);
      es.addEventListener('error', onError as any);
      es.addEventListener('lite_video', onLiteVideo as any);
    } catch {
      setSseConnected(false);
    }
    return () => {
      try { es?.close(); } catch {}
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.user_id, jobDirs.join('|')]);

  // (Removed diff-based 'New' timer; we now show 'New' only based on createdAt being today)

  const removeItem = (idx: number) => {
    setItems((prev) => prev.filter((_, i) => i !== idx));
  };

  const updateItem = (idx: number, patch: Partial<TopicInput>) => {
    setItems((prev) => prev.map((it, i) => (i === idx ? { ...it, ...patch } : it)));
  };

  const canSubmit = () => {
    if (isAuthLoading || !isAuthenticated || isSubmitting) return false;
    if (items.length === 0) return false;
    // Require non-empty topics
    return items.every((it) => it.topic.trim().length > 0);
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit()) return;
    setIsSubmitting(true);
    setError(null);
    setSuccess(null);
    try {
      if (!user || !user.user_id) throw new Error('Not authenticated');

      // 1) Upsert topics for this user
      const topicsPayload = {
        user_id: user.user_id,
        topics: items.map((it) => ({
          topic: it.topic.trim(),
          minutes_per_day: it.minutes_per_day,
        })),
      };
      const tResp = await fetch('/api/lites/topics', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(topicsPayload),
      });
      if (!tResp.ok) {
        const err = await tResp.json().catch(() => ({} as any));
        throw new Error(err?.message || err?.detail || 'Failed to save topics');
      }
      const tData = await tResp.json().catch(() => ({ topics: [] as any[] }));
      const entered = new Set(items.map((it) => it.topic.trim()));
      const selectedTopicIds: number[] = Array.isArray(tData?.topics)
        ? tData.topics
            .filter((r: any) => entered.has(String(r?.topic || '').trim()))
            .map((r: any) => Number(r?.topic_id))
            .filter((n: any) => Number.isFinite(n))
        : [];

      // 2) Trigger sequential generator that persists to user_posts
      const gResp = await fetch('/api/lites/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({
          user_id: user.user_id,
          max_per_topic: 1,
          ...(selectedTopicIds.length > 0 ? { topic_ids: selectedTopicIds } : {}),
        }),
      });
      const gCt = gResp.headers.get('content-type') || '';
      let gData: ApiResponse | null = null;
      if (gCt.includes('application/json')) {
        gData = await gResp.json().catch(() => null);
      }
      if (!gResp.ok) {
        throw new Error(gData?.detail || gData?.message || gData?.error || 'Failed to start generation');
      }
      // Start generation state; keep patience message visible until video ready
      setIsGenerating(true);
      setJobDirs([]); // no deterministic dirs from /generate; rely on SSE
      // Preload current videos list
      fetchMyVideos();
      fetchTopics();
    } catch (err: any) {
      setError(err?.message || "Something went wrong");
      setIsGenerating(false);
    } finally {
      setIsSubmitting(false);
    }
  };

  const onUnsubscribe = async (topicId: number) => {
    try {
      if (!user?.user_id) return;
      const resp = await fetch(`/api/lites/topics?user_id=${encodeURIComponent(user.user_id)}&topic_id=${encodeURIComponent(String(topicId))}`, { method: 'DELETE' });
      if (!resp.ok) return;
      await fetchTopics();
    } catch {}
  };

  const scrollToForm = () => {
    try {
      formRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch {
      try {
        window?.scrollTo?.({ top: 0, behavior: 'smooth' } as any);
      } catch {}
    }
  };

  const pollStatusOnce = async (dirs: string[]): Promise<LitesStatusJob[]> => {
    const qs = new URLSearchParams();
    dirs.forEach((d) => qs.append('dir', d));
    const resp = await fetch(`/api/lites/status?${qs.toString()}`, {
      method: 'GET',
      headers: { 'Accept': 'application/json' },
      cache: 'no-store',
    });
    if (!resp.ok) {
      // Non-fatal; return empty
      return [];
    }
    const data: LitesStatusResponse = await resp.json();
    return Array.isArray(data?.jobs) ? data.jobs : [];
  };

  const pollUntilReady = async (dirs: string[]) => {
    const start = Date.now();
    const timeoutMs = 10 * 60 * 1000; // 10 minutes
    const intervalMs = 2500;
    while (Date.now() - start < timeoutMs) {
      try {
        const jobs = await pollStatusOnce(dirs);
        const done = jobs.find((j) => j.status === 'completed' && j.video_url);
        if (done && typeof done.video_url === 'string') {
          setVideoUrl(done.video_url);
          setSuccess('Your Lite is ready!');
          setIsGenerating(false);
          return;
        }
      } catch {
        // Ignore and continue polling
      }
      await new Promise((r) => setTimeout(r, intervalMs));
    }
    setError('Timed out waiting for video. Please check later in My Videos.');
    setIsGenerating(false);
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="py-12 px-4 sm:px-6 lg:px-8">
        <div className="max-w-3xl mx-auto">
          {/* Header with Create Lites button */}
          <div className="flex items-center justify-between mb-4">
            <div>
              <h1 className="text-2xl font-bold text-gray-900">Lites</h1>
              <p className="text-gray-600 text-sm">Your 1-minute learning videos</p>
            </div>
            <button onClick={scrollToForm} className="px-4 py-2 text-sm font-semibold text-white bg-indigo-600 rounded-md hover:bg-indigo-700">
              Create Lites
            </button>
          </div>

          {/* Subscribed topics */}
          <div className="mb-8">
            <h2 className="text-sm font-semibold text-gray-800 mb-2">Subscribed Topics</h2>
            {topics.filter(t => t.active).length === 0 ? (
              <p className="text-sm text-gray-500">No active topics yet. Add topics below.</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {topics.filter(t => t.active).map(t => (
                  <span key={t.topic_id} className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-gray-100 text-gray-800 text-sm border">
                    <span className="font-medium truncate max-w-[200px]" title={`${t.topic} · ${t.minutes_per_day}m/d`}>{t.topic}</span>
                    <button
                      onClick={() => onUnsubscribe(t.topic_id)}
                      className="text-red-600 hover:text-red-700"
                      title="Unsubscribe"
                      aria-label={`Unsubscribe ${t.topic}`}
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>

          <div className="text-center mb-8" ref={formRef}>
            <h2 className="text-3xl font-bold text-gray-900 mb-2">Create Your Lites</h2>
            <p className="text-gray-600">Pick topics and daily packs to generate 1-minute learning lites</p>
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
                <div className="space-y-4">
                  {items.map((it, idx) => (
                    <div key={idx} className="border rounded-md p-4">
                      <div className="flex items-center justify-between mb-3">
                        <h3 className="text-sm font-semibold text-gray-800">Topic {idx + 1}</h3>
                        <div className="flex items-center gap-2">
                          {items.length > 1 && (
                            <button
                              type="button"
                              onClick={() => removeItem(idx)}
                              className="text-xs px-2 py-1 rounded bg-red-50 text-red-600 hover:bg-red-100"
                            >
                              Remove
                            </button>
                          )}
                        </div>
                      </div>

                      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                        <div className="sm:col-span-2">
                          <label className="block text-sm font-medium text-gray-700 mb-1">Topic</label>
                          <input
                            type="text"
                            value={it.topic}
                            onChange={(e) => updateItem(idx, { topic: e.target.value })}
                            placeholder="e.g., Science, World History, Python Basics"
                            className="w-full px-4 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-indigo-500 focus:border-indigo-500"
                            disabled={isSubmitting}
                            required
                          />
                        </div>
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">Daily Pack</label>
                          <select
                            value={it.minutes_per_day}
                            onChange={(e) => updateItem(idx, { minutes_per_day: Number(e.target.value) as TopicInput["minutes_per_day"] })}
                            className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-indigo-500 focus:border-indigo-500"
                            disabled={isSubmitting}
                          >
                            <option value={1}>1 min / day</option>
                            <option value={2}>2 min / day</option>
                            <option value={3}>3 min / day</option>
                            <option value={4}>4 min / day</option>
                            <option value={5}>5 min / day</option>
                            <option value={10}>10 min / day</option>
                            <option value={15}>15 min / day</option>
                          </select>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>

                <div className="flex items-center justify-between">
                  <button
                    type="button"
                    onClick={addItem}
                    disabled={isSubmitting || items.length >= 3}
                    className={`px-4 py-2 text-sm rounded-md border ${
                      items.length >= 3 ? "bg-gray-100 text-gray-400 cursor-not-allowed" : "bg-white hover:bg-gray-50"
                    }`}
                  >
                    Add another topic ({items.length}/3)
                  </button>

                  <button
                    type="submit"
                    disabled={!canSubmit()}
                    className={`inline-flex justify-center px-4 py-2 rounded-md text-sm font-medium text-white ${
                      !canSubmit() ? "bg-indigo-300 cursor-not-allowed" : "bg-indigo-600 hover:bg-indigo-700"
                    }`}
                  >
                    {isSubmitting ? "Starting…" : "Save & Generate"}
                  </button>
                </div>

                {isGenerating && (
                  <p className="mt-3 text-center text-sm font-bold text-gray-700" aria-live="polite">
                    Please be patient. Your Lites will be ready in a moment...
                  </p>
                )}

                {error && (
                  <div className="mt-3 p-3 bg-red-50 text-red-700 rounded-md text-sm" role="alert">
                    {error}
                  </div>
                )}
                {success && (
                  <div className="mt-3 p-3 bg-green-50 text-green-700 rounded-md text-sm" role="status">
                    {success}
                  </div>
                )}
              </form>
            </div>
          )}

          {/* Videos section: always visible below the form */}
          <div className="bg-white shadow rounded-lg p-6 mt-8">
            <div className="flex items-center justify-between mb-3">
              <h4 className="text-base font-semibold text-gray-900">Your Generated Videos</h4>
              <button
                type="button"
                onClick={() => fetchMyVideos()}
                className="text-sm text-indigo-600 hover:text-indigo-700"
              >
                Refresh
              </button>
            </div>
              {(() => {
                // Get current date in user's local timezone
                const now = new Date();
                
                // Helper to get start of day in local timezone
                const startOfDay = (date: Date) => {
                  const d = new Date(date);
                  d.setHours(0, 0, 0, 0);
                  return d;
                };
                
                const today = startOfDay(now);
                const yesterday = new Date(today);
                yesterday.setDate(yesterday.getDate() - 1);
                
                const isToday = (date: Date) => {
                  const d = new Date(date);
                  return d.getDate() === today.getDate() && 
                         d.getMonth() === today.getMonth() && 
                         d.getFullYear() === today.getFullYear();
                };
                
                const isYesterday = (date: Date) => {
                  const d = new Date(date);
                  return d.getDate() === yesterday.getDate() && 
                         d.getMonth() === yesterday.getMonth() && 
                         d.getFullYear() === yesterday.getFullYear();
                };

                const groups = {
                  today: [] as GridVideo[],
                  yesterday: [] as GridVideo[],
                  past: [] as GridVideo[],
                };
                
                // Process each video and categorize by date
                myVideos.forEach(video => {
                  const videoDate = new Date(video.createdAt);
                  
                  if (isNaN(videoDate.getTime())) {
                    groups.past.push(video);
                    return;
                  }
                  
                  if (isToday(videoDate)) {
                    groups.today.push(video);
                  } else if (isYesterday(videoDate)) {
                    groups.yesterday.push(video);
                  } else {
                    groups.past.push(video);
                  }
                });

                const renderGrid = (arr: GridVideo[]) => (
                  <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
                    {arr.map((video) => (
                      <div
                        key={video.id}
                        className="relative bg-white shadow rounded-lg hover:shadow-lg transition-shadow duration-200 cursor-pointer overflow-visible z-10"
                        onClick={() => { setSelectedVideo(video); setIsModalOpen(true); }}
                      >
                        <div className="relative pb-[56.25%] bg-black rounded-t-lg overflow-hidden">
                          {video.thumbnailUrl ? (
                            <div className="absolute inset-0">
                              <Image
                                src={video.thumbnailUrl}
                                alt={video.title}
                                fill
                                className="object-cover"
                                sizes="(max-width: 768px) 100vw, (max-width: 1200px) 50vw, 33vw"
                                unoptimized
                              />
                            </div>
                          ) : (
                            <div className="w-full h-full bg-gradient-to-br from-blue-600 to-purple-600 flex items-center justify-center text-white p-4 text-center">
                              <div className="relative w-16 h-16 mb-4">
                                <div className="absolute inset-0 bg-white/20 rounded-full animate-ping"></div>
                                <div className="absolute inset-0 flex items-center justify-center">
                                  <svg className="w-10 h-10" fill="currentColor" viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg">
                                    <path d="M6.3 2.841A1.5 1.5 0 004 4.11v11.78a1.5 1.5 0 002.3 1.269l9.344-5.89a1.5 1.5 0 000-2.538L6.3 2.84z" />
                                  </svg>
                                </div>
                              </div>
                            </div>
                          )}
                          {isToday(new Date(video.createdAt)) && (
                            <span className="absolute top-2 left-2 z-20 px-2 py-0.5 rounded bg-green-600 text-white text-xs font-semibold shadow">
                              New
                            </span>
                          )}
                          <div className="absolute inset-0 flex items-center justify-center opacity-0 hover:opacity-100 transition-opacity">
                            <div className="bg-black bg-opacity-50 rounded-full p-3">
                              <svg className="w-10 h-10 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"></path>
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                              </svg>
                            </div>
                          </div>
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
                );

                if (myVideos.length === 0) {
                  return <p className="text-sm text-gray-600">No videos yet. Generate one to see it here.</p>;
                }

                return (
                  <div className="space-y-8">
                    {groups.today.length > 0 && (
                      <section>
                        <h5 className="text-sm font-semibold text-gray-900 mb-3">Today</h5>
                        {renderGrid(groups.today)}
                      </section>
                    )}
                    {groups.yesterday.length > 0 && (
                      <section>
                        <h5 className="text-sm font-semibold text-gray-900 mb-3">Yesterday</h5>
                        {renderGrid(groups.yesterday)}
                      </section>
                    )}
                    {groups.past.length > 0 && (
                      <section>
                        <h5 className="text-sm font-semibold text-gray-900 mb-3">Past</h5>
                        {renderGrid(groups.past)}
                      </section>
                    )}
                  </div>
                );
              })()}
          </div>
        </div>
      </div>
      {/* Video Modal */}
      {isModalOpen && selectedVideo && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" role="dialog" aria-modal="true">
          {/* Backdrop */}
          <div className="absolute inset-0 bg-black/60" onClick={() => { setIsModalOpen(false); setSelectedVideo(null); }} />
          {/* Modal content */}
          <div className="relative z-10 w-full max-w-3xl mx-4 bg-white rounded-lg shadow-lg overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b">
              <h3 className="text-lg font-semibold truncate pr-4">{selectedVideo.title}</h3>
              <button
                onClick={() => { setIsModalOpen(false); setSelectedVideo(null); }}
                className="p-2 text-gray-500 hover:text-gray-700"
                aria-label="Close"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5">
                  <path fillRule="evenodd" d="M5.47 5.47a.75.75 0 011.06 0L12 10.94l5.47-5.47a.75.75 0 111.06 1.06L13.06 12l5.47 5.47a.75.75 0 11-1.06 1.06L12 13.06l-5.47 5.47a.75.75 0 01-1.06-1.06L10.94 12 5.47 6.53a.75.75 0 010-1.06z" clipRule="evenodd" />
                </svg>
              </button>
            </div>
            <div className="relative bg-black">
              <div className="relative pb-[56.25%]">
                <video src={selectedVideo.videoUrl} controls className="absolute inset-0 w-full h-full" autoPlay>
                  Your browser does not support the video tag.
                </video>
              </div>
            </div>
            <div className="px-4 py-3 border-t text-sm text-gray-600 flex items-center justify-between">
              <div className="truncate">Generated Lite</div>
              <div className="text-gray-500">{new Date(selectedVideo.createdAt).toLocaleString()}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function LitesPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-gray-50 flex items-center justify-center"><div className="text-gray-600">Loading…</div></div>}>
      <>
        <LitesPageContent />
        {/* Video Modal */}
        {/* Placed here to avoid re-rendering issues inside the form container */}
      </>
    </Suspense>
  );
}
