'use client';

import { useEffect, useRef } from 'react';

export default function HeroVideo({ src }: { src: string }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const playAttemptRef = useRef<number | NodeJS.Timeout | null>(null);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    // Error logging only; do not auto-play. Let the user click play.
    const handleError = () => {
      console.error('Video error:', video.error);
    };

    video.addEventListener('error', handleError);

    // Cleanup
    return () => {
      video.removeEventListener('error', handleError);
      if (playAttemptRef.current !== null) {
        clearTimeout(playAttemptRef.current as number | NodeJS.Timeout);
      }
    };
  }, [src]);

  return (
    <div className="aspect-video bg-black">
      <video
        ref={videoRef}
        className="w-full h-full object-cover"
        loop
        playsInline
        preload="metadata"
        muted
        controls // Show controls so users get seek/progress bar and can manage sound
      >
        <source src={src} type="video/mp4" />
        Your browser does not support the video tag.
      </video>
    </div>
  );
}
