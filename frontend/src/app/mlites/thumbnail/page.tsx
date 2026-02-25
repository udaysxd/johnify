"use client";

import React, { useState } from "react";
import Image from "next/image";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

export default function MlitesThumbnailPage() {
  const [topic, setTopic] = useState("");
  const [style, setStyle] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [thumbUrl, setThumbUrl] = useState<string | null>(null);
  const [resultPath, setResultPath] = useState<string | null>(null);

  async function handleGenerate(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setThumbUrl(null);
    setResultPath(null);
    const body = {
      topic: topic.trim(),
      style: style.trim() || undefined,
    };
    if (!body.topic) {
      setError("Please enter a topic");
      return;
    }
    setLoading(true);
    try {
      const resp = await fetch(`${BACKEND_URL}/api/mlites/thumbnail`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(body),
      });
      const data = await resp.json();
      if (!resp.ok) {
        const msg = data?.detail?.message || data?.detail || data?.message || "Failed to generate thumbnail";
        throw new Error(msg);
      }
      // Prefer a public URL when available (GCS in prod). Otherwise construct a local /videos-style path if applicable.
      if (data.url) {
      } else if (data.path) {
        // In local dev, we can't read arbitrary files; the app may have a /videos static serving route.
        // If your backend exposes a /videos path, you can adapt here. For now, show the absolute path as text.
        setResultPath(data.path);
      }
    } catch (err) {
      const errMsg = (err as Error).message || "Error";
      setError(errMsg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="max-w-2xl mx-auto p-6">
      <h1 className="text-2xl font-semibold mb-4">MLites Thumbnail Generator</h1>
      <p className="text-sm text-gray-600 mb-6">Enter any topic (e.g., Mozart, Steve Jobs, skincare, travel) to generate a portrait 1080x1920 thumbnail image. This will not create a video.</p>

      <form onSubmit={handleGenerate} className="space-y-4">
        <div>
          <label className="block text-sm font-medium mb-1">Topic</label>
          <input
            value={topic}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setTopic(e.target.value)}
            className="w-full border rounded px-3 py-2"
            placeholder="e.g., Mozart | Steve Jobs | Top 10 skincare tips"
          />
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">Style (optional)</label>
          <input
            value={style}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setStyle(e.target.value)}
            className="w-full border rounded px-3 py-2"
            placeholder="e.g., Top 10, Best 10 (leave empty for plain topic)"
          />
        </div>
        <button
          type="submit"
          disabled={loading}
          className="px-4 py-2 rounded bg-black text-white disabled:opacity-60"
        >
          {loading ? "Generating…" : "Generate Thumbnail"}
        </button>
      </form>

      {error && (
        <div className="mt-4 text-red-600 text-sm">{error}</div>
      )}

      {thumbUrl && (
        <div className="mt-6">
          <div className="text-sm text-gray-700 mb-2">Preview:</div>
          <Image
            src={thumbUrl}
            alt="MLites Thumbnail"
            width={360}
            height={640}
            className="w-64 border rounded h-auto"
            priority={false}
          />
          <div className="mt-2 text-xs text-gray-500 break-all">{thumbUrl}</div>
        </div>
      )}

      {resultPath && !thumbUrl && (
        <div className="mt-6 text-sm text-gray-700">
          Thumbnail saved at: <code className="text-xs">{resultPath}</code>
          <div className="text-xs text-gray-500 mt-1">If you need this served in dev, add a static route to expose generated files or wire it to your existing /videos endpoint.</div>
        </div>
      )}
    </div>
  );
}
