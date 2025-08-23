import { NextResponse } from 'next/server';
import { Question, VideoRequest } from '@/types/video';
import { Agent, setGlobalDispatcher } from 'undici';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const longLivedAgent = new Agent({ headersTimeout: 0, bodyTimeout: 0 });
setGlobalDispatcher(longLivedAgent);

function getBackendUrl(): string {
  const raw = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL;
  if (raw && typeof raw === 'string') return raw.replace(/\/$/, '');
  if (process.env.NODE_ENV === 'development') return 'http://localhost:8000';
  throw new Error('Backend URL not configured');
}

interface FormattedQuestion extends Omit<Question, 'opts'> { opts: Record<string, string>; }

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

    const formattedAnswers: Record<string, string> = {};
    Object.entries(answers).forEach(([questionIndex, answerIndex]) => {
      const letterAnswer = String.fromCharCode(97 + parseInt(answerIndex, 10));
      formattedAnswers[questionIndex] = letterAnswer;
    });

    const formattedQuestions: FormattedQuestion[] = questions.map((q) => {
      const formattedOpts: Record<string, string> = {};
      Object.entries(q.opts || {}).forEach(([key, value]) => {
        formattedOpts[key.toString().toUpperCase()] = String(value);
      });
      return { ...q, a: q.a ? q.a.toString().toLowerCase() : '', opts: formattedOpts };
    });

    const backendUrl = getBackendUrl();
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 1100_000);

    try {
      const incomingCookie = request.headers.get('cookie') || '';
      const incomingAuth = request.headers.get('authorization') || '';

      async function kickoffOnce() {
        const resp = await fetch(`${backendUrl}/api/tutor/generate-video/start`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(incomingCookie ? { Cookie: incomingCookie } : {}),
            ...(incomingAuth ? { Authorization: incomingAuth } : {}),
          },
          body: JSON.stringify({ topic, questions: formattedQuestions, answers: formattedAnswers }),
          signal: controller.signal,
        });
        const text = await resp.text();
        if (!resp.ok) {
          throw new Error(`Backend error: ${resp.status} - ${text}`);
        }
        try { return text ? JSON.parse(text) : {}; } catch (e) { throw e; }
      }

      let data: unknown;
      try {
        data = await kickoffOnce();
      } catch (e: unknown) {
        const { name, message } = normalizeError(e);
        if (name === 'HeadersTimeoutError' || /UND_ERR_HEADERS_TIMEOUT/i.test(message)) {
          data = await kickoffOnce();
        } else {
          throw e;
        }
      } finally {
        clearTimeout(timeoutId);
      }

      if (hasVideos(data)) {
        data.videos = data.videos!.map((video: VideoItem) => ({
          ...video,
          url: typeof video.url === 'string' && video.url.startsWith('http') ? video.url : `${backendUrl}${video.url ?? ''}`
        }));
      }

      const res = NextResponse.json(data as object);
      res.headers.set('X-Route-Version', 'tutor-generate-video:kickoff-v1');
      return res;

    } catch (error: unknown) {
      clearTimeout(timeoutId);
      if (error instanceof Error) {
        if (error.name === 'AbortError') {
          return NextResponse.json({ message: 'Video generation is taking longer than expected', details: 'The server is still processing your request. Please try again in a few minutes.' }, { status: 504 });
        }
        throw error;
      }
      throw new Error('An unknown error occurred');
    }
  } catch (error: unknown) {
    const errorMessage = error instanceof Error ? error.message : 'Unknown error occurred';
    return NextResponse.json({ message: 'Failed to generate video', details: errorMessage }, { status: 500 });
  }
}
