'use client';

import { useEffect, useState } from 'react';
import Image from 'next/image';
import Link from 'next/link';
import VideoModal from '@/components/VideoModal';

interface VideoItem {
  id: string;
  title: string;
  video_url?: string; // backend shape
  thumbnail_url?: string;
  videoUrl?: string; // normalized
  thumbnailUrl?: string;
  created_at?: string;
  createdAt?: string;
  status?: 'processing' | 'completed' | 'failed' | string;
  user_id?: string | number;
  userId?: string;
  user_name?: string | null;
  userName?: string | null;
  likes?: number;
  dislikes?: number;
  my_reaction?: -1 | 0 | 1;
}

function toFrontend(v: VideoItem) {
  const videoUrl = (v.videoUrl || v.video_url) ?? '';
  const thumbnailUrl = (v.thumbnailUrl || v.thumbnail_url) ?? '';
  const createdAt = (v.createdAt || v.created_at) ?? new Date().toISOString();
  const userId = v.userId ?? (v.user_id !== undefined ? String(v.user_id) : undefined);
  const userName = v.userName ?? (typeof v.user_name === 'string' ? v.user_name : undefined) ?? undefined;
  const status: 'processing' | 'completed' | 'failed' =
    v.status === 'processing' || v.status === 'failed' ? v.status : 'completed';
  return {
    id: String(v.id),
    title: v.title || 'Untitled Video',
    videoUrl,
    thumbnailUrl,
    createdAt,
    status,
    userId,
    userName,
    likes: typeof v.likes === 'number' ? v.likes : 0,
    dislikes: typeof v.dislikes === 'number' ? v.dislikes : 0,
    myReaction: (v.my_reaction ?? 0) as -1 | 0 | 1,
  } as const;
}

