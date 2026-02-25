"use client";

import Link from "next/link";

export default function LiteVideoClient({
  title,
  canonical,
  videoUrl,
  thumbnailUrl,
}: {
  title: string;
  canonical: string;
  videoUrl: string;
  thumbnailUrl: string;
}) {
  return (
    <div className="min-h-screen bg-[var(--color-background)]">
      <div className="max-w-4xl mx-auto px-4 py-8">
        <div className="mb-4">
          <h1 className="text-xl sm:text-2xl font-semibold text-gray-900 truncate" title={title}>
            {title}
          </h1>
          <p className="text-sm text-gray-600 mt-1 break-all">
            <span className="font-medium">Link:</span>{" "}
            <Link href={canonical} className="text-[var(--color-secondary)] hover:underline">
              {canonical}
            </Link>
          </p>
        </div>
        <div className="bg-black rounded-lg overflow-hidden shadow">
          <div className="relative pb-[56.25%]">
            <video
              src={videoUrl}
              poster={thumbnailUrl}
              className="absolute inset-0 w-full h-full"
              controls
              preload="metadata"
              playsInline
            >
              Your browser does not support the video tag.
            </video>
          </div>
        </div>
        <div className="mt-4 flex items-center gap-3 text-sm text-gray-600">
          <a
            href={videoUrl}
            download
            className="inline-flex items-center px-3 py-1.5 border border-gray-300 shadow-sm rounded-md text-gray-700 bg-white hover:bg-gray-50"
          >
            Download MP4
          </a>
          <button
            onClick={() => navigator.clipboard.writeText(canonical).catch(() => {})}
            className="inline-flex items-center px-3 py-1.5 border border-gray-300 shadow-sm rounded-md text-gray-700 bg-white hover:bg-gray-50"
          >
            Copy Link
          </button>
        </div>
      </div>
    </div>
  );
}
