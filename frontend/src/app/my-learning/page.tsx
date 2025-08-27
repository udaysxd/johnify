'use client';

import { useEffect, useState, useRef } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import Image from 'next/image';
import { useAuth } from '@/contexts/AuthContext';


type Video = {
  id: string;
  title: string;
  thumbnailUrl: string;
  videoUrl: string;
  createdAt: string;
  status: 'processing' | 'completed' | 'failed';
  public: boolean;
};



export default function HomePage() {
  const { user, loading: isAuthLoading } = useAuth();
  const isAuthenticated = !!user;
  const router = useRouter();
  // Capitalize the first alphabetical character, ignoring leading spaces/punctuation
  const capitalizeFirst = (s?: string): string => {
    if (!s) return 'Untitled Video';
    const match = s.match(/[A-Za-z]/);
    if (!match) return s.trim() ? s : 'Untitled Video';
    const i = match.index as number;
    return s.slice(0, i) + s.charAt(i).toUpperCase() + s.slice(i + 1);
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
  const [videos, setVideos] = useState<Video[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedVideo, setSelectedVideo] = useState<Video | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const modalRef = useRef<HTMLDivElement>(null);
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<{ open: boolean; video: Video | null }>({ open: false, video: null });

  // Close the card action menu when clicking outside or pressing Escape
  useEffect(() => {
    const handleDocClick = (e: MouseEvent) => {
      const target = e.target as HTMLElement | null;
      if (!target) return;
      // Ignore clicks inside menu trigger or panel
      if (target.closest('[data-ml-menu-trigger]') || target.closest('[data-ml-menu-panel]')) return;
      if (menuOpenId) setMenuOpenId(null);
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && menuOpenId) setMenuOpenId(null);
    };
    document.addEventListener('mousedown', handleDocClick);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleDocClick);
      document.removeEventListener('keydown', handleKey);
    };
  }, [menuOpenId]);

  const openDeleteConfirm = (video: Video) => {
    setMenuOpenId(null);
    setDeleteConfirm({ open: true, video });
  };

  const performDeleteVideo = async () => {
    const video = deleteConfirm.video;
    if (!video) return;
    try {
      console.log('[MyLearning] Deleting video', video.id);
      // Optimistic remove
      setVideos((prev) => prev.filter((v) => v.id !== video.id));
      setMenuOpenId(null);
      setDeleteConfirm({ open: false, video: null });
      const resp = await fetch(`/api/videos/${encodeURIComponent(video.id)}`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
      });
      if (!resp.ok) {
        const err: { error?: string; detail?: string } = await resp.json().catch(() => ({}));
        setError(err?.error || err?.detail || 'Failed to delete video');
        // Attempt to refetch to restore state accurately
        try {
          const r = await fetch('/api/videos/my-videos', { cache: 'no-store' });
          if (r.ok) {
            const data = await r.json();
            if (Array.isArray(data)) setVideos(data);
          }
        } catch {}
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to delete video');
    }
  };

  const handleToggleVisibility = async (video: Video, nextPublic: boolean) => {
    try {
      // Optimistic update
      setVideos((prev) => prev.map((v) => (v.id === video.id ? { ...v, public: nextPublic } : v)));
      setMenuOpenId(null);
      const resp = await fetch(`/api/videos/${encodeURIComponent(video.id)}/visibility`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ public: nextPublic }),
      });
      if (!resp.ok) {
        // Revert on error
        setVideos((prev) => prev.map((v) => (v.id === video.id ? { ...v, public: !nextPublic } : v)));
        const err: { error?: string; detail?: string } = await resp
          .json()
          .catch(() => ({}));
        setError(err?.error || err?.detail || 'Failed to update visibility');
      }
    } catch (e) {
      setVideos((prev) => prev.map((v) => (v.id === video.id ? { ...v, public: !nextPublic } : v)));
      setError(e instanceof Error ? e.message : 'Failed to update visibility');
    }
  };

  // Handle unauthenticated state - this needs to be the first effect
  useEffect(() => {
    if (!isAuthLoading && !isAuthenticated && !window.location.pathname.startsWith('/auth/signin')) {
      console.log('Redirecting to signin');
      router.push('/auth/signin');
    }
  }, [isAuthenticated, isAuthLoading, router]);

  // Fetch user's videos - this is the second effect
  useEffect(() => {
    const fetchVideos = async () => {
      // Only proceed if we have a valid session
      if (isAuthLoading || !isAuthenticated) {
        console.log('Not authenticated or still loading, waiting for auth...');
        setIsLoading(false);
        return;
      }

      try {
        setIsLoading(true);
        setError(null);
        // Use cookie-based auth via Next.js API route; no header token required
        console.log('Fetching videos from /api/videos/my-videos...');
        
        const response = await fetch('/api/videos/my-videos', {
          method: 'GET',
          headers: {
            'Content-Type': 'application/json',
          },
          cache: 'no-store',
        });
        
        console.log('API Response status:', response.status);
        
        if (response.status === 401) {
          setError('Your session has expired. Please sign in again.');
          setIsLoading(false);
          return;
        }

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.error || `Failed to fetch videos: ${response.statusText}`);
        }

        const data = await response.json();
        console.log('Fetched videos:', data);
        
        // Ensure we have an array of videos
        if (Array.isArray(data)) {
          setVideos(data);
        } else {
          console.error('Expected an array of videos but got:', data);
          setVideos([]);
        }
      } catch (err) {
        console.error('Error in fetchVideos:', err);
        setError(err instanceof Error ? err.message : 'An error occurred');
      } finally {
        setIsLoading(false);
      }
    };

    // Only fetch videos if we're authenticated
    if (isAuthenticated) {
      fetchVideos();
    }
  }, [isAuthenticated, isAuthLoading]);

  // Close modal when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (modalRef.current && !modalRef.current.contains(event.target as Node)) {
        setSelectedVideo(null);
      }
    }

    if (selectedVideo) {
      document.addEventListener('mousedown', handleClickOutside);
      document.body.style.overflow = 'hidden'; // Prevent scrolling when modal is open
    } else {
      document.body.style.overflow = 'auto';
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.body.style.overflow = 'auto';
    };
  }, [selectedVideo]);

  // Try to programmatically play when a video is selected
  useEffect(() => {
    if (selectedVideo && videoRef.current) {
      // Reload the element to ensure fresh source
      try {
        videoRef.current.load();
      } catch {}
      const tryPlay = async () => {
        try {
          await videoRef.current?.play();
        } catch (err) {
          console.log('Video play() was prevented:', err);
        }
      };
      // Give the browser a tick to attach source
      setTimeout(tryPlay, 0);
    }
  }, [selectedVideo]);

  // Show loading state while checking auth status or fetching videos
  if (isAuthLoading || (isAuthenticated && isLoading)) {
    return (
      <div className="min-h-screen bg-gray-100">
        <div className="container mx-auto px-4 py-8">
          <h1 className="text-2xl font-bold mb-6">My Videos</h1>
          <div className="flex justify-center items-center h-64">
            <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-blue-500"></div>
          </div>
        </div>
      </div>
    );
  }

  // Show error state if there was an error
  if (error) {
    return (
      <div className="min-h-screen bg-gray-100">
        <div className="container mx-auto px-4 py-8">
          <h1 className="text-2xl font-bold mb-6">My Videos</h1>
          <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded relative" role="alert">
            <strong className="font-bold">Error: </strong>
            <span className="block sm:inline">{error}</span>
          </div>
          <div className="mt-4">
            <button 
              onClick={() => window.location.reload()}
              className="bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded"
            >
              Refresh Page
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Don't render anything if not authenticated - the effect will handle redirect
  if (!isAuthenticated) {
    return null;
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="py-8 px-4 sm:px-6 lg:px-8">
        <div className="max-w-7xl mx-auto">
          <div className="flex justify-between items-center mb-8">
            <h1 className="text-3xl font-bold text-gray-900">
              My Learning<span className="ml-1 align-middle text-sm font-normal text-gray-500">({videos.length})</span>
            </h1>
            {videos.length > 0 && (
              <Link
                href="/tutor"
                className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
              >
                Create My Tutor
              </Link>
            )}
          </div>

          {error ? (
            <div className="bg-red-50 border-l-4 border-red-400 p-4 mb-6">
              <div className="flex">
                <div className="flex-shrink-0">
                  <svg className="h-5 w-5 text-red-400" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                  </svg>
                </div>
                <div className="ml-3">
                  <p className="text-sm text-red-700">
                    {error}. Please try again later or contact support if the problem persists.
                  </p>
                </div>
              </div>
            </div>
          ) : null}

          {videos.length === 0 && !error ? (
            <div className="text-center py-12">
              <svg
                className="mx-auto h-12 w-12 text-gray-400"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2z"
                />
              </svg>
              <h3 className="mt-2 text-sm font-medium text-gray-900">You have no learning videos created yet.</h3>
              <p className="mt-1 text-sm text-gray-500">Get started by creating your first AI tutor.</p>
              <div className="mt-6">
                <Link
                  href="/tutor"
                  className="inline-flex items-center px-4 py-2 border border-transparent shadow-sm text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
                >
                  <svg
                    className="-ml-1 mr-2 h-5 w-5"
                    xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 20 20"
                    fill="currentColor"
                    aria-hidden="true"
                  >
                    <path
                      fillRule="evenodd"
                      d="M10 5a1 1 0 011 1v3h3a1 1 0 110 2h-3v3a1 1 0 01-1 1h-3a1 1 0 110-2h3V6a1 1 0 011-1z"
                      clipRule="evenodd"
                    />
                  </svg>
                  Create My Tutor
                </Link>
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
              {videos.map((video) => (
                <div 
                  key={video.id} 
                  className="relative bg-white shadow rounded-lg hover:shadow-lg transition-shadow duration-200 cursor-pointer overflow-visible z-10"
                  onClick={() => setSelectedVideo(video)}
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
                        {/* No title text on top of the image */}
                      </div>
                    )}
                    {/* Visibility badge */}
                    <span className={`absolute bottom-2 left-2 text-xs px-2 py-1 rounded ${video.public ? 'bg-green-600 text-white' : 'bg-gray-700 text-white'}`}>
                      {video.public ? 'Public' : 'Private'}
                    </span>
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
                  <div className="px-4 pb-3 pt-3 relative">
                    <div className="flex items-start justify-between gap-2">
                      <h3 className="text-base font-medium text-gray-900 truncate">
                        {capitalizeFirst(video.title)}
                      </h3>
                      {/* Three-dot menu next to title (vertical) */}
                      <div
                        className="relative"
                        onClick={(e) => e.stopPropagation()}
                        data-ml-menu-trigger
                      >
                        <button
                          aria-label="Options"
                          onClick={() => setMenuOpenId((prev) => (prev === video.id ? null : video.id))}
                          className="p-1 rounded hover:bg-gray-100 text-gray-700"
                        >
                          {/* Vertical dots icon */}
                          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
                            <path d="M10 4a2 2 0 110-4 2 2 0 010 4zM10 12a2 2 0 110-4 2 2 0 010 4zM10 20a2 2 0 110-4 2 2 0 010 4z" />
                          </svg>
                        </button>
                        {menuOpenId === video.id && (
                          <div
                            className="absolute right-0 bottom-full mb-2 w-44 bg-white text-gray-700 rounded shadow-lg border border-gray-200 z-50"
                            onClick={(e) => e.stopPropagation()}
                            data-ml-menu-panel
                          >
                            <button
                              className="w-full text-left px-4 py-2 hover:bg-gray-100"
                              onClick={() => handleToggleVisibility(video, !video.public)}
                            >
                              {video.public ? 'Make Private' : 'Make Public'}
                            </button>
                            <button
                              className="w-full text-left px-4 py-2 hover:bg-gray-100 text-red-600"
                              onClick={() => openDeleteConfirm(video)}
                            >
                              Delete
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                    <p className="mt-1 text-sm text-gray-500">{timeAgo(video.createdAt)}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Delete confirmation modal */}
      {deleteConfirm.open && deleteConfirm.video && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/60 z-0" onClick={() => setDeleteConfirm({ open: false, video: null })} />
          <div className="relative z-10 w-full max-w-md mx-auto bg-white rounded-lg shadow-xl overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="px-6 pt-6">
              <h3 className="text-lg font-semibold text-gray-900">Delete video?</h3>
              <p className="mt-2 text-sm text-gray-600">This action cannot be undone. The video will be permanently removed from your account.</p>
            </div>
            <div className="mt-6 px-6 pb-6 flex justify-end gap-3">
              <button
                onClick={() => setDeleteConfirm({ open: false, video: null })}
                className="px-4 py-2 rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={performDeleteVideo}
                className="px-4 py-2 rounded-md bg-red-600 text-white hover:bg-red-700"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Video Modal */}
      {selectedVideo && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80">
          <div 
            ref={modalRef}
            className="relative w-full max-w-4xl bg-white rounded-lg overflow-hidden shadow-xl"
          >
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
                  // Attempt to auto-play once metadata is available
                  videoRef.current?.play().catch((e) => {
                    console.log('Auto-play blocked on metadata:', e);
                  });
                }}
                onError={() => {
                  const v = videoRef.current;
                  const err = v?.error;
                  console.error('Video error event', {
                    src: proxySrc,
                    networkState: v?.networkState,
                    readyState: v?.readyState,
                    errorCode: err?.code,
                    errorMessage: err?.message,
                  });
                }}
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
              <p className="mt-2 text-gray-600">{timeAgo(selectedVideo.createdAt)}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
