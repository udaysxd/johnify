'use client';

import { useEffect, useRef } from 'react';

export default function HeroVideo({ src }: { src: string }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const playAttemptRef = useRef<number | NodeJS.Timeout | null>(null);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    // Simple error logging
    const handleError = () => {
      console.error('Video error:', video.error);
    };

    // Try to play the video with better error handling
    const playVideo = async () => {
      if (!video) return;
      
      try {
        // Clear any pending play attempts
        if (playAttemptRef.current) {
          clearTimeout(playAttemptRef.current);
        }
        
        // Wait for video to be ready to play
        if (video.readyState < 3) { // HAVE_FUTURE_DATA
          video.load();
          await new Promise(resolve => {
            video.oncanplay = resolve;
            // Set a timeout in case canplay never fires
            playAttemptRef.current = window.setTimeout(resolve, 1000) as unknown as number;
          });
          video.oncanplay = null;
        }
        
        // Only try to play if not already playing
        if (video.paused) {
          await video.play();
        }
      } catch (error: unknown) {
        // Don't log the common autoplay error to reduce console noise
        const errorMessage = error instanceof Error ? error.message : String(error);
        if (!errorMessage.includes('play() was interrupted')) {
          console.error('Video play error:', error);
        }
      }
    };

    // Set up event listeners
    video.addEventListener('error', handleError);
    
    // Try to play when enough data is loaded
    video.addEventListener('canplay', playVideo);
    
    // Initial play attempt
    playVideo();

    // Cleanup
    return () => {
      video.removeEventListener('error', handleError);
      video.removeEventListener('canplay', playVideo);
      if (playAttemptRef.current !== null) {
        clearTimeout(playAttemptRef.current as number | NodeJS.Timeout);
      }
      if (video) {
        video.pause();
        video.removeAttribute('src');
        video.load();
      }
    };
  }, [src]);

  return (
    <div className="aspect-video bg-black">
      <video
        ref={videoRef}
        className="w-full h-full object-cover"
        autoPlay
        loop
        muted
        playsInline
        preload="auto"
        controls={false} // Remove controls for a cleaner look
      >
        <source src={src} type="video/mp4" />
        Your browser does not support the video tag.
      </video>
    </div>
  );
}
