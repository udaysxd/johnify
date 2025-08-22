import { NextResponse } from 'next/server';
import { cookies } from 'next/headers';

interface BackendVideoItem {
  id?: string | number;
  title?: string;
  video_url?: string;
  thumbnail_url?: string;
  url?: string;        // fallback name used by some handlers
  thumbnail?: string;  // fallback name used by some handlers
  duration?: number;
  created_at?: string;
  status?: 'processing' | 'completed' | 'failed' | string;
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
}

const isProduction = process.env.NODE_ENV === 'production';
const API_BASE_URL = isProduction
  ? (process.env.BACKEND_URL || 'https://johnify-backend-873155673176.us-central1.run.app')
  : (process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000');

function absoluteUrl(url: string | undefined): string {
  if (!url) return '';
  // If backend returned an absolute URL, normalize its origin and path quirks
  if (url.startsWith('http')) {
    try {
      const u = new URL(url);
      const api = new URL(API_BASE_URL);
      // Replace localhost origin with backend API origin
      u.protocol = api.protocol;
      u.host = api.host;
      // Collapse any `/videos/../app/` to `/videos/`
      u.pathname = u.pathname.replace('/videos/../app/', '/videos/');
      return u.toString();
    } catch {
      return url;
    }
  }
  // For relative paths, keep existing join behavior
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
    const cookieStore = await cookies();
    const cookieAccess = cookieStore.get('access_token')?.value; // primary used by app
    const cookieAuth = cookieStore.get('auth_token')?.value;     // legacy fallback
    const headerAuth = request.headers.get('authorization') || request.headers.get('Authorization');
    const bearer = headerAuth?.startsWith('Bearer ') ? headerAuth.substring(7) : undefined;
    const authToken = bearer || cookieAccess || cookieAuth;
    if (!authToken) return createErrorResponse('Authentication required', 401);

    const resp = await fetch(`${API_BASE_URL}/api/videos/my-videos`, {
      method: 'GET',
      headers: {
        Authorization: `Bearer ${authToken}`,
        'Content-Type': 'application/json',
      },
      credentials: 'include',
      cache: 'no-store',
    });

    if (!resp.ok) {
      const errorData = await resp.json().catch(() => ({}));
      return createErrorResponse(errorData.detail || 'Failed to fetch videos', resp.status);
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
            };
          })
          // Filter out entries with no video URL
          .filter((v) => !!v.videoUrl)
      : [];

    return NextResponse.json(videos);
  } catch (error) {
    return createErrorResponse('Internal server error', 500, error instanceof Error ? error.message : 'Unknown error');
  }
}
