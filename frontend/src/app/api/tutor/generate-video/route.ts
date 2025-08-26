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

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
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
    // Keep kickoff under a minute to avoid platform 300s hard timeout and to return promptly
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 60_000);

    try {
      const incomingCookie = request.headers.get('cookie') || '';
      const incomingAuth = request.headers.get('authorization') || '';

      async function kickoffWithRetry() {
        const maxRetries = 5;
        let attempt = 0;
        let lastError: unknown;
        while (attempt <= maxRetries) {
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

          // Success path
          if (resp.ok) {
            const text = await resp.text();
            try { return text ? JSON.parse(text) : {}; } catch (e) { throw e; }
          }

          // Handle 429 with backoff and respect Retry-After if present
          if (resp.status === 429 && attempt < maxRetries) {
            const retryAfter = resp.headers.get('retry-after');
            let delayMs = Math.min(30_000, 1000 * Math.pow(2, attempt)); // 1s,2s,4s,8s,16s, capped at 30s
            if (retryAfter) {
              const seconds = parseInt(retryAfter, 10);
              if (!Number.isNaN(seconds) && seconds > 0) {
                delayMs = Math.min(60_000, seconds * 1000);
              }
            }
            await sleep(delayMs);
            attempt++;
            continue;
          }

          // For transient 5xx, do one quick retry
          if (resp.status >= 500 && resp.status < 600 && attempt < 2) {
            await sleep(1000 * (attempt + 1));
            attempt++;
            continue;
          }

          const text = await resp.text();
          lastError = new Error(`Backend error: ${resp.status} - ${text}`);
          break;
        }
        throw lastError instanceof Error ? lastError : new Error('Backend kickoff failed');
      }

      let data: unknown;
      try {
        data = await kickoffWithRetry();
      } catch (e: unknown) {
        const { name, message } = normalizeError(e);
        if (name === 'HeadersTimeoutError' || /UND_ERR_HEADERS_TIMEOUT/i.test(message)) {
          // One more attempt after a headers-timeout
          data = await kickoffWithRetry();
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
          // Treat long-running kickoff as accepted for async processing so the client can poll
          const res = NextResponse.json({ status: 'processing', message: 'Kickoff accepted; processing continues in background' }, { status: 202 });
          res.headers.set('Retry-After', '10');
          res.headers.set('X-Route-Note', 'kickoff-timeout-treated-as-accepted');
          return res;
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
