'use client';

import { useEffect, useRef } from 'react';

export default function HeroVideo({ src }: { src: string }) {
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    // Simple error logging
    video.onerror = () => {
      console.error('Video error:', video.error);
    };

    // Try to play the video
    const playVideo = () => {
      video.play().catch(error => {
        console.error('Auto-play failed:', error);
      });
    };

    // Try to play when enough data is loaded
    video.oncanplay = playVideo;
    
    // Also try to play immediately
    playVideo();

    return () => {
      video.pause();
      video.removeAttribute('src');
      video.load();
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
        controls // Add controls for manual playback
      >
        <source src={src} type="video/mp4" />
        Your browser does not support the video tag.
      </video>
    </div>
  );
}
