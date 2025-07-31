'use client';

import { useState } from 'react';

export default function DebugVideoPage() {
  const [videoUrl, setVideoUrl] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!videoUrl.trim()) return;
    
    setIsLoading(true);
    setError(null);
    setResult(null);
    
    try {
      const response = await fetch('/api/debug-video', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ url: videoUrl }),
      });
      
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Failed to debug video URL');
      }
      
      const data = await response.json();
      setResult(data);
    } catch (err) {
      console.error('Debug error:', err);
      setError(err instanceof Error ? err.message : 'An unknown error occurred');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-4xl mx-auto">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-gray-900">Video Debugger</h1>
          <p className="mt-2 text-gray-600">
            Test video URL accessibility and debug video playback issues
          </p>
        </div>
        
        <div className="bg-white shadow overflow-hidden sm:rounded-lg p-6 mb-8">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="videoUrl" className="block text-sm font-medium text-gray-700">
                Video URL
              </label>
              <div className="mt-1 flex rounded-md shadow-sm">
                <input
                  type="text"
                  id="videoUrl"
                  className="flex-1 min-w-0 block w-full px-3 py-2 rounded-none rounded-l-md border border-gray-300 focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm"
                  placeholder="Enter video URL to test"
                  value={videoUrl}
                  onChange={(e) => setVideoUrl(e.target.value)}
                />
                <button
                  type="submit"
                  disabled={isLoading || !videoUrl.trim()}
                  className={`inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-r-md text-white ${
                    isLoading || !videoUrl.trim() 
                      ? 'bg-gray-400 cursor-not-allowed' 
                      : 'bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500'
                  }`}
                >
                  {isLoading ? 'Testing...' : 'Test URL'}
                </button>
              </div>
            </div>
          </form>
        </div>
        
        {error && (
          <div className="bg-red-50 border-l-4 border-red-400 p-4 mb-8">
            <div className="flex">
              <div className="flex-shrink-0">
                <svg className="h-5 w-5 text-red-400" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z" clipRule="evenodd" />
                </svg>
              </div>
              <div className="ml-3">
                <p className="text-sm text-red-700">{error}</p>
              </div>
            </div>
          </div>
        )}
        
        {result && (
          <div className="space-y-8">
            <div className="bg-white shadow overflow-hidden sm:rounded-lg">
              <div className="px-4 py-5 sm:px-6 bg-gray-50">
                <h3 className="text-lg font-medium leading-6 text-gray-900">Test Results</h3>
                <p className="mt-1 max-w-2xl text-sm text-gray-500">
                  Debug information for: <span className="font-mono text-xs break-all">{result.url}</span>
                </p>
              </div>
              
              <div className="border-t border-gray-200">
                <dl>
                  <div className="bg-gray-50 px-4 py-5 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                    <dt className="text-sm font-medium text-gray-500">Tested At</dt>
                    <dd className="mt-1 text-sm text-gray-900 sm:col-span-2 sm:mt-0">
                      {new Date(result.timestamp).toLocaleString()}
                    </dd>
                  </div>
                  
                  <div className="bg-white px-4 py-5 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                    <dt className="text-sm font-medium text-gray-500">Final URL</dt>
                    <dd className="mt-1 text-sm text-gray-900 sm:col-span-2 sm:mt-0 break-all">
                      {result.head?.url || result.url}
                    </dd>
                  </div>
                </dl>
              </div>
            </div>
            
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              <div className="bg-white shadow overflow-hidden sm:rounded-lg">
                <div className="px-4 py-5 sm:px-6 bg-blue-50">
                  <h3 className="text-lg font-medium leading-6 text-blue-900">HEAD Request</h3>
                  <p className="mt-1 text-sm text-blue-700">
                    Status: {result.head?.status} {result.head?.statusText}
                  </p>
                </div>
                <div className="border-t border-gray-200 px-4 py-5 sm:p-0">
                  <dl className="sm:divide-y sm:divide-gray-200">
                    {result.head?.headers && Object.entries(result.head.headers).map(([key, value]) => (
                      <div key={key} className="py-4 sm:grid sm:grid-cols-3 sm:gap-4 sm:py-5 sm:px-6">
                        <dt className="text-sm font-medium text-gray-500">{key}</dt>
                        <dd className="mt-1 text-sm text-gray-900 sm:col-span-2 sm:mt-0 break-all">
                          {String(value)}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </div>
              </div>
              
              {result.get && (
                <div className="bg-white shadow overflow-hidden sm:rounded-lg">
                  <div className="px-4 py-5 sm:px-6 bg-green-50">
                    <h3 className="text-lg font-medium leading-6 text-green-900">GET Request</h3>
                    <p className="mt-1 text-sm text-green-700">
                      Status: {result.get.status} {result.get.statusText}
                    </p>
                  </div>
                  <div className="border-t border-gray-200 px-4 py-5 sm:p-0">
                    <dl className="sm:divide-y sm:divide-gray-200">
                      {result.get.headers && Object.entries(result.get.headers).map(([key, value]) => (
                        <div key={key} className="py-4 sm:grid sm:grid-cols-3 sm:gap-4 sm:py-5 sm:px-6">
                          <dt className="text-sm font-medium text-gray-500">{key}</dt>
                          <dd className="mt-1 text-sm text-gray-900 sm:col-span-2 sm:mt-0 break-all">
                            {String(value)}
                          </dd>
                        </div>
                      ))}
                      
                      {result.get.bodyPreview && (
                        <div className="py-4 sm:grid sm:grid-cols-3 sm:gap-4 sm:py-5 sm:px-6">
                          <dt className="text-sm font-medium text-gray-500">Response Preview</dt>
                          <dd className="mt-1 text-sm text-gray-900 sm:col-span-2 sm:mt-0">
                            <pre className="bg-gray-50 p-2 rounded text-xs overflow-auto max-h-40">
                              {result.get.bodyPreview}
                            </pre>
                          </dd>
                        </div>
                      )}
                    </dl>
                  </div>
                </div>
              )}
            </div>
            
            <div className="bg-white shadow overflow-hidden sm:rounded-lg">
              <div className="px-4 py-5 sm:px-6 bg-gray-50">
                <h3 className="text-lg font-medium leading-6 text-gray-900">Video Player</h3>
                <p className="mt-1 text-sm text-gray-500">
                  Test video playback in the browser
                </p>
              </div>
              <div className="px-4 py-5 sm:p-6">
                <div className="aspect-w-16 aspect-h-9 bg-black rounded-lg overflow-hidden">
                  <video
                    key={result.head?.url || result.url}
                    controls
                    className="w-full h-full"
                    onError={(e) => {
                      const video = e.target as HTMLVideoElement;
                      console.error('Video error:', video.error);
                    }}
                  >
                    <source src={result.head?.url || result.url} type={result.head?.headers?.['content-type'] || 'video/mp4'} />
                    Your browser does not support the video tag.
                  </video>
                </div>
                <div className="mt-4 text-sm text-gray-600">
                  <p>Using URL: <span className="font-mono text-xs break-all">{result.head?.url || result.url}</span></p>
                  {result.head?.headers?.['content-type'] && (
                    <p>Content-Type: {result.head.headers['content-type']}</p>
                  )}
                </div>
              </div>
            </div>
            
            <div className="bg-white shadow overflow-hidden sm:rounded-lg">
              <div className="px-4 py-5 sm:px-6 bg-gray-50">
                <h3 className="text-lg font-medium leading-6 text-gray-900">Raw Debug Data</h3>
              </div>
              <div className="px-4 py-5 sm:p-6">
                <pre className="bg-gray-50 p-4 rounded text-xs overflow-auto max-h-96">
                  {JSON.stringify(result, null, 2)}
                </pre>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
