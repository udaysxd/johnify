'use client';

import { useState, useEffect } from 'react';

interface VideoInfo {
  url: string;
  level: number;
  title: string;
}

interface VideoPlayerProps {
  videos: VideoInfo[];
  onVideoChange?: (video: VideoInfo) => void;
  initialLevel?: number;
}

export default function VideoPlayer({ videos, onVideoChange, initialLevel = 1 }: VideoPlayerProps) {
  const [currentVideoIndex, setCurrentVideoIndex] = useState<number>(
    Math.max(0, videos.findIndex(v => v.level === initialLevel))
  );
  const [error, setError] = useState<string | null>(null);
  interface DebugInfo {
    contentType?: string;
    contentLength?: string;
    [key: string]: unknown;
  }
  const [debugInfo, setDebugInfo] = useState<DebugInfo | null>(null);
  const [isChecking, setIsChecking] = useState(true);
  const [isPlaying, setIsPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  // Removed unused duration state

  const [isLoading, setIsLoading] = useState(true);

  const currentVideo = videos[currentVideoIndex];
  const videoUrl = currentVideo?.url;

  // Handle video change
  useEffect(() => {
    if (videos.length === 0) return;
    
    // If current video is no longer in the list, reset to first video
    if (currentVideoIndex >= videos.length) {
      setCurrentVideoIndex(0);
    }
  }, [videos, currentVideoIndex]);

  // Check video accessibility when URL changes
  useEffect(() => {
    const checkVideoAccess = async () => {
      if (!videoUrl) return;
      
      setIsChecking(true);
      setError(null);
      
      try {
        const response = await fetch('/api/check-video', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ videoUrl })
        });
        
        const result = await response.json();
        
        if (!response.ok) {
          throw new Error(result.error || 'Failed to access video');
        }
        
        setDebugInfo(result);
      } catch (err) {
        console.error('Error checking video access:', err);
        setError(err instanceof Error ? err.message : 'Failed to load video');
      } finally {
        setIsChecking(false);
        setIsLoading(false);
      }
    };
    
    checkVideoAccess();
  }, [videoUrl]);

  const handleError = (e: React.SyntheticEvent<HTMLVideoElement>) => {
    const video = e.target as HTMLVideoElement;
    const error = video.error;
    let errorMessage = 'Failed to load video';
    
    if (error) {
      switch(error.code) {
        case MediaError.MEDIA_ERR_ABORTED:
          errorMessage = 'Video playback was aborted';
          break;
        case MediaError.MEDIA_ERR_NETWORK:
          errorMessage = 'A network error occurred while loading the video';
          break;
        case MediaError.MEDIA_ERR_DECODE:
          errorMessage = 'Error decoding the video';
          break;
        case MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED:
          errorMessage = 'Video format is not supported by your browser';
          break;
      }
    }
    
    console.error('Video error:', { 
      error: error ? `${error.code}: ${error.message}` : 'Unknown error',
      video: {
        readyState: video.readyState,
        networkState: video.networkState,
        error: video.error,
        currentSrc: video.currentSrc,
        src: video.src,
        videoWidth: video.videoWidth,
        videoHeight: video.videoHeight,
        buffered: video.buffered,
        seekable: video.seekable,
        duration: video.duration,
        paused: video.paused,
        ended: video.ended,
      }
    });
    
    setError(errorMessage);
  };

  const handleTimeUpdate = (e: React.SyntheticEvent<HTMLVideoElement>) => {
    const video = e.target as HTMLVideoElement;
    setProgress((video.currentTime / video.duration) * 100);
  };

  const handleLoadedMetadata = (e: React.SyntheticEvent<HTMLVideoElement>) => {
    const video = e.target as HTMLVideoElement;
    // Try to play the video automatically
    video.play().catch(err => {
      console.log('Autoplay prevented:', err);
      // Autoplay was prevented, we'll let the user start it manually
    });
  };

  const handlePlay = () => setIsPlaying(true);
  const handlePause = () => setIsPlaying(false);

  const handleRetry = async () => {
    setError(null);
    setIsChecking(true);
    
    if (!videoUrl) return;
    
    // Force a re-render of the video element
    const newUrl = `${videoUrl}${videoUrl.includes('?') ? '&' : '?'}t=${Date.now()}`;
    
    // Update the videos array with the new URL
    const updatedVideos = [...videos];
    updatedVideos[currentVideoIndex] = {
      ...updatedVideos[currentVideoIndex],
      url: newUrl
    };
    
    // Trigger re-render with the new URL
    setCurrentVideoIndex(currentVideoIndex);
  };
  
  const handleVideoChange = (index: number) => {
    if (index === currentVideoIndex) return;
    setCurrentVideoIndex(index);
    if (onVideoChange) {
      onVideoChange(videos[index]);
    }
    setIsPlaying(false);
    setProgress(0);
  };

  if (videos.length === 0) {
    return (
      <div className="bg-yellow-50 border-l-4 border-yellow-400 p-4 rounded">
        <div className="flex">
          <div className="flex-shrink-0">
            <svg className="h-5 w-5 text-yellow-400" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
            </svg>
          </div>
          <div className="ml-3">
            <h3 className="text-sm font-medium text-yellow-800">No videos available</h3>
            <div className="mt-2 text-sm text-yellow-700">
              <p>There are no videos to display. Please try generating some videos first.</p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (isChecking || isLoading) {
    return (
      <div className="bg-white rounded-lg shadow overflow-hidden">
        <div className="p-4 border-b border-gray-200">
          <div className="flex space-x-1">
            {videos.map((_, index) => (
              <button
                key={index}
                className={`px-4 py-2 text-sm font-medium rounded-t-md ${
                  index === currentVideoIndex
                    ? 'bg-white border-t border-l border-r border-gray-300 text-blue-600'
                    : 'text-gray-500 hover:text-gray-700 bg-gray-100'
                }`}
                disabled
              >
                Level {index + 1}
              </button>
            ))}
          </div>
        </div>
        <div className="bg-gray-100 rounded-b-lg p-8 text-center">
          <div className="inline-block animate-spin rounded-full h-12 w-12 border-4 border-blue-500 border-t-transparent"></div>
          <p className="mt-4 text-gray-700">Loading video...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-white rounded-lg shadow overflow-hidden">
        <div className="p-4 border-b border-gray-200">
          <div className="flex space-x-1">
            {videos.map((video, index) => (
              <button
                key={index}
                onClick={() => handleVideoChange(index)}
                className={`px-4 py-2 text-sm font-medium rounded-t-md ${
                  index === currentVideoIndex
                    ? 'bg-white border-t border-l border-r border-gray-300 text-blue-600'
                    : 'text-gray-500 hover:text-gray-700 bg-gray-100'
                }`}
              >
                {video.title || `Level ${video.level}`}
              </button>
            ))}
          </div>
        </div>
        <div className="bg-red-50 border-l-4 border-red-500 p-4 rounded-b-lg">
          <div className="flex">
            <div className="flex-shrink-0">
              <svg className="h-5 w-5 text-red-500" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z" clipRule="evenodd" />
              </svg>
            </div>
            <div className="ml-3">
              <h3 className="text-sm font-medium text-red-800">Error loading video</h3>
              <div className="mt-2 text-sm text-red-700">
                <p>{error}</p>
              </div>
              <div className="mt-4">
                <button
                  type="button"
                  onClick={handleRetry}
                  className="inline-flex items-center px-3 py-2 border border-transparent text-sm leading-4 font-medium rounded-md text-red-700 bg-red-100 hover:bg-red-200 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500"
                >
                  <svg className="-ml-0.5 mr-2 h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                  </svg>
                  Try again
                </button>
              </div>
              {debugInfo && (
                <details className="mt-4">
                  <summary className="text-sm font-medium text-red-800 cursor-pointer">Technical details</summary>
                  <pre className="mt-2 p-3 bg-gray-100 rounded overflow-auto text-xs">
                    {JSON.stringify(debugInfo, null, 2)}
                  </pre>
                </details>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg shadow overflow-hidden">
      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="flex -mb-px overflow-x-auto" aria-label="Video levels">
          {videos.map((video, index) => (
            <button
              key={index}
              onClick={() => handleVideoChange(index)}
              className={`whitespace-nowrap py-4 px-6 border-b-2 font-medium text-sm ${
                index === currentVideoIndex
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
              aria-current={index === currentVideoIndex ? 'page' : undefined}
            >
              {video.title || `Level ${video.level}`}
              {index === 0 && ' (Basic)'}
              {index === videos.length - 1 && ' (Advanced)'}
            </button>
          ))}
        </nav>
      </div>

      {/* Video Player */}
      <div className="relative bg-black">
        <video
          key={currentVideo.url}
          controls
          className="w-full h-auto max-h-[70vh] mx-auto"
          onError={handleError}
          onLoadedMetadata={handleLoadedMetadata}
          onTimeUpdate={handleTimeUpdate}
          onPlay={handlePlay}
          onPause={handlePause}
          onEnded={handlePause}
          playsInline
        >
          <source src={currentVideo.url} type="video/mp4" />
          Your browser does not support the video tag.
        </video>
        
        {!isPlaying && !isChecking && (
          <div className="absolute inset-0 flex items-center justify-center">
            <button
              onClick={() => {
                const video = document.querySelector('video');
                if (video) video.play().catch(console.error);
              }}
              className="p-4 bg-black bg-opacity-50 rounded-full text-white hover:bg-opacity-70 transition transform hover:scale-110"
              aria-label="Play video"
            >
              <svg className="w-16 h-16" fill="currentColor" viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8v4a1 1 0 001.555.832l3-2a1 1 0 000-1.664l-3-2z" clipRule="evenodd" />
              </svg>
            </button>
          </div>
        )}
      </div>
      
      {/* Video Info */}
      <div className="p-4 border-t border-gray-200">
        <div className="flex flex-wrap items-center justify-between gap-4 text-sm text-gray-600">
          <div className="flex items-center space-x-2">
            <span className="px-2 py-1 bg-blue-100 text-blue-800 text-xs font-medium rounded">
              {currentVideo.level === 1 && 'Beginner'}
              {currentVideo.level === 2 && 'Basic'}
              {currentVideo.level === 3 && 'Intermediate'}
              {currentVideo.level === 4 && 'Advanced'}
              {currentVideo.level === 5 && 'Expert'}
            </span>
            {debugInfo?.contentType && (
              <span>
                {debugInfo.contentType.split(';')[0].toUpperCase().replace('VIDEO/', '')}
              </span>
            )}
          </div>
          
          <div className="flex items-center space-x-4">
            {debugInfo?.contentLength && (
              <span>
                {Math.round(parseInt(debugInfo.contentLength) / 1024 / 1024 * 100) / 100} MB
              </span>
            )}
            <a
              href={currentVideo.url}
              download
              className="inline-flex items-center px-3 py-1.5 border border-gray-300 shadow-sm text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
            >
              <svg className="-ml-0.5 mr-1.5 h-4 w-4" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z" clipRule="evenodd" />
              </svg>
              Download
            </a>
          </div>
        </div>
        
        {/* Progress bar */}
        <div className="mt-3 h-1.5 w-full bg-gray-200 rounded-full overflow-hidden">
          <div 
            className="h-full bg-blue-600 transition-all duration-300 ease-out"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>
    </div>
  );
}
