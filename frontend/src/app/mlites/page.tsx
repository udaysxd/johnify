"use client";

import { useEffect, useRef, useState, Suspense } from "react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";

type TopicInput = {
  topic: string;
  minutes_per_day: 1 | 2 | 3 | 4 | 5 | 10 | 15;
};

type ApiResponse = {
  status?: string;
  message?: string;
  jobs?: { topic: string; dir: string }[];
};

type GridVideo = { id: string; title: string; videoUrl: string; thumbnailUrl: string; createdAt: string; type?: string };

type UserTopic = {
  topic_id: number;
  topic: string;
  minutes_per_day: number;
  active: boolean;
};

function MLitesPageContent() {
  const router = useRouter();
  const { user, loading: isAuthLoading } = useAuth();
  const isAuthenticated = !!user;

  const [item, setItem] = useState<TopicInput>({ topic: "", minutes_per_day: 2 });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [jobDirs, setJobDirs] = useState<string[]>([]);
  const [sseConnected, setSseConnected] = useState<boolean>(false);
  const [myVideos, setMyVideos] = useState<GridVideo[]>([]);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [selectedVideo, setSelectedVideo] = useState<GridVideo | null>(null);
  const formRef = useRef<HTMLDivElement | null>(null);
  const [topics, setTopics] = useState<UserTopic[]>([]);

  const fetchMyVideos = async () => {
    try {
      const resp = await fetch('/api/videos/my-videos?type=mlites', { method: 'GET', headers: { 'Accept': 'application/json' }, cache: 'no-store' });
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
            type: typeof v.type === 'string' ? v.type.toLowerCase() : undefined,
          }))
          .filter(v => v.type === 'mlites' && !!v.videoUrl);
        mapped.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
        setMyVideos(mapped);
      }
    } catch {}
  };

  useEffect(() => {
    if (!isAuthLoading && !isAuthenticated) {
      router.push("/auth/signin");
    }
  }, [isAuthLoading, isAuthenticated, router]);

  useEffect(() => {
    if (!isAuthLoading && isAuthenticated) {
      fetchMyVideos();
      fetchTopics();
    }
  }, [isAuthLoading, isAuthenticated]);

  // SSE subscribe for mlites
  useEffect(() => {
    if (!user || !user.user_id) return;
    let es: EventSource | null = null;
    try {
      es = new EventSource(`/api/mlites/stream?user_id=${encodeURIComponent(user.user_id)}`);
      const onOpen = () => setSseConnected(true);
      const onError = () => setSseConnected(false);
      const onMLiteVideo = (ev: MessageEvent) => {
        try {
          const payload = JSON.parse(ev.data || '{}');
          if (!payload || typeof payload !== 'object') return;
          if (Array.isArray(jobDirs) && jobDirs.length > 0) {
            if (!payload.dir || !jobDirs.includes(String(payload.dir))) return;
          }
          fetchMyVideos();
          setSuccess('Your MLite is ready!');
          setIsGenerating(false);
        } catch {}
      };
      es.addEventListener('open', onOpen as any);
      es.addEventListener('error', onError as any);
      es.addEventListener('mlite_video', onMLiteVideo as any);
    } catch {
      setSseConnected(false);
    }
    return () => {
      try { es?.close(); } catch {}
    };
  }, [user?.user_id, jobDirs.join('|')]);

  const fetchTopics = async () => {
    try {
      if (!user?.user_id) return;
      const resp = await fetch(`/api/mlites/topics?user_id=${encodeURIComponent(user.user_id)}`, { cache: 'no-store' });
      if (!resp.ok) return;
      const data = await resp.json();
      const arr = Array.isArray(data?.topics) ? (data.topics as UserTopic[]) : [];
      setTopics(arr);
    } catch {}
  };

  const onUnsubscribe = async (topicId: number) => {
    try {
      if (!user?.user_id) return;
      const resp = await fetch(`/api/mlites/topics?user_id=${encodeURIComponent(user.user_id)}&topic_id=${encodeURIComponent(String(topicId))}`, { method: 'DELETE' });
      if (!resp.ok) return;
      await fetchTopics();
    } catch {}
  };

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

      // 1) Upsert mlites topics
      const topicsPayload = {
        user_id: user.user_id,
        topics: [{ topic: item.topic.trim(), minutes_per_day: item.minutes_per_day }],
      };
      const tResp = await fetch('/api/mlites/topics', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(topicsPayload),
      });
      if (!tResp.ok) {
        const err = await tResp.json().catch(() => ({} as any));
        throw new Error(err?.message || err?.detail || 'Failed to save topics');
      }
      await fetchTopics();

      // 2) Start mlites generation
      const genPayload = {
        user_id: user.user_id,
        topics: [{ topic: item.topic.trim(), minutes_per_day: item.minutes_per_day }],
      };
      const resp = await fetch('/api/mlites', {
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
        throw new Error((data as any)?.message || 'Failed to start mlites');
      }
      const dirs = Array.isArray(data?.jobs) ? data!.jobs!.map(j => j.dir).filter(Boolean) : [];
      setJobDirs(dirs);
      setIsGenerating(true);
      fetchMyVideos();
    } catch (err: any) {
      setError(err?.message || 'Something went wrong');
      setIsGenerating(false);
    } finally {
      setIsSubmitting(false);
    }
  };

  const scrollToForm = () => {
    try {
      formRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch {
      try { window?.scrollTo?.({ top: 0, behavior: 'smooth' } as any); } catch {}
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="py-12 px-4 sm:px-6 lg:px-8">
        <div className="max-w-3xl mx-auto">
          <div className="flex items-center justify-between mb-4">
            <div></div>
            <button onClick={scrollToForm} className="px-4 py-2 text-sm font-semibold text-white bg-indigo-600 rounded-md hover:bg-indigo-700">
              Create MLites
            </button>
          </div>

          {/* Subscribed topics */}
          <div className="mb-8">
            <h2 className="text-sm font-semibold text-gray-800 mb-2">Subscribed Topics</h2>
            {topics.filter(t => t.active).length === 0 ? (
              <p className="text-sm text-gray-500">No active topics yet. Add a topic below.</p>
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
            <h2 className="text-3xl font-bold text-gray-900 mb-2">Create Your MLite</h2>
            <p className="text-gray-600">Enter a topic to generate a vertical video</p>
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
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <div className="sm:col-span-2">
                    <label className="block text-sm font-medium text-gray-700 mb-1">Topic</label>
                    <input
                      type="text"
                      value={item.topic}
                      onChange={(e) => setItem((it) => ({ ...it, topic: e.target.value }))}
                      placeholder="e.g., Python Tips, World War II, Nutrition"
                      className="w-full px-4 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-indigo-500 focus:border-indigo-500"
                      disabled={isSubmitting}
                      required
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Daily Pack</label>
                    <select
                      value={item.minutes_per_day}
                      onChange={(e) => setItem((it) => ({ ...it, minutes_per_day: Number(e.target.value) as TopicInput["minutes_per_day"] }))}
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

                <div className="flex items-center justify-end">
                  <button
                    type="submit"
                    disabled={!canSubmit()}
                    className={`inline-flex justify-center px-4 py-2 rounded-md text-sm font-medium text-white ${!canSubmit() ? "bg-indigo-300 cursor-not-allowed" : "bg-indigo-600 hover:bg-indigo-700"}`}
                  >
                    {isSubmitting ? "Starting…" : "Generate MLite"}
                  </button>
                </div>

                {isGenerating && (
                  <p className="mt-3 text-center text-sm font-bold text-gray-700" aria-live="polite">
                    Please be patient. Your MLite will be ready shortly...
                  </p>
                )}
                {error && <div className="mt-3 p-3 bg-red-50 text-red-700 rounded-md text-sm" role="alert">{error}</div>}
                {success && <div className="mt-3 p-3 bg-green-50 text-green-700 rounded-md text-sm" role="status">{success}</div>}
              </form>
            </div>
          )}

          {/* Videos */}
          <div className="bg-white shadow rounded-lg p-6 mt-8">
            <div className="flex items-center justify-between mb-3">
              <h4 className="text-base font-semibold text-gray-900">Your MLites</h4>
              <button type="button" onClick={() => fetchMyVideos()} className="text-sm text-indigo-600 hover:text-indigo-700">Refresh</button>
            </div>
            {myVideos.length === 0 ? (
              <p className="text-sm text-gray-600">No MLites yet. Generate one to see it here.</p>
            ) : (
              <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
                {myVideos.map((video) => (
                  <div key={video.id} className="relative bg-white shadow rounded-lg hover:shadow-lg transition-shadow duration-200 cursor-pointer overflow-visible z-10" onClick={() => { setSelectedVideo(video); setIsModalOpen(true); }}>
                    <div className="relative pb-[177.78%] bg-black rounded-t-lg overflow-hidden">{/* 9:16 ratio -> 1080x1920 */}
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
              <div className="truncate">Generated MLite</div>
              <div className="text-gray-500">{new Date(selectedVideo.createdAt).toLocaleString()}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function MLitesPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-gray-50 flex items-center justify-center"><div className="text-gray-600">Loading…</div></div>}>
      <>
        <MLitesPageContent />
      </>
    </Suspense>
  );
}
