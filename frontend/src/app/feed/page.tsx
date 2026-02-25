'use client';

import { useEffect, useState } from 'react';
import Image from 'next/image';
import Link from 'next/link';
import { useAuth } from '@/contexts/AuthContext';
import VideoModal from '@/components/VideoModal';

type Video = {
  id: string;
  title: string;
  thumbnailUrl: string;
  videoUrl: string;
  createdAt: string;
  status: 'processing' | 'completed' | 'failed';
  userId?: string;
  userName?: string;
  profilePicUrl?: string;
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
  const [shareOpenId, setShareOpenId] = useState<string | null>(null);
  const { user } = useAuth();
  // Capitalize the first alphabetical character, ignoring leading spaces/punctuation
  const capitalizeFirst = (s?: string): string => {
    if (!s) return 'Untitled Video';
    const match = s.match(/[A-Za-z]/);
    if (!match) return s.trim() ? s : 'Untitled Video';
    const i = match.index as number;
    return s.slice(0, i) + s.charAt(i).toUpperCase() + s.slice(i + 1);
  };

  // Build canonical share URL like https://johnify.com/lites/<video path>
  const canonicalLinkFor = (videoUrl: string | undefined): string => {
    if (!videoUrl) return '';
    try {
      const base = typeof window !== 'undefined' ? window.location.origin : 'https://johnify.com';
      const u = new URL(videoUrl, base);
      const idx = u.pathname.indexOf('/videos/');
      if (idx >= 0) {
        const rel = u.pathname.slice(idx + '/videos/'.length).replace(/^\/+/, '');
        return `https://johnify.com/lites/${rel}`;
      }
      const p = u.pathname.replace(/^\/+/, '');
      return `https://johnify.com/lites/${p}`;
    } catch {
      return '';
    }
  };
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

  // Reactions state
  const [reactions, setReactions] = useState<Record<string, { likes: number; dislikes: number }>>({});
  const [myReactions, setMyReactions] = useState<Record<string, -1 | 0 | 1>>({});
  const [saved, setSaved] = useState<Record<string, boolean>>({});

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
        // Seed reactions if backend sends likesCount (legacy) - map to likes only
        const seed: Record<string, { likes: number; dislikes: number }> = {};
        for (const v of list) {
          if (typeof v.likesCount === 'number') seed[v.id] = { likes: v.likesCount, dislikes: 0 };
        }
        if (Object.keys(seed).length) setReactions((prev) => ({ ...seed, ...prev }));
      } catch (e) {
        setError(e instanceof Error ? e.message : 'An error occurred');
      } finally {
        setIsLoading(false);
      }
    };
    fetchFeed();
  }, []);

  // Fetch reactions for each video (best effort, non-blocking)
  useEffect(() => {
    if (!videos.length) return;
    const abort = new AbortController();
    (async () => {
      try {
        const results = await Promise.all(
          videos.map(async (v) => {
            try {
              const r = await fetch(`/api/videos/${encodeURIComponent(v.id)}/reaction`, { signal: abort.signal, cache: 'no-store' });
              if (!r.ok) return [v.id, undefined] as const;
              const data = await r.json();
              // Expected: { likes, dislikes, my_reaction }
              if (typeof data?.likes === 'number' && typeof data?.dislikes === 'number') {
                const likes = data.likes as number;
                const dislikes = data.dislikes as number;
                const mr = (data.my_reaction ?? 0) as -1 | 0 | 1;
                return [v.id, { likes, dislikes, my: mr }] as const;
              }
              return [v.id, undefined] as const;
            } catch {
              return [v.id, undefined] as const;
            }
          })
        );
        const mergedR: Record<string, { likes: number; dislikes: number }> = {};
        const mergedMR: Record<string, -1 | 0 | 1> = {};
        for (const [id, obj] of results) {
          if (obj && typeof obj.likes === 'number' && typeof obj.dislikes === 'number') {
            mergedR[id] = { likes: obj.likes, dislikes: obj.dislikes };
            const maybeMy = (obj as Record<string, unknown>).my;
            if (maybeMy === -1 || maybeMy === 0 || maybeMy === 1) {
              mergedMR[id] = maybeMy;
            }
          }
        }
        if (Object.keys(mergedR).length) setReactions((prev) => ({ ...prev, ...mergedR }));
        if (Object.keys(mergedMR).length) setMyReactions((prev) => ({ ...prev, ...mergedMR }));
      } catch {}
    })();
    return () => abort.abort();
  }, [videos]);

  // Fetch saved status for current user (best-effort; requires auth cookies)
  useEffect(() => {
    if (!videos.length) return;
    const ids = videos.map((v) => v.id).join(',');
    const abort = new AbortController();
    (async () => {
      try {
        const r = await fetch(`/api/videos/saved/status?ids=${encodeURIComponent(ids)}`, { cache: 'no-store', signal: abort.signal });
        if (!r.ok) return;
        const data = await r.json().catch(() => ({}));
        const arr = Array.isArray(data?.saved) ? (data.saved as unknown[]) : [];
        const map: Record<string, boolean> = {};
        for (const x of arr) { const id = String(x); map[id] = true; }
        if (Object.keys(map).length) setSaved((prev) => ({ ...prev, ...map }));
      } catch {}
    })();
    return () => abort.abort();
  }, [videos]);

  const canLike = (v: Video) => {
    if (!user) return true; // allow anonymous/session based like; backend should enforce auth rules if needed
    if (v.userId && String(v.userId) === String(user.user_id)) return false; // cannot like own video
    return true;
  };

  const handleLikeToggle = async (v: Video) => {
    if (!canLike(v)) return;
    const current = myReactions[v.id] ?? 0; // -1 | 0 | 1
    const likedNow = current === 1;
    const existing = reactions[v.id] || { likes: 0, dislikes: 0 };
    // optimistic
    const nextLikes = likedNow ? Math.max(0, existing.likes - 1) : existing.likes + 1;
    setReactions((prev) => ({ ...prev, [v.id]: { ...existing, likes: nextLikes } }));
    setMyReactions((prev) => ({ ...prev, [v.id]: likedNow ? 0 : 1 }));

    try {
      if (likedNow) {
        const resp = await fetch(`/api/videos/${encodeURIComponent(v.id)}/reaction`, { method: 'DELETE' });
        if (!resp.ok) throw new Error('Failed to remove reaction');
        const data = await resp.json().catch(() => ({}));
        if (typeof data?.likes === 'number') {
          setReactions((prev) => ({ ...prev, [v.id]: { ...existing, likes: data.likes } }));
          setMyReactions((prev) => ({ ...prev, [v.id]: 0 }));
        }
      } else {
        const resp = await fetch(`/api/videos/${encodeURIComponent(v.id)}/reaction`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reaction: 1 }),
        });
        if (!resp.ok) throw new Error('Failed to set reaction');
        const data = await resp.json().catch(() => ({}));
        if (typeof data?.likes === 'number' && typeof data?.my_reaction === 'number') {
          setReactions((prev) => ({ ...prev, [v.id]: { ...existing, likes: data.likes } }));
          setMyReactions((prev) => ({ ...prev, [v.id]: (data.my_reaction as -1 | 0 | 1) }));
        }
      }
    } catch (e) {
      // revert: refetch from server for this post
      try {
        const r = await fetch(`/api/videos/${encodeURIComponent(v.id)}/reaction`, { cache: 'no-store' });
        if (r.ok) {
          const data = await r.json();
          if (typeof data?.likes === 'number') {
            setReactions((prev) => ({ ...prev, [v.id]: { ...existing, likes: data.likes } }));
            setMyReactions((prev) => ({ ...prev, [v.id]: (data.my_reaction ?? 0) as -1 | 0 | 1 }));
          }
        }
      } catch {}
    }
  };

  // Video modal behavior handled by shared VideoModal component

  // Show only videos created by other users when logged in
  const visibleVideos = user ? videos.filter((v) => v.userId !== user.user_id) : videos;

  // Autoplay handled by VideoModal

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
              href="/mlites"
              className="btn-primary text-sm"
            >
              Learn New
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
                    {/* Share button (top-right) */}
                    <div className="absolute top-2 right-2 z-10" onClick={(e) => e.stopPropagation()}>
                      <button
                        type="button"
                        aria-label="Share"
                        onClick={() => setShareOpenId((prev) => (prev === video.id ? null : video.id))}
                        className="p-2 rounded-full bg-black/50 text-white hover:bg-black/60"
                      >
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5">
                          <path d="M7 7a3 3 0 106 0 3 3 0 00-6 0zM4 17a3 3 0 106 0 3 3 0 00-6 0zM14 17a3 3 0 106 0 3 3 0 00-6 0z" />
                          <path d="M8.59 15.51l6.82-3.41-.9-1.8-6.82 3.4.9 1.81zm-.9-6.62l.9 1.8 6.82-3.4-.9-1.81-6.82 3.41zm7.72 8.43l-6.82-3.4-.9 1.8 6.82 3.41.9-1.81z" />
                        </svg>
                      </button>
                      {shareOpenId === video.id && (
                        <div
                          role="menu"
                          className="mt-2 w-40 rounded-md bg-white text-black shadow-lg border border-gray-200 absolute right-0"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <button
                            className="w-full text-left px-4 py-2 text-sm hover:bg-gray-100"
                            onClick={() => {
                              const link = canonicalLinkFor(video.videoUrl);
                              if (link) { try { navigator.clipboard.writeText(link); } catch {} }
                              setShareOpenId(null);
                            }}
                          >
                            Copy Link
                          </button>
                        </div>
                      )}
                    </div>
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
                        {capitalizeFirst(video.title || 'Untitled Video')}
                      </h3>
                      <div className="flex items-center gap-2">
                        <button
                          className={`flex items-center gap-1 px-2 py-1 rounded text-sm ${
                            (myReactions[video.id] ?? 0) === 1
                              ? 'text-red-600 hover:bg-red-50'
                              : canLike(video)
                                ? 'text-gray-600 hover:bg-gray-100'
                                : 'text-gray-400 cursor-not-allowed'
                          }`}
                          title={canLike(video) ? (((myReactions[video.id] ?? 0) === 1) ? 'Liked' : 'Like') : "You can't like your own video"}
                          onClick={(e) => { e.stopPropagation(); handleLikeToggle(video); }}
                          disabled={!canLike(video)}
                          aria-label={((myReactions[video.id] ?? 0) === 1) ? 'Liked' : 'Like'}
                          aria-pressed={(myReactions[video.id] ?? 0) === 1}
                        >
                          {/* Heart icon: filled if liked, outline otherwise */}
                          {(myReactions[video.id] ?? 0) === 1 ? (
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
                              <path d="M11.645 20.91l-.007-.003-.022-.012a15.247 15.247 0 01-.383-.218 25.18 25.18 0 01-4.244-3.17C4.688 15.36 2.25 12.462 2.25 9.003 2.25 6.387 4.357 4.5 6.75 4.5c1.503 0 2.86.654 3.75 1.68A5.123 5.123 0 0114.25 4.5c2.393 0 4.5 1.887 4.5 4.503 0 3.46-2.438 6.358-4.739 8.504a25.175 25.175 0 01-4.244 3.17 15.247 15.247 0 01-.383.218l-.022.012-.007.003a.75.75 0 01-.645 0z" />
                            </svg>
                          ) : (
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-4 w-4">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 8.25c0-2.485-2.015-4.5-4.5-4.5-1.86 0-3.456 1.116-4.125 2.709-.669-1.593-2.265-2.709-4.125-2.709C5.015 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12z" />
                            </svg>
                          )}
                          <span>{reactions[video.id]?.likes ?? 0}</span>
                        </button>
                        <button
                          className={`flex items-center gap-1 px-2 py-1 rounded text-sm ${
                            saved[video.id] ? 'text-blue-600 hover:bg-blue-50' : 'text-gray-600 hover:bg-gray-100'
                          }`}
                          title={saved[video.id] ? 'Saved' : 'Save'}
                          onClick={async (e) => {
                            e.stopPropagation();
                            const currently = !!saved[video.id];
                            // optimistic
                            setSaved((prev) => ({ ...prev, [video.id]: !currently }));
                            try {
                              const resp = await fetch(`/api/videos/${encodeURIComponent(video.id)}/save`, { method: currently ? 'DELETE' : 'PUT' });
                              if (!resp.ok) throw new Error('failed');
                              const data = await resp.json().catch(() => ({}));
                              if (typeof data?.saved === 'boolean') {
                                setSaved((prev) => ({ ...prev, [video.id]: data.saved as boolean }));
                              }
                            } catch {
                              // revert
                              setSaved((prev) => ({ ...prev, [video.id]: currently }));
                            }
                          }}
                          aria-label={saved[video.id] ? 'Saved' : 'Save'}
                          aria-pressed={!!saved[video.id]}
                        >
                          {/* Bookmark icon: filled if saved, outline otherwise */}
                          {saved[video.id] ? (
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
                              <path d="M6.75 3A2.25 2.25 0 004.5 5.25v15.19a.75.75 0 001.138.65l5.362-3.217a2.25 2.25 0 012.25 0l5.362 3.216a.75.75 0 001.138-.648V5.25A2.25 2.25 0 0017.25 3h-10.5z" />
                            </svg>
                          ) : (
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-4 w-4">
                              <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3h10.5A2.25 2.25 0 0119.5 5.25v15.19a.75.75 0 01-1.138.65l-5.362-3.217a2.25 2.25 0 00-2.25 0l-5.362 3.217a.75.75 0 01-1.138-.65V5.25A2.25 2.25 0 016.75 3z" />
                            </svg>
                          )}
                        </button>
                      </div>
                    </div>
                    {(() => {
                      const creatorName = extractCreatorName(video);
                      if (!creatorName) return null;
                      const href = video.userId ? `/users/${encodeURIComponent(String(video.userId))}` : undefined;
                      const content = (
                        <div className="mt-1 flex items-center gap-2 min-w-0" onClick={(e) => e.stopPropagation()}>
                          {video.profilePicUrl ? (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img
                              src={video.profilePicUrl}
                              alt={creatorName}
                              className="h-5 w-5 rounded-full object-cover flex-shrink-0 border border-gray-200"
                              loading="lazy"
                            />
                          ) : (
                            <div className="h-5 w-5 rounded-full bg-gray-200 flex-shrink-0" />
                          )}
                          <span className="text-sm text-gray-700 font-medium truncate">{creatorName}</span>
                        </div>
                      );
                      return href ? (
                        <Link href={href} prefetch={false}>{content}</Link>
                      ) : content;
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
      <VideoModal
        isOpen={!!selectedVideo}
        onClose={() => setSelectedVideo(null)}
        title={selectedVideo ? capitalizeFirst(selectedVideo.title) : undefined}
        videoUrl={selectedVideo?.videoUrl || ''}
        creatorName={selectedVideo ? extractCreatorName(selectedVideo) : null}
        createdAt={selectedVideo?.createdAt}
        showMeta={true}
        maxWidthClass="max-w-4xl"
        postId={selectedVideo?.id}
      />
    </div>
  );
}
