'use client';

import { useEffect, useRef, useState } from 'react';
import Image from 'next/image';
import Link from 'next/link';
import { useAuth } from '@/contexts/AuthContext';

type Video = {
  id: string;
  title: string;
  thumbnailUrl: string;
  videoUrl: string;
  createdAt: string;
  status: 'processing' | 'completed' | 'failed';
  userId?: string;
  userName?: string;
  // Optional likes metadata if backend starts including it
  likesCount?: number;
};

// Helper to safely extract a creator name without using `any`
function extractCreatorName(v: Video): string | null {
  // Known field on our type
  if (typeof v.userName === 'string' && v.userName.trim()) return v.userName;
  // Potential alternate keys from backend variations
  const rec = v as unknown as Record<string, unknown>;
  const candidates = ['user_name', 'creatorName', 'authorName', 'author'] as const;
  for (const key of candidates) {
    const val = rec[key];
    if (typeof val === 'string' && val.trim()) return val;
  }
  return null;
}

export default function FeedPage() {
  const [videos, setVideos] = useState<Video[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedVideo, setSelectedVideo] = useState<Video | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const modalRef = useRef<HTMLDivElement>(null);
  const { user } = useAuth();
  const timeAgo = (isoDate: string): string => {
    const now = Date.now();
    const then = new Date(isoDate).getTime();
    if (isNaN(then)) return '';
    const diff = Math.max(0, now - then);
    const sec = Math.floor(diff / 1000);
    if (sec < 60) return `${sec || 1} second${sec === 1 ? '' : 's'} ago`;
    const min = Math.floor(sec / 60);
    if (min < 60) return `${min} minute${min === 1 ? '' : 's'} ago`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr} hour${hr === 1 ? '' : 's'} ago`;
    const day = Math.floor(hr / 24);
    if (day < 30) return `${day} day${day === 1 ? '' : 's'} ago`;
    const mon = Math.floor(day / 30);
    if (mon < 12) return `${mon} month${mon === 1 ? '' : 's'} ago`;
    const yr = Math.floor(day / 365);
    return `${yr} year${yr === 1 ? '' : 's'} ago`;
  };

  // Local like state: counts per post and which posts the current session has liked
  const [likeCounts, setLikeCounts] = useState<Record<string, number>>({});
  const [likedByMe, setLikedByMe] = useState<Set<string>>(new Set());

  useEffect(() => {
    const fetchFeed = async () => {
      try {
        setIsLoading(true);
        setError(null);
        const resp = await fetch('/api/videos/feed', {
          method: 'GET',
          headers: { 'Content-Type': 'application/json' },
          cache: 'no-store',
        });
        if (!resp.ok) {
          const raw = await resp.json().catch(() => ({}));
          let message: string | undefined;
          if (raw && typeof raw === 'object') {
            const obj = raw as Record<string, unknown>;
            const first = ['error', 'detail', 'message']
              .map((k) => obj[k])
              .find((v): v is string => typeof v === 'string');
            message = first;
          }
          throw new Error(message ?? `Failed to fetch feed: ${resp.statusText}`);
        }
        const data = (await resp.json()) as Video[];
        const list = Array.isArray(data) ? data : [];
        setVideos(list);
        // Seed likeCounts from payload if present
        const seed: Record<string, number> = {};
        for (const v of list) {
          if (typeof v.likesCount === 'number') seed[v.id] = v.likesCount;
        }
        setLikeCounts((prev) => ({ ...seed, ...prev }));
      } catch (e) {
        setError(e instanceof Error ? e.message : 'An error occurred');
      } finally {
        setIsLoading(false);
      }
    };
    fetchFeed();
  }, []);

  // Fetch like counts for each video (best effort, non-blocking)
  useEffect(() => {
    if (!videos.length) return;
    const abort = new AbortController();
    (async () => {
      try {
        const results = await Promise.all(
          videos.map(async (v) => {
            try {
              const r = await fetch(`/api/videos/${encodeURIComponent(v.id)}/likes`, { signal: abort.signal, cache: 'no-store' });
              if (!r.ok) return [v.id, undefined] as const;
              const data = await r.json();
              // Support either {likes_count} object or primitive number
              const count = typeof data === 'number' ? data : (typeof data?.likes_count === 'number' ? data.likes_count : undefined);
              return [v.id, count] as const;
            } catch {
              return [v.id, undefined] as const;
            }
          })
        );
        const merged: Record<string, number> = {};
        for (const [id, count] of results) {
          if (typeof count === 'number') merged[id] = count;
        }
        if (Object.keys(merged).length) setLikeCounts((prev) => ({ ...prev, ...merged }));
      } catch {}
    })();
    return () => abort.abort();
  }, [videos]);

  const canLike = (v: Video) => {
    if (!user) return true; // allow anonymous/session based like; backend should enforce auth rules if needed
    if (v.userId && String(v.userId) === String(user.user_id)) return false; // cannot like own video
    return true;
  };

  const handleLike = async (v: Video) => {
    if (!canLike(v)) return;
    if (likedByMe.has(v.id)) return; // prevent double-like in session
    // optimistic update
    setLikeCounts((prev) => ({ ...prev, [v.id]: (prev[v.id] ?? 0) + 1 }));
    setLikedByMe((prev) => new Set(prev).add(v.id));
    try {
      const resp = await fetch(`/api/videos/${encodeURIComponent(v.id)}/likes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'like' }),
      });
      if (!resp.ok) throw new Error('Failed to like');
      const data = await resp.json().catch(() => ({}));
      const newCount = typeof data === 'number' ? data : (typeof data?.likes_count === 'number' ? data.likes_count : undefined);
      if (typeof newCount === 'number') setLikeCounts((prev) => ({ ...prev, [v.id]: newCount }));
    } catch (e) {
      // revert on error
      setLikeCounts((prev) => ({ ...prev, [v.id]: Math.max(0, (prev[v.id] ?? 1) - 1) }));
      setLikedByMe((prev) => {
        const s = new Set(prev);
        s.delete(v.id);
        return s;
      });
    }
  };

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (modalRef.current && !modalRef.current.contains(event.target as Node)) {
        setSelectedVideo(null);
      }
    }
    if (selectedVideo) {
      document.addEventListener('mousedown', handleClickOutside);
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = 'auto';
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.body.style.overflow = 'auto';
    };
  }, [selectedVideo]);

  // Show only videos created by other users when logged in
  const visibleVideos = user ? videos.filter((v) => v.userId !== user.user_id) : videos;

  useEffect(() => {
    if (selectedVideo && videoRef.current) {
      try { videoRef.current.load(); } catch {}
      setTimeout(async () => {
        try { await videoRef.current?.play(); } catch {}
      }, 0);
    }
  }, [selectedVideo]);

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-100">
        <div className="container mx-auto px-4 py-8">
          <h1 className="text-3xl font-bold mb-6">Public Feed</h1>
          <div className="flex justify-center items-center h-64">
            <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-blue-500"></div>
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gray-100">
        <div className="container mx-auto px-4 py-8">
          <h1 className="text-3xl font-bold mb-6">Public Feed</h1>
          <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded relative" role="alert">
            <strong className="font-bold">Error: </strong>
            <span className="block sm:inline">{error}</span>
          </div>
          <div className="mt-4">
            <button onClick={() => window.location.reload()} className="bg-blue-600 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded">
              Refresh Page
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="py-8 px-4 sm:px-6 lg:px-8">
        <div className="max-w-7xl mx-auto">
          <div className="flex justify-between items-center mb-8">
            <h1 className="text-3xl font-bold text-gray-900">Public Feed</h1>
            <Link
              href="/tutor"
              className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
            >
              Create My Tutor
            </Link>
          </div>

          {visibleVideos.length === 0 ? (
            <div className="text-center py-12">
              <svg className="mx-auto h-12 w-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2z" />
              </svg>
              <h3 className="mt-2 text-sm font-medium text-gray-900">No videos yet.</h3>
              <p className="mt-1 text-sm text-gray-500">Be the first to create one.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
              {visibleVideos.map((video) => (
                <div
                  key={video.id}
                  className="bg-white overflow-hidden shadow rounded-lg hover:shadow-lg transition-shadow duration-200 cursor-pointer"
                  onClick={() => setSelectedVideo(video)}
                >
                  <div className="relative pb-[56.25%] bg-black">
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
                      <div className="w-full h-full bg-gradient-to-br from-blue-600 to-purple-600 flex flex-col items-center justify-center text-white p-4 text-center">
                        <div className="relative w-16 h-16 mb-4">
                          <div className="absolute inset-0 bg-white/20 rounded-full animate-ping"></div>
                          <div className="absolute inset-0 flex items-center justify-center">
                            <svg className="w-10 h-10" fill="currentColor" viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg">
                              <path d="M6.3 2.841A1.5 1.5 0 004 4.11v11.78a1.5 1.5 0 002.3 1.269l9.344-5.89a1.5 1.5 0 000-2.538L6.3 2.84z" />
                            </svg>
                          </div>
                        </div>
                        {/* No title text on top of the image, to match my-learning */}
                      </div>
                    )}
                    {video.status === 'processing' && (
                      <div className="absolute inset-0 bg-black bg-opacity-50 flex items-center justify-center">
                        <div className="text-white text-center">
                          <div className="w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto"></div>
                          <p className="mt-2 text-sm">Processing</p>
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
                  <div className="px-4 pb-3 pt-3">
                    <div className="flex items-center justify-between gap-3">
                      <h3 className="text-base font-medium text-gray-900 truncate">
                        {video.title || 'Untitled Video'}
                      </h3>
                      <button
                        className={`flex items-center gap-1 px-2 py-1 rounded text-sm ${
                          likedByMe.has(video.id)
                            ? 'text-red-600 hover:bg-red-50'
                            : canLike(video)
                              ? 'text-gray-600 hover:bg-gray-100'
                              : 'text-gray-400 cursor-not-allowed'
                        }`}
                        title={canLike(video) ? (likedByMe.has(video.id) ? 'Liked' : 'Like') : "You can't like your own video"}
                        onClick={(e) => { e.stopPropagation(); handleLike(video); }}
                        disabled={!canLike(video) || likedByMe.has(video.id)}
                        aria-label={likedByMe.has(video.id) ? 'Liked' : 'Like'}
                        aria-pressed={likedByMe.has(video.id)}
                      >
                        {/* Heart like icon */}
                        {likedByMe.has(video.id) ? (
                          // Filled heart (liked)
                          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
                            <path d="M11.645 20.91l-.007-.003-.022-.012a15.247 15.247 0 01-.383-.218 25.18 25.18 0 01-4.244-3.17C4.688 15.36 2.25 12.462 2.25 9.003 2.25 6.387 4.357 4.5 6.75 4.5c1.503 0 2.86.654 3.75 1.68A5.123 5.123 0 0114.25 4.5c2.393 0 4.5 1.887 4.5 4.503 0 3.46-2.438 6.358-4.739 8.504a25.175 25.175 0 01-4.244 3.17 15.247 15.247 0 01-.383.218l-.022.012-.007.003a.75.75 0 01-.645 0z" />
                          </svg>
                        ) : (
                          // Outline heart (not liked)
                          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-4 w-4">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M21 8.25c0-2.485-2.015-4.5-4.5-4.5-1.86 0-3.456 1.116-4.125 2.709-.669-1.593-2.265-2.709-4.125-2.709C5.015 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12z" />
                          </svg>
                        )}
                        <span>{likeCounts[video.id] ?? 0}</span>
                      </button>
                    </div>
                    {(() => {
                      const creatorName = extractCreatorName(video);
                      return creatorName ? (
                        <p className="mt-0.5 text-sm text-gray-700 font-medium">{creatorName}</p>
                      ) : null;
                    })()}
                    <p className="text-sm text-gray-500">{timeAgo(video.createdAt)}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Video Modal */}
      {selectedVideo && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80">
          <div ref={modalRef} className="relative w-full max-w-4xl bg-white rounded-lg overflow-hidden shadow-xl">
            <div className="relative pt-[56.25%] bg-black">
              {(() => {
                const proxySrc = `/api/proxy-video?url=${encodeURIComponent(selectedVideo.videoUrl)}`;
                return (
                  <video
                    key={selectedVideo.id}
                    ref={videoRef}
                    className="absolute top-0 left-0 w-full h-full"
                    controls
                    autoPlay
                    crossOrigin="anonymous"
                    playsInline
                    preload="auto"
                    src={proxySrc}
                    onEnded={() => videoRef.current?.pause()}
                    onLoadedMetadata={() => {
                      videoRef.current?.play().catch(() => {});
                    }}
                    onError={() => {}}
                  >
                    <source src={proxySrc} type="video/mp4" />
                    Your browser does not support the video tag.
                  </video>
                );
              })()}
              <button
                onClick={() => setSelectedVideo(null)}
                className="absolute top-4 right-4 p-2 rounded-full bg-black/50 text-white hover:bg-black/70 transition-colors"
                aria-label="Close"
              >
                <svg xmlns="http://www.w3.org/2000/svg" className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="p-6">
              <h2 className="text-2xl font-bold text-gray-900">{selectedVideo.title}</h2>
              {(() => {
                const creatorName = extractCreatorName(selectedVideo);
                return creatorName ? (
                  <p className="mt-2 text-gray-800 font-medium">{creatorName}</p>
                ) : null;
              })()}
              <p className="mt-1 text-gray-600">{timeAgo(selectedVideo.createdAt)}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
