import { NextResponse } from 'next/server';

interface BackendVideoItem {
  id?: string | number;
  title?: string;
  video_url?: string;
  thumbnail_url?: string;
  url?: string;        // fallback
  thumbnail?: string;  // fallback
  duration?: number;
  created_at?: string;
  status?: 'processing' | 'completed' | 'failed' | string;
  user_id?: number | string;
  user_name?: string | null;
  [key: string]: unknown;
}

interface FrontendVideoItem {
  id: string;
  title: string;
  videoUrl: string;
  thumbnailUrl: string;
  duration?: number;
  createdAt: string;
  status: 'processing' | 'completed' | 'failed';
  userId?: string;
  userName?: string;
}

const isProduction = process.env.NODE_ENV === 'production';
const API_BASE_URL = isProduction
  ? (process.env.BACKEND_URL || 'https://johnify-backend-873155673176.us-central1.run.app')
  : (process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000');

function absoluteUrl(url: string | undefined): string {
  if (!url) return '';
  if (url.startsWith('http')) {
    try {
      const u = new URL(url);
      // Fix known path quirk but do not rewrite host for valid absolute URLs
      u.pathname = u.pathname.replace('/videos/../app/', '/videos/');
      // Only normalize localhost origins to the backend API origin
      if (u.hostname === 'localhost' || u.hostname === '127.0.0.1') {
        const api = new URL(API_BASE_URL);
        u.protocol = api.protocol;
        u.host = api.host;
      }
      return u.toString();
    } catch {
      return url;
    }
  }
  // Relative path from backend
  return `${API_BASE_URL}${url.startsWith('/') ? '' : '/'}${url}`;
}

function createErrorResponse(message: string, status: number, details?: unknown): NextResponse {
  console.error(`[API Error] ${message}`, details || '');
  const body: { error: string; details?: unknown } = { error: message };
  if (details !== undefined) body.details = details;
  return new NextResponse(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

function isValidStatus(s: unknown): s is 'processing' | 'completed' | 'failed' {
  return s === 'processing' || s === 'completed' || s === 'failed';
}

export async function GET(request: Request): Promise<NextResponse> {
  try {
    const cookieHeader = request.headers.get('cookie') ?? undefined;
    const authHeader = request.headers.get('authorization') ?? undefined;
    const resp = await fetch(`${API_BASE_URL}/api/videos/feed`, {
      method: 'GET',
      // Forward cookies and auth so backend can personalize/exclude current user's posts
      headers: {
        'Content-Type': 'application/json',
        ...(cookieHeader ? { 'Cookie': cookieHeader } : {}),
        ...(authHeader ? { 'Authorization': authHeader } : {}),
      },
      cache: 'no-store',
    });

    if (!resp.ok) {
      const errorData = await resp.json().catch(() => ({}));
      return createErrorResponse(errorData.detail || 'Failed to fetch feed', resp.status);
    }

    const data = (await resp.json()) as BackendVideoItem[];

    const videos: FrontendVideoItem[] = Array.isArray(data)
      ? data
          .map((v) => {
            const videoUrl = absoluteUrl(v.video_url ?? v.url);
            const thumbnailUrl = absoluteUrl(v.thumbnail_url ?? v.thumbnail);
            const status: FrontendVideoItem['status'] = isValidStatus(v.status) ? v.status : 'completed';
            return {
              id: String(v.id ?? ''),
              title: v.title || 'Untitled Video',
              videoUrl,
              thumbnailUrl,
              duration: typeof v.duration === 'number' ? v.duration : undefined,
              createdAt: v.created_at || new Date().toISOString(),
              status,
              userId: v.user_id !== undefined ? String(v.user_id) : undefined,
              userName: typeof v.user_name === 'string' ? v.user_name : undefined,
            };
          })
          .filter((v) => !!v.videoUrl)
      : [];

    return NextResponse.json(videos);
  } catch (error) {
    return createErrorResponse('Internal server error', 500, error instanceof Error ? error.message : 'Unknown error');
  }
}
