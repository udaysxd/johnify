'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Image from 'next/image';
import Link from 'next/link';
import VideoModal from '@/components/VideoModal';
import { useAuth } from '@/contexts/AuthContext';

type BackendVideo = {
  id?: string | number;
  title?: string;
  video_url?: string;
  thumbnail_url?: string;
  created_at?: string;
  status?: 'processing' | 'completed' | 'failed' | string;
  user_id?: string | number;
  user_name?: string | null;
};

type FrontendVideo = {
  id: string;
  title: string;
  videoUrl: string; // Can be empty for processing videos
  thumbnailUrl: string; // Can be empty for processing videos
  createdAt: string;
  status: 'processing' | 'completed' | 'failed';
};

function toFrontend(v: BackendVideo): FrontendVideo | null {
  const id = v.id !== undefined ? String(v.id) : '';
  const videoUrl = typeof v.video_url === 'string' ? v.video_url : '';
  const thumbnailUrl = typeof v.thumbnail_url === 'string' ? v.thumbnail_url : '';
  if (!id) return null; // Only filter out if no ID, allow empty videoUrl (processing status)
  const status: FrontendVideo['status'] = v.status === 'processing' || v.status === 'failed' ? v.status : 'completed';
  return {
    id,
    title: v.title || 'Untitled Video',
    videoUrl,
    thumbnailUrl,
    createdAt: v.created_at || new Date().toISOString(),
    status,
  };
}

function timeAgo(isoDate: string): string {
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
}

