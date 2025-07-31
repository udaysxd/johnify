'use client';

import { useState } from 'react';
import VideoDebug from '@/components/VideoDebug';

export default function VideoTestPage() {
  const [videoUrl, setVideoUrl] = useState('');
  const [testUrl, setTestUrl] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setTestUrl(videoUrl);
  };

  return (
    <div className="min-h-screen bg-gray-50 py-12 px-4">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-3xl font-bold text-center mb-8">Video URL Tester</h1>
        
        <div className="bg-white p-6 rounded-lg shadow-md mb-8">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="videoUrl" className="block text-sm font-medium text-gray-700 mb-1">
                Enter Video URL
              </label>
              <div className="flex">
                <input
                  type="text"
                  id="videoUrl"
                  value={videoUrl}
                  onChange={(e) => setVideoUrl(e.target.value)}
                  placeholder="https://example.com/video.mp4"
                  className="flex-1 min-w-0 block w-full px-3 py-2 rounded-l-md border border-gray-300 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                />
                <button
                  type="submit"
                  className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-r-md text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
                >
                  Test URL
                </button>
              </div>
              <p className="mt-1 text-sm text-gray-500">
                Try: /videos/rolex_watch/rolex_watch_explanation.mp4 or full URL
              </p>
            </div>
          </form>
        </div>

        {testUrl && (
          <div className="bg-white p-6 rounded-lg shadow-md">
            <h2 className="text-xl font-semibold mb-4">Test Results</h2>
            <div className="border rounded-lg overflow-hidden">
              <VideoDebug videoUrl={testUrl} />
            </div>
            
            <div className="mt-6 p-4 bg-gray-50 rounded-lg">
              <h3 className="font-medium mb-2">Troubleshooting Tips</h3>
              <ul className="list-disc pl-5 space-y-1 text-sm text-gray-600">
                <li>Make sure the URL is correct and the video file exists</li>
                <li>Check if the URL is accessible from your browser</li>
                <li>Verify CORS headers are properly set on the server</li>
                <li>Try adding a cache-busting parameter: {`${testUrl}?t=${Date.now()}`}</li>
              </ul>
            </div>
          </div>
        )}
        
        <div className="mt-8 p-6 bg-white rounded-lg shadow-md">
          <h2 className="text-xl font-semibold mb-4">Common Test URLs</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <button
              onClick={() => setVideoUrl('/videos/rolex_watch/rolex_watch_explanation.mp4')}
              className="text-left p-3 border rounded hover:bg-gray-50 text-sm text-blue-600"
            >
              <div className="font-medium">Rolex Watch</div>
              <div className="text-xs text-gray-500 truncate">/videos/rolex_watch/rolex_watch_explanation.mp4</div>
            </button>
            <button
              onClick={() => setVideoUrl('/videos/is_money_important_or_love/is_money_important_or_love_explanation.mp4')}
              className="text-left p-3 border rounded hover:bg-gray-50 text-sm text-blue-600"
            >
              <div className="font-medium">Money vs Love</div>
              <div className="text-xs text-gray-500 truncate">/videos/is_money_important_or_love/is_money_important_or_love_explanation.mp4</div>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
