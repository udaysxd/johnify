import { NextResponse } from 'next/server';
import { Question, VideoRequest } from '@/types/video';
import { Agent, setGlobalDispatcher } from 'undici';

// Ensure Node.js runtime (not Edge) so Undici settings apply
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// Configure a long-lived Undici Agent to disable default timeouts
const longLivedAgent = new Agent({
  headersTimeout: 0,
  bodyTimeout: 0,
});
setGlobalDispatcher(longLivedAgent);

// Note: We rely on Node's global fetch (Undici under the hood in Node 18+).
// We avoid importing 'undici' directly to prevent module resolution issues in builds.

// Helper function to get backend URL
function getBackendUrl(): string {
  // Prefer server-side BACKEND_URL, then NEXT_PUBLIC_BACKEND_URL
  const raw = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL;
  if (raw && typeof raw === 'string') {
    return raw.replace(/\/$/, '');
  }
  // Only fall back to localhost during development
  if (process.env.NODE_ENV === 'development') {
    return 'http://localhost:8000';
  }
  throw new Error('Backend URL not configured');
}

interface FormattedQuestion extends Omit<Question, 'opts'> {
  opts: Record<string, string>;
}

type VideoItem = { url?: string; [key: string]: unknown };
type MaybeVideos = { videos?: VideoItem[] };

function hasVideos(v: unknown): v is MaybeVideos {
  if (typeof v !== 'object' || v === null) return false;
  const videos = (v as { videos?: unknown }).videos;
  return Array.isArray(videos);
}

function normalizeError(e: unknown): { name: string; message: string } {
  if (e && typeof e === 'object') {
    const rec = e as Record<string, unknown>;
    const name = typeof rec.name === 'string' ? rec.name : '';
    const message = typeof rec.message === 'string' ? rec.message : String(e);
    return { name, message };
  }
  return { name: '', message: String(e) };
}

export async function POST(request: Request) {
  try {
    const { topic, questions, answers } = await request.json() as VideoRequest;
    
    // Format the answers to match backend expectations
    const formattedAnswers: Record<string, string> = {};
    Object.entries(answers).forEach(([questionIndex, answerIndex]) => {
      // Convert numeric answer index to letter (0->'a', 1->'b', etc.)
      const letterAnswer = String.fromCharCode(97 + parseInt(answerIndex, 10));
      formattedAnswers[questionIndex] = letterAnswer;
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
    console.log('Using BACKEND_URL for quiz kickoff:', backendUrl);
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 1100_000); // ~18m20s, below Cloud Run 1200s
    
    try {
      // Forward incoming auth/cookie headers to backend
      const incomingCookie = request.headers.get('cookie') || '';
      const incomingAuth = request.headers.get('authorization') || '';

      // Kick off async job via global fetch with AbortController timeout
      async function kickoffOnce() {
        const resp = await fetch(`${backendUrl}/generate-video/start`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(incomingCookie ? { Cookie: incomingCookie } : {}),
            ...(incomingAuth ? { Authorization: incomingAuth } : {}),
          },
          body: JSON.stringify({ topic, questions: formattedQuestions, answers: formattedAnswers }),
          signal: controller.signal,
          // cache no-store not necessary server-to-server
        });
        const text = await resp.text();
        if (!resp.ok) {
          console.error('Backend error status:', resp.status);
          console.error('Backend error response:', text);
          throw new Error(`Backend error: ${resp.status} - ${text}`);
        }
        try {
          return text ? JSON.parse(text) : {};
        } catch (e) {
          console.error('Failed to parse backend JSON:', text);
          throw e;
        }
      }

      let data: unknown;
      try {
        data = await kickoffOnce();
      } catch (e: unknown) {
        // Retry once on HeadersTimeoutError
        const { name, message } = normalizeError(e);
        if (name === 'HeadersTimeoutError' || /UND_ERR_HEADERS_TIMEOUT/i.test(message)) {
          console.warn('Retrying kickoff after HeadersTimeoutError...');
          data = await kickoffOnce();
        } else {
          throw e;
        }
      } finally {
        clearTimeout(timeoutId);
      }
      
      // If backend returned a synchronous result (rare), ensure URLs are absolute
      if (hasVideos(data)) {
        data.videos = data.videos!.map((video: VideoItem) => ({
          ...video,
          url: typeof video.url === 'string' && video.url.startsWith('http') ? video.url : `${backendUrl}${video.url ?? ''}`
        }));
      }
      
      console.log('Backend response data:', data);
      const res = NextResponse.json(data as object);
      res.headers.set('X-Route-Version', 'quiz-generate-video:kickoff-v2');
      return res;
      
    } catch (error: unknown) {
      clearTimeout(timeoutId);
      
      if (error instanceof Error) {
        if (error.name === 'AbortError') {
          console.error('Request timed out before Cloud Run limit');
          return NextResponse.json(
            { 
              message: 'Video generation is taking longer than expected', 
              details: 'The server is still processing your request. Please try again in a few minutes.' 
            },
            { status: 504 }
          );
        }
        console.error('Undici/Fetch error details:', {
          name: error.name,
          message: error.message,
          stack: error.stack,
        });
        throw error; // Re-throw other errors to be caught by the outer catch
      }
      
      throw new Error('An unknown error occurred');
    }
  } catch (error: unknown) {
    console.error('Video generation error:', error);
    const errorMessage = error instanceof Error ? error.message : 'Unknown error occurred';
    
    return NextResponse.json(
      { 
        message: 'Failed to generate video', 
        details: errorMessage
      },
      { status: 500 }
    );
  }
}