export default function MySavedPage() {
  const [videos, setVideos] = useState<ReturnType<typeof toFrontend>[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<ReturnType<typeof toFrontend> | null>(null);

  useEffect(() => {
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const resp = await fetch('/api/videos/saved', { cache: 'no-store' });
        if (!resp.ok) {
          const body = await resp.json().catch(() => ({}));
          const msg = (body && (body.message || body.detail)) || 'Failed to load saved videos';
          throw new Error(msg);
        }
        const data = (await resp.json()) as VideoItem[];
        const list = Array.isArray(data) ? data.map(toFrontend).filter((x) => !!x.videoUrl) : [];
        setVideos(list);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Error loading saved videos');
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const handleUnsave = async (id: string) => {
    // optimistic remove
    const prev = videos;
    setVideos((v) => v.filter((x) => x.id !== id));
    try {
      const r = await fetch(`/api/videos/${encodeURIComponent(id)}/save`, { method: 'DELETE' });
      if (!r.ok) throw new Error('Failed to unsave');
    } catch {
      // revert
      setVideos(prev);
    }
  };

  const handleLikeToggle = async (v: ReturnType<typeof toFrontend>) => {
    const current = v.myReaction ?? 0;
    const likedNow = current === 1;
    // optimistic
    setVideos((list) =>
      list.map((it) =>
        it.id === v.id
          ? {
              ...it,
              likes: Math.max(0, (it.likes || 0) + (likedNow ? -1 : 1)),
              myReaction: likedNow ? 0 : 1,
            }
          : it
      )
    );
    try {
      if (likedNow) {
        const resp = await fetch(`/api/videos/${encodeURIComponent(v.id)}/reaction`, { method: 'DELETE' });
        if (!resp.ok) throw new Error('Failed');
        const data = await resp.json().catch(() => ({}));
        if (typeof data?.likes === 'number') {
          setVideos((list) => list.map((it) => (it.id === v.id ? { ...it, likes: data.likes, myReaction: 0 } : it)));
        }
      } else {
        const resp = await fetch(`/api/videos/${encodeURIComponent(v.id)}/reaction`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reaction: 1 }),
        });
        if (!resp.ok) throw new Error('Failed');
        const data = await resp.json().catch(() => ({}));
        if (typeof data?.likes === 'number' && typeof data?.my_reaction === 'number') {
          setVideos((list) => list.map((it) => (it.id === v.id ? { ...it, likes: data.likes, myReaction: data.my_reaction as 0 | 1 | -1 } : it)));
        }
      }
    } catch {
      // revert by refetching this item's reaction from server best-effort
      try {
        const r = await fetch(`/api/videos/${encodeURIComponent(v.id)}/reaction`, { cache: 'no-store' });
        if (r.ok) {
          const data = await r.json();
          setVideos((list) =>
            list.map((it) =>
              it.id === v.id
                ? { ...it, likes: typeof data?.likes === 'number' ? data.likes : it.likes, myReaction: (data?.my_reaction ?? 0) as -1 | 0 | 1 }
                : it
            )
          );
        }
      } catch {}
    }
  };

  const capitalizeFirst = (s?: string) => {
    if (!s) return 'Untitled Video';
    const m = s.match(/[A-Za-z]/);
    if (!m) return s.trim() || 'Untitled Video';
    const i = m.index as number;
    return s.slice(0, i) + s.charAt(i).toUpperCase() + s.slice(i + 1);
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50">
        <div className="max-w-7xl mx-auto py-8 px-4">
          <h1 className="text-3xl font-bold mb-6">My Saved</h1>
          <div className="flex justify-center items-center h-64"><div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-blue-500"></div></div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gray-50">
        <div className="max-w-7xl mx-auto py-8 px-4">
          <h1 className="text-3xl font-bold mb-6">My Saved</h1>
          <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded">{error}</div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto py-8 px-4">
        <div className="flex justify-between items-center mb-8">
          <h1 className="text-3xl font-bold">My Saved</h1>
          <Link href="/feed" className="btn-primary text-sm">Back to Feed</Link>
        </div>
        {videos.length === 0 ? (
          <div className="text-center py-12">
            <svg className="mx-auto h-12 w-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2z" />
            </svg>
            <h3 className="mt-2 text-sm font-medium text-gray-900">No saved videos.</h3>
            <p className="mt-1 text-sm text-gray-500">Save videos from the Feed to see them here.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {videos.map((video) => (
              <div key={video.id} className="bg-white overflow-hidden shadow rounded-lg hover:shadow-lg transition-shadow duration-200 cursor-pointer" onClick={() => setSelected(video)}>
                <div className="relative pb-[56.25%] bg-black">
                  {video.thumbnailUrl ? (
                    <div className="absolute inset-0">
                      <Image src={video.thumbnailUrl} alt={video.title} fill className="object-cover" sizes="(max-width: 768px) 100vw, (max-width: 1200px) 50vw, 33vw" unoptimized />
                    </div>
                  ) : (
                    <div className="w-full h-full bg-gradient-to-br from-blue-600 to-purple-600" />
                  )}
                  {video.status === 'processing' && (
                    <div className="absolute inset-0 bg-black bg-opacity-50 flex items-center justify-center">
                      <div className="text-white text-center">
                        <div className="w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto" />
                        <p className="mt-2 text-sm">Processing</p>
                      </div>
                    </div>
                  )}
                </div>
                <div className="mx-4 border-t border-gray-300" />
                <div className="px-4 pb-3 pt-3">
                  <div className="flex items-center justify-between gap-3">
                    <h3 className="text-base font-medium text-gray-900 truncate">{capitalizeFirst(video.title)}</h3>
                    <div className="flex items-center gap-2">
                      <button
                        className={`flex items-center gap-1 px-2 py-1 rounded text-sm ${video.myReaction === 1 ? 'text-red-600 hover:bg-red-50' : 'text-gray-600 hover:bg-gray-100'}`}
                        title={video.myReaction === 1 ? 'Liked' : 'Like'}
                        onClick={(e) => { e.stopPropagation(); handleLikeToggle(video); }}
                        aria-label={video.myReaction === 1 ? 'Liked' : 'Like'}
                        aria-pressed={video.myReaction === 1}
                      >
                        {video.myReaction === 1 ? (
                          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
                            <path d="M11.645 20.91l-.007-.003-.022-.012a15.247 15.247 0 01-.383-.218 25.18 25.18 0 01-4.244-3.17C4.688 15.36 2.25 12.462 2.25 9.003 2.25 6.387 4.357 4.5 6.75 4.5c1.503 0 2.86.654 3.75 1.68A5.123 5.123 0 0114.25 4.5c2.393 0 4.5 1.887 4.5 4.503 0 3.46-2.438 6.358-4.739 8.504a25.175 25.175 0 01-4.244 3.17 15.247 15.247 0 01-.383.218l-.022.012-.007.003a.75.75 0 01-.645 0z" />
                          </svg>
                        ) : (
                          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-4 w-4">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 8.25c0-2.485-2.015-4.5-4.5-4.5-1.86 0-3.456 1.116-4.125 2.709-.669-1.593-2.265-2.709-4.125-2.709C5.015 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12z" />
                          </svg>
                        )}
                        <span>{video.likes ?? 0}</span>
                      </button>
                      <button
                        className="flex items-center gap-1 px-2 py-1 rounded text-sm text-gray-600 hover:bg-gray-100"
                        title="Unsave"
                        onClick={(e) => { e.stopPropagation(); handleUnsave(video.id); }}
                        aria-label="Unsave"
                      >
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
                          <path d="M6.75 3A2.25 2.25 0 004.5 5.25v15.19a.75.75 0 001.138.65l5.362-3.217a2.25 2.25 0 012.25 0l5.362 3.216a.75.75 0 001.138-.648V5.25A2.25 2.25 0 0017.25 3h-10.5z" />
                        </svg>
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <VideoModal
        isOpen={!!selected}
        onClose={() => setSelected(null)}
        title={selected?.title}
        videoUrl={selected?.videoUrl || ''}
        creatorName={selected?.userName || null}
        createdAt={selected?.createdAt}
        showMeta={true}
        maxWidthClass="max-w-4xl"
        postId={selected?.id}
      />
    </div>
  );
}
