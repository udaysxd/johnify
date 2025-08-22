'use client';

import { useState, useEffect, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';

// Response shape from /api/learn
interface LearnResponse {
  status?: string;
  video_url?: string;
  message?: string;
  error?: string;
  details?: string;
  detail?: string;
}

function LearnPageContent() {
  const { user, loading: isAuthLoading } = useAuth();
  const isAuthenticated = !!user;
  const [topic, setTopic] = useState('');
  const complexity = 3; // Fixed intermediate complexity level
  const [isLoading, setIsLoading] = useState(false);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();
  const searchParams = useSearchParams();

  // Prefill topic from query string
  useEffect(() => {
    const q = searchParams.get('topic');
    if (q && !topic) {
      setTopic(q);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  // Redirect to login if not authenticated
  useEffect(() => {
    if (!isAuthLoading && !isAuthenticated) {
      router.push('/auth/signin');
    }
  }, [isAuthenticated, isAuthLoading, router]);

  const generateVideo = async (requestedTopic: string) => {
    const trimmed = requestedTopic.trim();
    if (!trimmed) return;

    setIsLoading(true);
    setError(null);

    try {
      const userEmail = user?.user_email;
      const response = await fetch('/api/learn', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: JSON.stringify({
          topic: trimmed,
          complexity_level: complexity,
          user_email: userEmail || 'anonymous@example.com',
        }),
      });

      const contentType = response.headers.get('content-type') || '';
      let data: LearnResponse | null = null;
      if (contentType.includes('application/json')) {
        data = await response.json().catch(() => null);
      } else {
        // Try to parse as text then JSON; otherwise, construct an informative error
        const textBody = await response.text().catch(() => '');
        try {
          data = JSON.parse(textBody) as LearnResponse;
        } catch {
          if (!response.ok) {
            throw new Error(
              `Backend error (${response.status}): ${response.statusText || 'Unknown'}\n` +
              `${textBody?.slice(0, 300) || 'No body'}`
            );
          } else {
            throw new Error(
              'Received non-JSON success body from server. Please try again later.'
            );
          }
        }
      }
      if (!response.ok) {
        throw new Error(
          data?.detail || data?.message || data?.error || 'Failed to generate learning video'
        );
      }

      if (!data || !data.video_url) {
        console.error('No video_url in response:', data);
        throw new Error('Received invalid response from server: missing video URL');
      }

      const videoPath = data.video_url;
      if (typeof videoPath !== 'string') {
        console.error('Invalid video_url format:', videoPath);
        throw new Error('Received invalid video URL format from server');
      }

      setVideoUrl(videoPath);
    } catch (err) {
      console.error('Error generating learning video:', err);
      setError(err instanceof Error ? err.message : 'An unknown error occurred');
    } finally {
      setIsLoading(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!topic.trim()) return;
    await generateVideo(topic);
  };

  // Autostart if ?autostart=1 and topic present
  useEffect(() => {
    if (isAuthLoading) return;
    if (!isAuthenticated) return;
    const auto = searchParams.get('autostart');
    const q = (searchParams.get('topic') || topic || '').trim();
    if (auto && q && !isLoading && !videoUrl) {
      generateVideo(q);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthenticated, isAuthLoading, searchParams, topic]);

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="py-12 px-4 sm:px-6 lg:px-8">
        <div className="max-w-3xl mx-auto">
          <div className="text-center mb-8">
            <h1 className="text-3xl font-bold text-gray-900 mb-2">Learn Something New</h1>
            <p className="text-gray-600">Enter a topic and we&apos;ll generate an educational video for you</p>
          </div>

          {isAuthLoading ? (
            <div className="min-h-[200px] flex items-center justify-center">
              <div className="text-center">
                <div className="w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto"></div>
                <p className="mt-4 text-gray-600">Loading...</p>
              </div>
            </div>
          ) : !videoUrl ? (
            <div className="bg-white shadow rounded-lg p-6">
              <form onSubmit={handleSubmit} className="space-y-6">
                <div>
                  <label htmlFor="topic" className="block text-sm font-medium text-gray-700 mb-1">
                    What would you like to learn about?
                  </label>
                  <input
                    type="text"
                    id="topic"
                    value={topic}
                    onChange={(e) => setTopic(e.target.value)}
                    className="w-full px-4 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-indigo-500 focus:border-indigo-500"
                    placeholder="e.g., Quantum Computing, Ancient Rome, Machine Learning"
                    disabled={isLoading}
                    required
                  />
                </div>

                <div>
                  <button
                    type="submit"
                    disabled={isLoading || !topic.trim()}
                    className={`w-full flex justify-center py-3 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white ${
                      isLoading || !topic.trim()
                        ? 'bg-indigo-300 cursor-not-allowed'
                        : 'bg-indigo-600 hover:bg-indigo-700'
                    } focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500`}
                  >
                    {isLoading ? 'Generating Video...' : 'Generate Learning Video'}
                  </button>
                </div>
              </form>
            
            {error && (
              <div className="mt-4 p-3 bg-red-50 text-red-700 rounded-md text-sm">
                {error}
              </div>
            )}
          </div>
        ) : (
          <div className="bg-white shadow rounded-lg p-6 text-center">
            <h2 className="text-xl font-semibold mb-4">Your Learning Video is Ready!</h2>
            <div className="aspect-w-16 aspect-h-9 bg-black rounded-lg overflow-hidden mb-6">
              <video 
                src={videoUrl} 
                controls 
                className="w-full h-full"
                autoPlay
              >
                Your browser does not support the video tag.
              </video>
            </div>
            <div className="space-x-4">
              <button
                onClick={() => setVideoUrl(null)}
                className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500"
              >
                Create Another Video
              </button>
              <button
                onClick={() => router.push('/')}
                className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500"
              >
                Back to Home
              </button>
            </div>
          </div>
        )}
        
        <div className="mt-8 text-center text-sm text-gray-500">
          <p>Note: Video generation may take a few moments. Please be patient.</p>
        </div>
      </div>
      </div>
    </div>
  );
}

export default function LearnPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-gray-50 flex items-center justify-center"><div className="text-gray-600">Loading…</div></div>}>
      <LearnPageContent />
    </Suspense>
  );
}
