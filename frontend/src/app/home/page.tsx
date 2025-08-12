'use client';

import { useEffect, useState, useRef } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import Header from '@/components/Header';
import Image from 'next/image';
import { useAuth } from '@/providers/AuthProvider';


type Video = {
  id: string;
  title: string;
  thumbnailUrl: string;
  videoUrl: string;
  createdAt: string;
  status: 'processing' | 'completed' | 'failed';
};



export default function HomePage() {
  const { isAuthenticated, isLoading: isAuthLoading } = useAuth();
  const router = useRouter();
  const [videos, setVideos] = useState<Video[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedVideo, setSelectedVideo] = useState<Video | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const modalRef = useRef<HTMLDivElement>(null);

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
        
        // Get the token from sessionStorage
        const token = sessionStorage.getItem('access_token');
        
        if (!token) {
          console.error('No access token found in session');
          setError('Authentication required. Please sign in again.');
          setIsLoading(false);
          return;
        }
        
        console.log('Fetching videos from /api/videos/my-videos...');
        
        const response = await fetch('/api/videos/my-videos', {
          method: 'GET',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`,
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

  // Show loading state while checking auth status or fetching videos
  if (isAuthLoading || (isAuthenticated && isLoading)) {
    return (
      <div className="min-h-screen bg-gray-100">
        <Header />
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
        <Header />
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
  if (status !== 'authenticated') {
    return null;
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <Header />
      <div className="py-8 px-4 sm:px-6 lg:px-8">
        <div className="max-w-7xl mx-auto">
          <div className="flex justify-between items-center mb-8">
            <h1 className="text-3xl font-bold text-gray-900">Your Library</h1>
            <Link
              href="/learn"
              className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
            >
              Learn New
            </Link>
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
                  d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"
                />
              </svg>
              <h3 className="mt-2 text-sm font-medium text-gray-900">No videos yet</h3>
              <p className="mt-1 text-sm text-gray-500">Get started by creating your first video.</p>
              <div className="mt-6">
                <Link
                  href="/generate"
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
                  New Video
                </Link>
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
              {videos.map((video) => (
                <div 
                  key={video.id} 
                  className="bg-white overflow-hidden shadow rounded-lg hover:shadow-lg transition-shadow duration-200 cursor-pointer"
                  onClick={() => setSelectedVideo(video)}
                >
                  <div className="relative pb-[56.25%] bg-black">
                    {video.thumbnailUrl ? (
                      <Image
                        className="w-full h-full object-cover"
                        src={video.thumbnailUrl}
                        alt={video.title}
                        width={640}
                        height={360}
                        unoptimized
                      />
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
                        <h3 className="text-lg font-semibold mb-1">Video Preview</h3>
                        <p className="text-sm opacity-80">{video.title || 'Untitled Video'}</p>
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
                  <div className="p-4">
                    <h3 className="text-lg font-medium text-gray-900 truncate">{video.title}</h3>
                    <p className="mt-1 text-sm text-gray-500">
                      Created on {new Date(video.createdAt).toLocaleDateString()}
                    </p>
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
          <div 
            ref={modalRef}
            className="relative w-full max-w-4xl bg-white rounded-lg overflow-hidden shadow-xl"
          >
            <div className="relative pt-[56.25%] bg-black">
              <video
                ref={videoRef}
                className="absolute top-0 left-0 w-full h-full"
                controls
                autoPlay
                src={selectedVideo.videoUrl}
                onEnded={() => videoRef.current?.pause()}
              >
                <source src={selectedVideo.videoUrl} type="video/mp4" />
                Your browser does not support the video tag.
              </video>
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
              <p className="mt-2 text-gray-600">
                Created on {new Date(selectedVideo.createdAt).toLocaleDateString()}
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
