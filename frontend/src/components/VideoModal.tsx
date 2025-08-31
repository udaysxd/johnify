"use client";

import React, { useEffect, useRef } from "react";

export type VideoModalProps = {
  isOpen: boolean;
  onClose: () => void;
  title?: string;
  videoUrl: string;
  createdAt?: string;
  creatorName?: string | null;
  showMeta?: boolean; // show title/creator/time section below player
  maxWidthClass?: string; // e.g., "max-w-3xl" | "max-w-4xl"
};

function timeAgo(iso?: string): string {
  if (!iso) return "";
  const now = Date.now();
  const then = new Date(iso).getTime();
  if (isNaN(then)) return "";
  const diff = Math.max(0, now - then);
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return `${sec || 1} second${sec === 1 ? "" : "s"} ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} minute${min === 1 ? "" : "s"} ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} hour${hr === 1 ? "" : "s"} ago`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day} day${day === 1 ? "" : "s"} ago`;
  const mon = Math.floor(day / 30);
  if (mon < 12) return `${mon} month${mon === 1 ? "" : "s"} ago`;
  const yr = Math.floor(day / 365);
  return `${yr} year${yr === 1 ? "" : "s"} ago`;
}

export default function VideoModal({
  isOpen,
  onClose,
  title,
  videoUrl,
  createdAt,
  creatorName,
  showMeta = true,
  maxWidthClass = "max-w-3xl",
}: VideoModalProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const modalRef = useRef<HTMLDivElement>(null);

  // Close on outside click and lock body scroll
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (modalRef.current && !modalRef.current.contains(event.target as Node)) {
        onClose();
      }
    }
    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "auto";
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.body.style.overflow = "auto";
    };
  }, [isOpen, onClose]);

  // Attempt autoplay when opened
  useEffect(() => {
    if (!isOpen || !videoRef.current) return;
    try {
      // Reload to ensure fresh source
      videoRef.current.load();
    } catch {}
    setTimeout(async () => {
      try {
        await videoRef.current?.play();
      } catch {}
    }, 0);
  }, [isOpen]);

  if (!isOpen) return null;

  const proxySrc = `/api/proxy-video?url=${encodeURIComponent(videoUrl)}`;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" role="dialog" aria-modal="true">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      {/* Modal content */}
      <div ref={modalRef} className={`relative z-10 w-full ${maxWidthClass} mx-4 bg-white rounded-lg shadow-lg overflow-hidden`}>
        <div className="relative pt-[56.25%] bg-black">
          <video
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
              videoRef.current?.play().catch(() => {});
            }}
            onError={() => {
              const v = videoRef.current;
              const err = v?.error;
              console.error("Video error event", {
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
          <button
            onClick={onClose}
            className="absolute top-4 right-4 p-2 rounded-full bg-black/50 text-white hover:bg-black/70 transition-colors"
            aria-label="Close"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        {showMeta && (
          <div className="p-6">
            {title ? <h2 className="text-2xl font-bold text-gray-900">{title}</h2> : null}
            {creatorName ? <p className="mt-2 text-gray-800 font-medium">{creatorName}</p> : null}
            {createdAt ? <p className="mt-1 text-gray-600">{timeAgo(createdAt)}</p> : null}
          </div>
        )}
      </div>
    </div>
  );
}