export default function UserProfilePage() {
  const params = useParams<{ user_id: string }>();
  const userId = params.user_id;
  const { user } = useAuth();
  const [profile, setProfile] = useState<{ user_id: string; user_name?: string | null; profile_pic_url?: string | null; bio?: string | null; link?: string | null; user_uid?: string | null } | null>(null);
  const [videos, setVideos] = useState<FrontendVideo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<FrontendVideo | null>(null);
  const [isFollowing, setIsFollowing] = useState<boolean>(false);
  const [followersCount, setFollowersCount] = useState<number>(0);
  const [followingCount, setFollowingCount] = useState<number>(0);
  const [followBusy, setFollowBusy] = useState<boolean>(false);

  useEffect(() => {
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const [uResp, vResp] = await Promise.all([
          fetch(`/api/users/${encodeURIComponent(userId)}`, { cache: 'no-store' }),
          fetch(`/api/videos/user/${encodeURIComponent(userId)}`, { cache: 'no-store' }),
        ]);
        if (!uResp.ok) {
          const j = await uResp.json().catch(() => ({}));
          throw new Error(j?.message || j?.detail || 'Failed to load user');
        }
        if (!vResp.ok) {
          const j = await vResp.json().catch(() => ({}));
          throw new Error(j?.message || j?.detail || 'Failed to load videos');
        }
        const user = await uResp.json();
        const vids = (await vResp.json()) as BackendVideo[];
        setProfile({
          user_id: String(user?.user_id ?? userId),
          user_name: user?.user_name ?? null,
          profile_pic_url: user?.profile_pic_url ?? null,
          bio: typeof user?.bio === 'string' ? user.bio : null,
          link: typeof user?.link === 'string' ? user.link : null,
          user_uid: typeof user?.user_uid === 'string' ? user.user_uid : null,
        });
        const list = Array.isArray(vids) ? vids.map(toFrontend).filter((x): x is FrontendVideo => !!x) : [];
        setVideos(list);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load profile');
      } finally {
        setLoading(false);
      }
    })();
  }, [userId]);

  // Load relationship and counts
  useEffect(() => {
    (async () => {
      try {
        const relResp = await fetch(`/api/users/${encodeURIComponent(userId)}/relationship`, { cache: 'no-store', credentials: 'include' });
        if (relResp.ok) {
          const rel = await relResp.json();
          setIsFollowing(!!rel?.is_following);
          setFollowersCount(Number(rel?.followers_count ?? 0));
          setFollowingCount(Number(rel?.following_count ?? 0));
        } else {
          // Fallback: try counts individually (public)
          const [fc, fg] = await Promise.all([
            fetch(`/api/users/${encodeURIComponent(userId)}/followers/count`, { cache: 'no-store' }),
            fetch(`/api/users/${encodeURIComponent(userId)}/following/count`, { cache: 'no-store' }),
          ]);
          if (fc.ok) {
            const d = await fc.json();
            setFollowersCount(Number(d?.followers_count || 0));
          }
          if (fg.ok) {
            const d = await fg.json();
            setFollowingCount(Number(d?.following_count || 0));
          }
        }
      } catch (_) {
        // ignore
      }
    })();
  }, [userId]);

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
          <div className="flex items-center gap-3 mb-6">
            <div className="h-14 w-14 rounded-full bg-gray-200 animate-pulse" />
            <div className="h-5 w-48 bg-gray-200 animate-pulse rounded" />
          </div>
          <div className="flex justify-center items-center h-64"><div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-blue-500"></div></div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gray-50">
        <div className="max-w-7xl mx-auto py-8 px-4">
          <div className="flex items-center gap-3 mb-6">
            <div className="h-14 w-14 rounded-full bg-gray-200" />
            <div className="h-5 w-48 bg-gray-200 rounded" />
          </div>
          <div className="bg-red-50 border border-red-200 text-red-700 rounded p-3">{error}</div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto py-8 px-4">
        {/* Header */}
        <div className="flex items-center gap-4 mb-6">
          {profile?.profile_pic_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={profile.profile_pic_url} alt={profile.user_name || `User ${profile.user_id}`} className="h-16 w-16 rounded-full object-cover border" />
          ) : (
            <div className="h-16 w-16 rounded-full bg-gray-200" />
          )}
          <div>
            <h1 className="text-2xl font-bold">
              {profile?.user_uid
                ? `${profile.user_uid}${profile?.user_name ? ` (${profile.user_name})` : ''}`
                : (profile?.user_name || 'User')}
            </h1>
            <div className="text-gray-600 text-sm flex items-center gap-4">
              <span>
                <span className="font-semibold">{followersCount}</span> followers
              </span>
              <span>
                <span className="font-semibold">{followingCount}</span> following
              </span>
            </div>
          </div>
          <div className="ml-auto flex items-center gap-3">
            {/* Follow/Unfollow button (hide if viewing own profile) */}
            {user?.user_id && String(user.user_id) !== String(userId) && (
              <button
                className={`px-4 py-2 rounded text-white ${isFollowing ? 'bg-gray-600 hover:bg-gray-700' : 'bg-blue-600 hover:bg-blue-700'} disabled:opacity-60`}
                disabled={followBusy}
                onClick={async () => {
                  try {
                    setFollowBusy(true);
                    if (!isFollowing) {
                      // Optimistic update
                      setIsFollowing(true);
                      setFollowersCount((c) => c + 1);
                      const resp = await fetch(`/api/users/${encodeURIComponent(userId)}/follow`, { method: 'POST', credentials: 'include' });
                      if (!resp.ok) {
                        // revert
                        setIsFollowing(false);
                        setFollowersCount((c) => Math.max(0, c - 1));
                      } else {
                        const data = await resp.json().catch(() => ({}));
                        if (typeof data?.followers_count === 'number') setFollowersCount(data.followers_count);
                      }
                    } else {
                      // Unfollow
                      setIsFollowing(false);
                      setFollowersCount((c) => Math.max(0, c - 1));
                      const resp = await fetch(`/api/users/${encodeURIComponent(userId)}/unfollow`, { method: 'POST', credentials: 'include' });
                      if (!resp.ok) {
                        // revert
                        setIsFollowing(true);
                        setFollowersCount((c) => c + 1);
                      } else {
                        const data = await resp.json().catch(() => ({}));
                        if (typeof data?.followers_count === 'number') setFollowersCount(data.followers_count);
                      }
                    }
                  } finally {
                    setFollowBusy(false);
                  }
                }}
              >
                {isFollowing ? (followBusy ? 'Unfollowing...' : 'Unfollow') : (followBusy ? 'Following...' : 'Follow')}
              </button>
            )}
            <Link href="/feed" className="btn-outline">Back to Feed</Link>
          </div>
        </div>

        {/* Public profile fields (read-only) */}
        <section className="rounded border border-gray-200 bg-white p-6 mb-8">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">About</h2>
          <div className="space-y-3 text-sm">
            {profile?.bio ? (
              <div>
                <span className="block text-gray-500 mb-1">Bio:</span>
                <p className="text-gray-900 whitespace-pre-wrap">{profile.bio}</p>
              </div>
            ) : null}
            {profile?.link ? (
              <div>
                <span className="text-gray-500 mr-2">Link:</span>
                <a className="text-blue-600 hover:underline break-all" href={profile.link} target="_blank" rel="noopener noreferrer">{profile.link}</a>
              </div>
            ) : null}
          </div>
        </section>

        {/* Videos */}
        {videos.length === 0 ? (
          <div className="text-center py-12">
            <svg className="mx-auto h-12 w-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2z" />
            </svg>
            <h3 className="mt-2 text-sm font-medium text-gray-900">No videos.</h3>
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
                    <div className="w-full h-full bg-gradient-to-br from-blue-600 to-purple-600 flex items-center justify-center text-white">
                      <svg className="w-10 h-10" fill="currentColor" viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg">
                        <path d="M6.3 2.841A1.5 1.5 0 004 4.11v11.78a1.5 1.5 0 002.3 1.269l9.344-5.89a1.5 1.5 0 000-2.538L6.3 2.84z" />
                      </svg>
                    </div>
                  )}
                  {video.status === 'processing' && (
                    <div className="absolute top-2 right-2 bg-yellow-500 text-white text-xs px-2 py-1 rounded">
                      Processing
                    </div>
                  )}
                  {video.status === 'failed' && (
                    <div className="absolute top-2 right-2 bg-red-500 text-white text-xs px-2 py-1 rounded">
                      Failed
                    </div>
                  )}
                </div>
                <div className="mx-4 border-t border-gray-300" />
                <div className="px-4 pb-3 pt-3">
                  <h3 className="text-base font-medium text-gray-900 truncate">{capitalizeFirst(video.title)}</h3>
                  <p className="text-sm text-gray-500">{timeAgo(video.createdAt)}</p>
                  {video.status === 'processing' && (
                    <p className="text-xs text-yellow-600 mt-1">Video is being processed...</p>
                  )}
                  {video.status === 'failed' && (
                    <p className="text-xs text-red-600 mt-1">Video processing failed</p>
                  )}
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
        creatorName={profile?.user_name || null}
        createdAt={selected?.createdAt}
        showMeta={true}
        maxWidthClass="max-w-4xl"
        postId={selected?.id}
      />
    </div>
  );
}
