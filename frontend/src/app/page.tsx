"use client";

import Link from 'next/link';
import Image from 'next/image';
import { useEffect, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import VideoReel, { type ReelVideo } from '@/components/VideoReel';

type Video = {
  id: string;
  title: string;
  thumbnailUrl: string;
  videoUrl: string;
  createdAt: string;
  status: 'processing' | 'completed' | 'failed';
  userId?: string;
  userName?: string;
  likesCount?: number;
};

function capitalizeFirst(s?: string): string {
  if (!s) return 'Untitled Video';
  const match = s.match(/[A-Za-z]/);
  if (!match) return s.trim() ? s : 'Untitled Video';
  const i = match.index as number;
  return s.slice(0, i) + s.charAt(i).toUpperCase() + s.slice(i + 1);
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

export default function Home() {
  const { user } = useAuth();
  const [videos, setVideos] = useState<Video[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchFeed = async () => {
      try {
        setLoading(true);
        setError(null);
        const resp = await fetch('/api/videos/feed', { cache: 'no-store' });
        if (!resp.ok) {
          const j = await resp.json().catch(() => ({}));
          throw new Error((j && (j.error || j.detail || j.message)) || 'Failed to load feed');
        }
        const list = (await resp.json()) as Video[];
        setVideos(Array.isArray(list) ? list : []);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load feed');
      } finally {
        setLoading(false);
      }
    };
    fetchFeed();
  }, []);

  const visibleVideos = user ? videos.filter((v) => String(v.userId) !== String(user.user_id)) : videos;

  return (
    <div className="min-h-screen bg-white">
      {/* Body layout */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-0 grid grid-cols-12 gap-6">
        {/* Left navigation */}
        <aside className="hidden md:block md:col-span-3">
          <div className="sticky top-2 space-y-4">
            <div className="px-3 mb-8">
              <Link href="/" className="block text-3xl font-extrabold tracking-tight">Johnify</Link>
              <div className="text-sm font-bold text-gray-600 mt-1">Social <span className="line-through">Media</span> Learning app</div>
            </div>
            <Link
              href="/"
              className="block px-3 py-2 rounded font-medium bg-[var(--color-primary)] text-white"
              aria-current="page"
            >
              For You
            </Link>
            <Link href="/mlites" className="block px-3 py-2 rounded hover:bg-gray-100 text-[var(--color-primary)]">My Lites</Link>
            {user ? (
              <Link href="/my-saved" className="block px-3 py-2 rounded hover:bg-gray-100 text-[var(--color-primary)]">My Saved</Link>
            ) : (
              <Link href="/auth/signin?callback=/my-saved" className="block px-3 py-2 rounded hover:bg-gray-100 text-[var(--color-primary)]">My Saved</Link>
            )}
            {user ? (
              <Link href="/my-profile" className="block px-3 py-2 rounded hover:bg-gray-100 text-[var(--color-primary)]">My Profile</Link>
            ) : (
              <Link href="/auth/signin?callback=/my-profile" className="block px-3 py-2 rounded hover:bg-gray-100 text-[var(--color-primary)]">My Profile</Link>
            )}
            {!user && (
              <Link href="/auth/signin" className="inline-flex mt-2 btn-outline">Login</Link>
            )}
          </div>
        </aside>

        {/* Feed */}
        <main className="col-span-12 md:col-span-9">
          <div className="md:hidden mb-6">
            <h1 className="text-3xl font-extrabold tracking-tight">Johnify</h1>
            <div className="text-sm font-bold text-gray-600 mt-1">Social <span className="line-through">Media</span> Learning app</div>
          </div>
          <h1 className="sr-only">Public Reel</h1>
          {loading ? (
            <div className="flex justify-center py-16">
              <div className="w-10 h-10 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : error ? (
            <div className="bg-red-50 border border-red-200 text-red-700 rounded p-3">{error}</div>
          ) : (
            <VideoReel videos={visibleVideos as unknown as ReelVideo[]} />
          )}
        </main>
      </div>
    </div>
  );
}
