"use client";

import { useEffect, useMemo, useRef, useState } from 'react';
import Image from 'next/image';
import Link from 'next/link';
import { useAuth } from '@/contexts/AuthContext';

export type ReelVideo = {
  id: string;
  title: string;
  thumbnailUrl: string;
  videoUrl: string;
  createdAt: string;
  status: 'processing' | 'completed' | 'failed';
  userId?: string;
  userName?: string;
};

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

/**
 * A vertical, full-height, snap-scrolling reel of videos.
 * - Each item is 100vh tall
 * - Uses IntersectionObserver to autoplay/pause
 */
export default function VideoReel({ videos }: { videos: ReelVideo[] }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const videoRefs = useRef<Record<string, HTMLVideoElement | null>>({});
  const [index, setIndex] = useState(0);
  const lastNavAtRef = useRef<number>(0);
  const [muted, setMuted] = useState<boolean>(true);
  const [menuOpen, setMenuOpen] = useState<boolean>(false);
  const [shareOpenId, setShareOpenId] = useState<string | null>(null);
  const { user, handleSignOut } = useAuth();
  const [profileOpen, setProfileOpen] = useState<boolean>(false);
  const profileMenuRef = useRef<HTMLDivElement | null>(null);
  const profileButtonRef = useRef<HTMLButtonElement | null>(null);

  // Close profile menu on outside click or Escape
  useEffect(() => {
    const onDocClick = (e: MouseEvent) => {
      const t = e.target as Node;
      if (
        profileOpen &&
        profileMenuRef.current &&
        !profileMenuRef.current.contains(t) &&
        profileButtonRef.current &&
        !profileButtonRef.current.contains(t)
      ) {
        setProfileOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setProfileOpen(false);
    };
    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDocClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [profileOpen]);

  // Clamp index if videos length changes
  useEffect(() => {
    if (index >= videos.length) setIndex(Math.max(0, videos.length - 1));
  }, [videos.length, index]);

  // Autoplay current, pause others on index change
  useEffect(() => {
    const current = videos[index];
    const currentId = current?.id;
    // pause all
    Object.values(videoRefs.current).forEach((el) => {
      try { el?.pause(); } catch {}
    });
    // play current
    if (currentId) {
      const el = videoRefs.current[currentId];
      if (el) {
        // set mute state per user preference
        try {
          el.muted = muted;
          if (!muted) el.volume = 1.0;
        } catch {}
        // attempt multiple times to accommodate browser autoplay policies
        const tryPlay = async () => {
          try {
            await el.play();
          } catch {
            // If autoplay with sound is blocked, fallback to muted autoplay
            try {
              el.muted = true;
              await el.play();
              // Do not flip global muted state here; wait for explicit user interaction
            } catch {}
          }
        };
        tryPlay();
        // safety re-try shortly after mount
        setTimeout(tryPlay, 50);
        setTimeout(tryPlay, 250);
      }
    }
  }, [index, videos]);

  const goPrev = () => setIndex((i) => Math.max(0, i - 1));
  const goNext = () => setIndex((i) => Math.min(videos.length - 1, i + 1));

  // Initial autoplay on mount
  useEffect(() => {
    // play the first video after first paint
    requestAnimationFrame(() => {
      const first = videos[0]?.id;
      if (first) {
        const el = videoRefs.current[first];
        try {
          if (el) {
            el.muted = muted;
            if (!muted) el.volume = 1.0;
            el.play().catch(async () => {
              // Fallback to muted autoplay if blocked
              try {
                el.muted = true;
                await el.play();
                // Do not flip global muted state here; wait for explicit user interaction
              } catch {}
            });
          }
        } catch {}
      }
    });
  }, [videos]);

  // Wheel/Touch/Keyboard navigation
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const canNavigate = () => {
      const now = Date.now();
      if (now - lastNavAtRef.current < 400) return false; // throttle 400ms
      lastNavAtRef.current = now;
      return true;
    };

    const onWheel = (e: WheelEvent) => {
      // prevent native scroll and navigate one item
      e.preventDefault();
      if (!canNavigate()) return;
      if (e.deltaY > 0) goNext();
      else if (e.deltaY < 0) goPrev();
    };

    let touchStartY = 0;
    let touching = false;
    const onTouchStart = (e: TouchEvent) => {
      if (e.touches && e.touches.length > 0) {
        touchStartY = e.touches[0].clientY;
        touching = true;
      }
    };
    const onTouchEnd = (e: TouchEvent) => {
      if (!touching) return;
      touching = false;
      const endY = (e.changedTouches && e.changedTouches[0]?.clientY) || touchStartY;
      const delta = endY - touchStartY;
      if (Math.abs(delta) < 40) return; // threshold
      if (!canNavigate()) return;
      if (delta < 0) goNext(); // swiped up -> next
      else goPrev(); // swiped down -> prev
    };

    const onKey = (e: KeyboardEvent) => {
      if (['ArrowDown', 'PageDown', ' '].includes(e.key)) {
        e.preventDefault();
        if (!canNavigate()) return;
        goNext();
      } else if (['ArrowUp', 'PageUp'].includes(e.key)) {
        e.preventDefault();
        if (!canNavigate()) return;
        goPrev();
      }
    };

    el.addEventListener('wheel', onWheel, { passive: false });
    el.addEventListener('touchstart', onTouchStart, { passive: true });
    el.addEventListener('touchend', onTouchEnd, { passive: true });
    window.addEventListener('keydown', onKey);

    return () => {
      el.removeEventListener('wheel', onWheel);
      el.removeEventListener('touchstart', onTouchStart);
      el.removeEventListener('touchend', onTouchEnd);
      window.removeEventListener('keydown', onKey);
    };
  }, [goNext, goPrev]);

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

  return (
    <div ref={containerRef} className="h-[100dvh] md:h-screen overflow-hidden relative touch-none">
      {/* Top bar overlay: actions only (right-aligned) */}
      <div className="absolute top-0 left-0 right-0 z-10 flex items-center justify-end px-2 sm:px-4 py-0 pointer-events-none">
        {/* Actions: hamburger on mobile, buttons on desktop */}
        <div className="pointer-events-auto flex items-center gap-2">
          {/* Mobile hamburger (right-aligned) */}
          <button
            type="button"
            aria-label="Open menu"
            onClick={() => setMenuOpen((v) => !v)}
            className="sm:hidden p-1 rounded-md bg-white/80 text-black shadow hover:bg-white"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5">
              <path d="M3 6.75A.75.75 0 013.75 6h16.5a.75.75 0 010 1.5H3.75A.75.75 0 013 6.75zm0 5.25a.75.75 0 01.75-.75h16.5a.75.75 0 010 1.5H3.75a.75.75 0 01-.75-.75zm.75 4.5a.75.75 0 000 1.5h16.5a.75.75 0 000-1.5H3.75z" />
            </svg>
          </button>
          {/* Desktop buttons */}
          <div className="hidden sm:flex items-center gap-3 ml-auto relative">
            <a href="https://play.google.com/store/apps/details?id=com.johnify&pcampaignid=web_share" target="_blank" rel="noopener noreferrer" className="btn-outline whitespace-nowrap">Get Android App</a>
            {user ? (
              <div className="relative">
                <button
                  ref={profileButtonRef}
                  type="button"
                  onClick={() => setProfileOpen(v => !v)}
                  className="h-8 w-8 rounded-full bg-black text-white flex items-center justify-center text-sm font-semibold focus:outline-none focus:ring-2 focus:ring-black/40"
                  aria-haspopup="menu"
                  aria-expanded={profileOpen}
                  title={(user.user_name || user.user_email || 'User') as string}
                  aria-label="Open profile menu"
                >
                  {((user.user_name || user.user_email || 'U').trim().charAt(0) || 'U').toUpperCase()}
                </button>
                {profileOpen && (
                  <div
                    ref={profileMenuRef}
                    className="absolute right-0 mt-2 w-44 bg-white border border-gray-200 rounded-md shadow-lg py-1 z-50"
                    role="menu"
                  >
                    <div className="px-4 py-2 text-xs text-gray-500 border-b border-gray-100 select-text break-words">
                      {user?.user_email || '—'}
                    </div>
                    <Link
                      href="/my-profile"
                      className="block w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
                      role="menuitem"
                      onClick={() => setProfileOpen(false)}
                    >
                      My Profile
                    </Link>
                    
                    <button
                      onClick={async () => {
                        setProfileOpen(false);
                        try { await handleSignOut(); } catch (e) { console.error(e); }
                      }}
                      className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
                      role="menuitem"
                    >
                      Sign Out
                    </button>
                  </div>
                )}
              </div>
            ) : (
              <>
                <Link href="/auth/signin" className="btn-outline whitespace-nowrap">Sign in</Link>
                <Link href="/auth/register" className="btn-primary whitespace-nowrap">Sign up</Link>
              </>
            )}
          </div>
        </div>
      </div>
      {/* Mobile dropdown menu */}
      {menuOpen && (
        <div className="absolute top-0 right-1 z-20 sm:hidden pointer-events-auto">
          <div className="bg-white rounded-md shadow-lg p-2 min-w-[11rem]">
            <a href="https://play.google.com/store/apps/details?id=com.johnify&pcampaignid=web_share" target="_blank" rel="noopener noreferrer" className="block w-full text-left px-3 py-2 rounded hover:bg-gray-100">Get Android App</a>
            {user ? (
              <>
                <Link href="/my-profile" className="block w-full text-left px-3 py-2 rounded hover:bg-gray-100">My Profile</Link>
                
                <button
                  onClick={async () => {
                    setMenuOpen(false);
                    try { await handleSignOut(); } catch (e) { console.error(e); }
                  }}
                  className="block w-full text-left px-3 py-2 rounded hover:bg-gray-100 text-red-600"
                >
                  Sign Out
                </button>
              </>
            ) : (
              <>
                <Link href="/auth/signin" className="block w-full text-left px-3 py-2 rounded hover:bg-gray-100">Sign in</Link>
                <Link href="/auth/register" className="block w-full text-left px-3 py-2 rounded bg-black text-white hover:bg-gray-900 mt-1">Sign up</Link>
              </>
            )}
          </div>
        </div>
      )}

      {/* Sliding container */}
      <div
        className="h-full w-full overflow-hidden"
      >
        <div
          className="h-full w-full flex flex-col transition-transform duration-300 ease-out"
          style={{ transform: `translateY(-${index * 100}%)` }}
        >
          {videos.map((v, i) => (
            <section key={v.id} data-vid={v.id} className="h-full min-h-full w-full flex-none relative bg-transparent overflow-hidden">
              {/* Centered reel container with mobile padding for separation */}
              <div className="h-full w-full box-border flex items-start sm:items-center justify-center sm:justify-start px-0 sm:px-0 sm:ml-6 lg:ml-12 pt-0 sm:pt-0 pb-0">
                {/* 9:16 player container */}
                <div
                  className="relative aspect-[9/16]"
                  style={{ width: 'min(100vw, calc(100dvh * 9 / 16))', height: 'auto', maxHeight: '100%' }}
                >
                  {/* Video / Thumbnail layer, contained within 9:16 box */}
                  <div className="absolute inset-0">
                    {v.videoUrl ? (
                      Math.abs(i - index) <= 2 ? (
                        // Load active and next video only
                        <video
                          ref={(node) => { videoRefs.current[v.id] = node; }}
                          className="w-full h-full object-cover rounded-md"
                          src={v.videoUrl}
                          controls={false}
                          playsInline
                          muted={muted}
                          loop
                          preload={i === index ? 'auto' : 'metadata'}
                          poster={v.thumbnailUrl || undefined}
                          onClick={(e) => {
                            const el = e.currentTarget as HTMLVideoElement;
                            if (el.paused) el.play().catch(() => {});
                            else el.pause();
                          }}
                        />
                      ) : (
                        // For off-screen items, render only the thumbnail to avoid fetching video metadata
                        v.thumbnailUrl ? (
                          <Image src={v.thumbnailUrl} alt={v.title} fill className="object-cover rounded-md" unoptimized />
                        ) : (
                          <div className="w-full h-full flex items-center justify-center text-white">No media</div>
                        )
                      )
                    ) : v.thumbnailUrl ? (
                      <Image src={v.thumbnailUrl} alt={v.title} fill className="object-cover rounded-md" unoptimized />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center text-white">No media</div>
                    )}
                    {/* Mute/Unmute button top-left */}
                    <button
                      type="button"
                      aria-label={muted ? 'Unmute' : 'Mute'}
                      onClick={() => {
                        const nextMuted = !muted;
                        setMuted(nextMuted);
                        const vid = videoRefs.current[videos[index]?.id || v.id];
                        if (vid) {
                          try {
                            vid.muted = nextMuted;
                            if (!nextMuted) {
                              // Force remove attribute for some browsers
                              try { vid.removeAttribute('muted'); } catch {}
                              vid.volume = 1.0;
                              // Ensure play with sound after gesture
                              const doPlay = async () => {
                                try {
                                  if (!vid.paused) {
                                    try { vid.pause(); } catch {}
                                  }
                                  await vid.play();
                                } catch {}
                              };
                              if (vid.readyState < 2) {
                                const onCanPlay = () => {
                                  vid.removeEventListener('canplay', onCanPlay);
                                  doPlay();
                                };
                                vid.addEventListener('canplay', onCanPlay, { once: true });
                                // Kick a load if needed
                                try { vid.load(); } catch {}
                              } else {
                                doPlay();
                              }
                            } else {
                              // Muting: keep playing silently
                              if (vid.paused) {
                                vid.play().catch(() => {});
                              }
                            }
                          } catch {}
                        }
                      }}
                      className="absolute top-2 left-2 z-50 p-2 rounded-full bg-black/50 text-white hover:bg-black/60"
                    >
                      {muted ? (
                        <span className="relative inline-block">
                          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5">
                            <path d="M3 9v6h4l5 5V4L7 9H3z" />
                            <path d="M16.5 12c0-1.77-1.02-3.29-2.5-4.03v8.06A4.49 4.49 0 0016.5 12z" />
                            <path d="M19 12a7 7 0 00-3.5-6.06v12.12A7 7 0 0019 12z" />
                          </svg>
                          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" className="w-5 h-5 absolute inset-0">
                            <line x1="5" y1="5" x2="19" y2="19" stroke="#ef4444" strokeWidth="2.5" strokeLinecap="round" />
                            <line x1="19" y1="5" x2="5" y2="19" stroke="#ef4444" strokeWidth="2.5" strokeLinecap="round" />
                          </svg>
                        </span>
                      ) : (
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5">
                          <path d="M3 9v6h4l5 5V4L7 9H3z" />
                          <path d="M16.5 12c0-1.77-1.02-3.29-2.5-4.03v8.06A4.49 4.49 0 0016.5 12z" />
                        </svg>
                      )}
                    </button>

                    {/* Share button top-right */}
                    <div className="absolute top-2 right-2 z-50" onClick={(e) => e.stopPropagation()}>
                      <button
                        type="button"
                        aria-label="Share"
                        onClick={() => setShareOpenId((prev) => (prev === v.id ? null : v.id))}
                        className="p-2 rounded-full bg-black/50 text-white hover:bg-black/60"
                      >
                        {/* share icon */}
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5">
                          <path d="M7 7a3 3 0 106 0 3 3 0 00-6 0zM4 17a3 3 0 106 0 3 3 0 00-6 0zM14 17a3 3 0 106 0 3 3 0 00-6 0z" />
                          <path d="M8.59 15.51l6.82-3.41-.9-1.8-6.82 3.4.9 1.81zm-.9-6.62l.9 1.8 6.82-3.4-.9-1.81-6.82 3.41zm7.72 8.43l-6.82-3.4-.9 1.8 6.82 3.41.9-1.81z" />
                        </svg>
                      </button>
                      {shareOpenId === v.id && (
                        <div
                          role="menu"
                          className="mt-2 w-40 rounded-md bg-white text-black shadow-lg border border-gray-200 absolute right-0"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <button
                            className="w-full text-left px-4 py-2 text-sm hover:bg-gray-100"
                            onClick={() => {
                              const link = canonicalLinkFor(v.videoUrl);
                              if (link) {
                                try { navigator.clipboard.writeText(link); } catch {}
                              }
                              setShareOpenId(null);
                            }}
                          >
                            Copy Link
                          </button>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Overlay meta inside the 9:16 box (no CTA buttons) */}
                  <div className="absolute inset-x-0 bottom-0 p-4 md:p-6 text-white bg-gradient-to-t from-black/60 to-transparent rounded-b-md">
                    <h3 className="text-lg md:text-xl font-semibold line-clamp-2">{v.title || 'Untitled'}</h3>
                    <div className="mt-1 text-sm text-white/80">{timeAgo(v.createdAt)}</div>
                  </div>
                </div>
              </div>
            </section>
          ))}
        </div>
      </div>

      {/* Up/Down controls (float over content on the right edge) */}
      <div className="absolute right-4 top-1/2 -translate-y-1/2 flex flex-col gap-3">
        <button
          onClick={goPrev}
          disabled={index === 0}
          aria-label="Previous video"
          className={`p-3 rounded-full shadow bg-white text-black hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed`}
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5">
            <path fillRule="evenodd" d="M12 4.5a.75.75 0 01.53.22l7.5 7.5a.75.75 0 11-1.06 1.06L12.75 6.81v12.44a.75.75 0 01-1.5 0V6.81L5.03 13.28a.75.75 0 11-1.06-1.06l7.5-7.5a.75.75 0 01.53-.22z" clipRule="evenodd" />
          </svg>
        </button>
        <button
          onClick={goNext}
          disabled={index >= videos.length - 1}
          aria-label="Next video"
          className={`p-3 rounded-full shadow bg-white text-black hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed`}
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5">
            <path fillRule="evenodd" d="M12 19.5a.75.75 0 01-.53-.22l-7.5-7.5a.75.75 0 011.06-1.06l6.47 6.47V4.75a.75.75 0 011.5 0v11.44l6.47-6.47a.75.75 0 111.06 1.06l-7.5 7.5a.75.75 0 01-.53.22z" clipRule="evenodd" />
          </svg>
        </button>
      </div>
    </div>
  );
}
