import { NextResponse } from 'next/server';
import { Question, VideoRequest, VideoResponse } from '@/types/video';

// Helper function to get backend URL
function getBackendUrl(): string {
  // Prefer server-only BACKEND_URL, then fall back to NEXT_PUBLIC_BACKEND_URL
  const serverUrl = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL;
  if (serverUrl) return serverUrl.replace(/\/$/, '');
  // Default to local development URL
  return 'http://localhost:8000';
}

interface FormattedQuestion extends Omit<Question, 'opts'> {
  opts: Record<string, string>;
}

export async function POST(request: Request) {
  try {
    const { topic, questions, answers } = await request.json() as VideoRequest;
    
    // Format the answers to match backend expectations
    const formattedAnswers: Record<string, string> = {};
    Object.entries(answers).forEach(([questionIndex, rawVal]) => {
      const val = String(rawVal).trim().toLowerCase();
      let letter = '';
      // Cases: numeric index ("0"), option key ("a", "b", "c"), or prefixed like "option-0"
      const numericMatch = val.match(/^(?:option[-_])?(\d+)$/);
      if (numericMatch) {
        const idx = parseInt(numericMatch[1], 10);
        if (!Number.isNaN(idx) && idx >= 0 && idx < 26) letter = String.fromCharCode(97 + idx);
      } else if (/^[a-z]$/.test(val)) {
        letter = val;
      } else if (/^[a-z]\)/.test(val)) {
        // e.g., "a) Some text"
        letter = val[0];
      }
      formattedAnswers[questionIndex] = letter || val[0] || '';
    });

    // Format questions to ensure they match the expected format
    const formattedQuestions: FormattedQuestion[] = questions.map((q) => {
      const formattedOpts: Record<string, string> = {};
      Object.entries(q.opts || {}).forEach(([key, value]) => {
        formattedOpts[key.toString().toUpperCase()] = String(value);
      });
      
      return {
        ...q,
        a: q.a ? q.a.toString().toLowerCase() : '',
        opts: formattedOpts
      };
    });

    const backendUrl = getBackendUrl();
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 600000); // 10 minute timeout
    
    try {
      const base = backendUrl.replace(/\/$/, '');
      // Prefer async job to avoid timeouts
      const asyncUrl = `${base}/generate-video-async`;
      const incomingCookie = request.headers.get('cookie') || '';
      const incomingAuth = request.headers.get('authorization') || '';
      const commonHeaders: Record<string, string> = {
        'Content-Type': 'application/json',
        ...(incomingCookie ? { Cookie: incomingCookie } : {}),
        ...(incomingAuth ? { Authorization: incomingAuth } : {}),
      };

      // Attempt async first
      let response = await fetch(asyncUrl, {
        method: 'POST',
        headers: commonHeaders,
        body: JSON.stringify({
          topic,
          questions: formattedQuestions,
          answers: formattedAnswers
        }),
        signal: controller.signal
      });

      // If async endpoint not available, fallback to sync
      if (response.status === 404) {
        const targetUrl = `${base}/generate-video`;
        response = await fetch(targetUrl, {
          method: 'POST',
          headers: commonHeaders,
          body: JSON.stringify({
            topic,
            questions: formattedQuestions,
            answers: formattedAnswers
          }),
          signal: controller.signal
        });
      }

      
      clearTimeout(timeoutId);
      
      if (!response.ok) {
        let details: unknown = undefined;
        try {
          details = await response.json();
        } catch {
          details = await response.text();
        }
        console.error('Backend error status:', response.status);
        console.error('Backend error response:', details);
        return NextResponse.json(
          { error: 'Failed to generate video', details },
          { status: response.status }
        );
      }
      
      const data = await response.json() as VideoResponse;
      
      // Ensure the video URLs are absolute if they're not already
      if (data.videos && Array.isArray(data.videos)) {
        data.videos = data.videos.map((video) => {
          const absoluteUrl = video.url.startsWith('http') ? video.url : `${backendUrl}${video.url}`;
          // Return proxied URL for same-origin playback
          const proxied = `/api/proxy-video?url=${encodeURIComponent(absoluteUrl)}`;
          return { ...video, url: proxied };
        });
      }
      
      console.log('Backend response data:', data);
      return NextResponse.json(data);
      
    } catch (error: unknown) {
      clearTimeout(timeoutId);
      
      if (error instanceof Error) {
        if (error.name === 'AbortError') {
          console.error('Request timed out after 10 minutes');
          return NextResponse.json(
            { 
              error: 'Video generation is taking longer than expected', 
              details: 'The server is still processing your request. Please try again in a few minutes.' 
            },
            { status: 504 }
          );
        }
        // Network or other fetch errors
        return NextResponse.json(
          { error: 'Failed to generate video', details: error.message },
          { status: 502 }
        );
      }
      
      throw new Error('An unknown error occurred');
    }
  } catch (error: unknown) {
    console.error('Video generation error:', error);
    const errorMessage = error instanceof Error ? error.message : 'Unknown error occurred';
    
    return NextResponse.json(
      { 
        error: 'Failed to generate video', 
        details: errorMessage
      },
      { status: 500 }
    );
  }
}