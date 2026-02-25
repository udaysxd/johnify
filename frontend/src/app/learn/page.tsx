'use client';

import { useState, useEffect, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Image from 'next/image';
import { useAuth } from '@/contexts/AuthContext';

// Response shape from /api/learn
interface LearnResponse {
  status?: string;
  video_url?: string;
  message?: string;
  error?: string;
  details?: string;
  detail?: string;
}

type FeedVideo = {
  id: string;
  title: string;
  thumbnailUrl: string;
  videoUrl: string;
  createdAt: string;
  status: 'processing' | 'completed' | 'failed';
  userId?: string;
  userName?: string;
  tags?: string[];
};

function LearnPageContent() {
  const { user, loading: isAuthLoading } = useAuth();
  const isAuthenticated = !!user;
  const [topic, setTopic] = useState('');
  const complexity = 3; // Fixed intermediate complexity level
  const [isLoading, setIsLoading] = useState(false);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [progressPct, setProgressPct] = useState<number | null>(null);
  const [feedSimilar, setFeedSimilar] = useState<FeedVideo[]>([]);
  const [feedOthers, setFeedOthers] = useState<FeedVideo[]>([]);
  const [feedLoading, setFeedLoading] = useState(false);
  const [showFeed, setShowFeed] = useState(false);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [selectedVideo, setSelectedVideo] = useState<FeedVideo | null>(null);
  const router = useRouter();
  const searchParams = useSearchParams();

  // Prefill topic from query string
  useEffect(() => {
    const q = searchParams.get('topic');
    if (q && !topic) {
      setTopic(q);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  // Redirect to login if not authenticated
  useEffect(() => {
    if (!isAuthLoading && !isAuthenticated) {
      router.push('/auth/signin');
    }
  }, [isAuthenticated, isAuthLoading, router]);

  const generateVideo = async (requestedTopic: string) => {
    const trimmed = requestedTopic.trim();
    if (!trimmed) return;

    setIsLoading(true);
    setError(null);
    // reset progress state for a fresh run
    setProgressPct(0);
    // reset transient fields

    try {
      const userEmail = user?.user_email;
      // Precompute tags (single source of truth) and send along with generation request
      const precomputedTags = await fetchPrecomputedTags(trimmed);
      const response = await fetch('/api/learn', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: JSON.stringify({
          topic: trimmed,
          complexity_level: complexity,
          user_email: userEmail || 'anonymous@example.com',
          tags: precomputedTags,
        }),
      });

      const contentType = response.headers.get('content-type') || '';
      let data: LearnResponse | null = null;
      if (contentType.includes('application/json')) {
        data = await response.json().catch(() => null);
      } else {
        // Try to parse as text then JSON; otherwise, construct an informative error
        const textBody = await response.text().catch(() => '');
        try {
          data = JSON.parse(textBody) as LearnResponse;
        } catch {
          if (!response.ok) {
            throw new Error(
              `Backend error (${response.status}): ${response.statusText || 'Unknown'}\n` +
              `${textBody?.slice(0, 300) || 'No body'}`
            );
          } else {
            throw new Error(
              'Received non-JSON success body from server. Please try again later.'
            );
          }
        }
      }
      if (!response.ok) {
        throw new Error(
          data?.detail || data?.message || data?.error || 'Failed to generate learning video'
        );
      }

      if (!data || !data.video_url) {
        console.error('No video_url in response:', data);
        throw new Error('Received invalid response from server: missing video URL');
      }

      const videoPath = data.video_url;
      if (typeof videoPath !== 'string') {
        console.error('Invalid video_url format:', videoPath);
        throw new Error('Received invalid video URL format from server');
      }

      setVideoUrl(videoPath);
    } catch (err) {
      console.error('Error generating learning video:', err);
      setError(err instanceof Error ? err.message : 'An unknown error occurred');
    } finally {
      setIsLoading(false);
    }
  };

  // Subscribe to Learn progress SSE
  useEffect(() => {
    if (!user || !user.user_id) return;
    let es: EventSource | null = null;
    try {
      es = new EventSource(`/api/learn/stream?user_id=${encodeURIComponent(user.user_id)}`);
      const onLearnProgress = (ev: MessageEvent) => {
        try {
          const payload = JSON.parse(ev.data || '{}');
          if (!payload || typeof payload !== 'object') return;
          // accept only kind learn if present
          if (payload.kind && payload.kind !== 'learn') return;
          const pct = typeof payload.pct === 'number' ? payload.pct : undefined;
          if (pct !== undefined) setProgressPct(Math.max(0, Math.min(100, pct)));
        } catch {}
      };
      es.addEventListener('learn_progress', onLearnProgress);
    } catch {
      // swallow
    }
    return () => {
      try { es?.close(); } catch {}
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.user_id]);

  // Get DeepSeek-generated tags first (retry a few times), then use those to fetch the feed
  const fetchPrecomputedTags = async (t: string): Promise<string[]> => {
    const topicNorm = (t || '').trim();
    if (!topicNorm) return [];
    const maxAttempts = 3;
    let attempt = 0;
    while (attempt < maxAttempts) {
      attempt += 1;
      try {
        const resp = await fetch('/api/videos/generate-tags?' + new URLSearchParams({ topic: topicNorm }).toString(), {
          method: 'GET',
          headers: { 'Content-Type': 'application/json' },
          cache: 'no-store',
        });
        if (!resp.ok) {
          const txt = await resp.text().catch(() => '');
          console.warn('generate-tags error:', txt);
        } else {
          const data = await resp.json();
          const tags: string[] = Array.isArray(data?.tags) ? data.tags.map(String) : [];
          const source: string = typeof data?.source === 'string' ? data.source : 'unknown';
          console.log(`generate-tags attempt=${attempt} source=${source} tags=`, tags);
          if (tags.length > 0 && source === 'deepseek') return tags;
        }
      } catch (e) {
        console.warn('generate-tags exception:', e);
      }
      // brief backoff
      await new Promise((r) => setTimeout(r, 800));
    }
    return [];
  };

  // Fetch learn feed based on topic
  const fetchLearnFeed = async (t: string) => {
    const q = (t || '').trim();
    if (!q) return;
    try {
      setFeedLoading(true);
      console.log('Fetching learn feed for topic:', q);
      // 1) Precompute DeepSeek tags
      const tags = await fetchPrecomputedTags(q);
      // 2) Call Next.js API route; pass precomputed tags when present
      const params = new URLSearchParams({
        topic: q,
        limit_similar: '9',
        limit_others: '18',
      });
      if (tags.length > 0) params.set('tags', JSON.stringify(tags));
      const resp = await fetch(`/api/videos/learn-feed?` + params.toString(), {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
        cache: 'no-store',
      });
      
      console.log('Learn feed response status:', resp.status);
      if (!resp.ok) {
        const errorText = await resp.text();
        let errorData;
        try {
          errorData = JSON.parse(errorText);
        } catch {
          errorData = { error: errorText };
        }
        console.error('Failed to fetch learn feed:', errorData);
        return;
      }
      
      const data = await resp.json();
      console.log('Learn feed data:', data);
      // API route returns keys: similar, others, queryTags
      setFeedSimilar(Array.isArray(data?.similar) ? data.similar : []);
      setFeedOthers(Array.isArray(data?.others) ? data.others : []);
    } catch (error) {
      console.error('Error in fetchLearnFeed:', error);
    } finally {
      setFeedLoading(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    // Prevent early clicks before auth is ready or if already processing
    if (isAuthLoading || !isAuthenticated || isLoading) return;
    if (!topic.trim()) return;
    
    // Show feed section only after user initiates generation
    setShowFeed(true);
    // Show feed immediately with loading state
    fetchLearnFeed(topic).catch(console.error);
    
    // Start video generation in the background
    generateVideo(topic).catch(console.error);
  };

  // Autostart if ?autostart=1 and topic present
  useEffect(() => {
    if (isAuthLoading) return;
    if (!isAuthenticated) return;
    const auto = searchParams.get('autostart');
    const q = (searchParams.get('topic') || topic || '').trim();
    if (auto && q && !isLoading && !videoUrl) {
      generateVideo(q);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthenticated, isAuthLoading, searchParams, topic]);

  return (
    <div className="min-h-screen bg-[var(--color-background)]">
      <div className="py-12 px-4 sm:px-6 lg:px-8">
        <div className="max-w-3xl mx-auto">
          <div className="text-center mb-8">
            <h1 className="text-3xl font-bold text-[var(--color-foreground)] mb-2">Learn Something New</h1>
            <p className="text-gray-600">Enter a topic and we&#39;ll generate an educational video for you</p>
          </div>

          {isAuthLoading ? (
            <div className="min-h-[200px] flex items-center justify-center">
              <div className="text-center">
                <div className="w-12 h-12 border-4 border-[var(--color-secondary)] border-t-transparent rounded-full animate-spin mx-auto"></div>
                <p className="mt-4 text-gray-600">Loading...</p>
              </div>
            </div>
          ) : !videoUrl ? (
            <div className="bg-white shadow rounded-lg p-6">
              <form onSubmit={handleSubmit} className="space-y-6">
                <div>
                  <label htmlFor="topic" className="block text-sm font-medium text-gray-700 mb-1">
                    What would you like to learn about?
                  </label>
                  <input
                    type="text"
                    id="topic"
                    value={topic}
                    onChange={(e) => setTopic(e.target.value)}
                    className="w-full px-4 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-2 focus:ring-[var(--color-secondary)] focus:border-[var(--color-secondary)]"
                    placeholder="e.g., Ancient Rome, Machine Learning, Pasta recipe"
                    disabled={isLoading}
                    required
                  />
                </div>

                <div>
                  <button
                    type="submit"
                    disabled={isAuthLoading || !isAuthenticated || isLoading || !topic.trim()}
                    className={`w-full flex justify-center py-3 px-4 rounded-md shadow-sm text-sm font-medium btn-primary ${
                      isAuthLoading || !isAuthenticated || isLoading || !topic.trim() ? 'opacity-50 cursor-not-allowed' : ''
                    }`}
                  >
                    {isLoading ? 'Generating Video...' : 'Generate Learning Video'}
                  </button>
                </div>
                {isLoading && (
                  <div className="mt-4" aria-live="polite">
                    {/* removed stage and ETA labels */}
                    <div className="w-full bg-gray-200 rounded h-2 overflow-hidden">
                      <div
                        className="h-2 transition-all bg-[var(--color-primary)]"
                        style={{ width: `${Math.round(progressPct ?? 5)}%` }}
                      />
                    </div>
                    <div className="mt-2 text-xs text-gray-600">
                      Please be patient. It takes a few minutes to generate.
                    </div>
                  </div>
                )}
              </form>
            
            {error && (
              <div className="mt-4 p-3 bg-red-50 text-red-700 rounded-md text-sm">
                {error}
              </div>
            )}
            
            {/* Feed section - only render after data is fetched and there are items */}
            {showFeed && !feedLoading && (feedSimilar.length > 0 || feedOthers.length > 0) && (
              <div className="mt-8">
                {/* Similar Videos */}
                {feedSimilar.length > 0 && (
                  <section className="mb-10">
                    <div className="flex items-center justify-between mb-3">
                      <h4 className="text-base font-semibold text-gray-900">Similar Videos</h4>
                    </div>
                    <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
                      {(feedSimilar || []).map((video) => (
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
                              <h3 className="text-base font-medium text-gray-900 truncate">
                                {video.title}
                              </h3>
                            </div>
                            <p className="mt-1 text-sm text-gray-500">{new Date(video.createdAt).toLocaleString()}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </section>
                )}

                {/* Other Videos */}
                {feedOthers.length > 0 && (
                  <section>
                    <div className="flex items-center justify-between mb-3">
                      <h4 className="text-base font-semibold text-gray-900">Explore Other Videos from Our Learners</h4>
                    </div>
                    <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
                      {(feedOthers || []).map((video) => (
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
                              <h3 className="text-base font-medium text-gray-900 truncate">
                                {video.title}
                              </h3>
                            </div>
                            <p className="mt-1 text-sm text-gray-500">{new Date(video.createdAt).toLocaleString()}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </section>
                )}
              </div>
            )}
          </div>
        ) : (
          <div className="bg-white shadow rounded-lg p-6 text-center">
            <h2 className="text-xl font-semibold mb-4">Your Learning Video is Ready!</h2>
            <div className="aspect-w-16 aspect-h-9 bg-black rounded-lg overflow-hidden mb-6">
              <video 
                src={videoUrl || undefined} 
                controls 
                className="w-full h-full"
                autoPlay
              >
                Your browser does not support the video tag.
              </video>
            </div>
            <div className="space-x-4">
              <button
                onClick={() => setVideoUrl(null)}
                className="inline-flex items-center px-4 py-2 text-sm font-medium rounded-md shadow-sm btn-primary"
              >
                Create Another Video
              </button>
              <button
                onClick={() => router.push('/')}
                className="inline-flex items-center px-4 py-2 text-sm font-medium rounded-md btn-outline"
              >
                Back to Home
              </button>
            </div>
          </div>
        )}
          {/* end panel or form/video container */}
        </div>
        {/* end max-w container */}
      </div>
      {/* end padding container */}

      {/* Video Modal */}
      {isModalOpen && selectedVideo && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center"
          role="dialog"
          aria-modal="true"
        >
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/60"
            onClick={() => { setIsModalOpen(false); setSelectedVideo(null); }}
          />
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
                <video
                  src={selectedVideo.videoUrl}
                  controls
                  className="absolute inset-0 w-full h-full"
                  autoPlay
                >
                  Your browser does not support the video tag.
                </video>
              </div>
            </div>
            <div className="px-4 py-3 border-t text-sm text-gray-600 flex items-center justify-between">
              <div className="truncate">
                {selectedVideo.userName ? `by ${selectedVideo.userName}` : 'Public video'}
              </div>
              <div className="text-gray-500">{new Date(selectedVideo.createdAt).toLocaleString()}</div>
            </div>
          </div>
        </div>
      )}
    </div>
    /* end outer min-h container */
  );
}

export default function LearnPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-gray-50 flex items-center justify-center"><div className="text-gray-600">Loading…</div></div>}>
      <LearnPageContent />
    </Suspense>
  );
}
