import { NextResponse } from 'next/server';

interface BackendVideoItem {
  id?: string | number;
  title?: string;
  video_url?: string;
  thumbnail_url?: string;
  url?: string;
  thumbnail?: string;
  duration?: number;
  created_at?: string;
  status?: 'processing' | 'completed' | 'failed' | string;
  user_id?: number | string;
  user_name?: string | null;
  tags?: unknown;
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
  tags?: string[];
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
      u.pathname = u.pathname.replace('/videos/../app/', '/videos/');
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
    const url = new URL(request.url);
    const topic = url.searchParams.get('topic') || '';
    const tagsParam = url.searchParams.get('tags') || '';
    const limitSimilar = url.searchParams.get('limit_similar') || '12';
    const limitOthers = url.searchParams.get('limit_others') || '12';
    const cookieHeader = request.headers.get('cookie') ?? undefined;
    const authHeader = request.headers.get('authorization') ?? undefined;

    const qs = new URLSearchParams({ topic, limit_similar: limitSimilar, limit_others: limitOthers });
    if (tagsParam) qs.set('tags', tagsParam);
    const resp = await fetch(`${API_BASE_URL}/api/videos/learn-feed?` + qs.toString(),
      {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
          ...(cookieHeader ? { 'Cookie': cookieHeader } : {}),
          ...(authHeader ? { 'Authorization': authHeader } : {}),
        },
        cache: 'no-store',
      }
    );

    if (!resp.ok) {
      const errorData = await resp.json().catch(() => ({}));
      return createErrorResponse(errorData.detail || 'Failed to fetch learn feed', resp.status);
    }

    const data = await resp.json();
    const toFrontend = (arr: BackendVideoItem[]): FrontendVideoItem[] => {
      if (!Array.isArray(arr)) return [];
      return arr
        .map((v) => {
          const videoUrl = absoluteUrl(v.video_url ?? v.url);
          const thumbnailUrl = absoluteUrl(v.thumbnail_url ?? v.thumbnail);
          const status: FrontendVideoItem['status'] = isValidStatus(v.status) ? v.status : 'completed';
          const tags = Array.isArray(v.tags) ? v.tags.map(String) : undefined;
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
            tags,
          };
        })
        .filter((v) => !!v.videoUrl);
    };

    const similar = toFrontend(data?.similar || []);
    // Exclude any items already in 'similar', sort by most recent, cap to 18
    const similarIds = new Set(similar.map((v) => v.id));
    let others = toFrontend(data?.others || [])
      .filter((v) => !similarIds.has(v.id))
      .sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
    // Enforce 18 max by default; if caller requested a different limit, backend already applied it
    others = others.slice(0, 18);
    const queryTags: string[] = Array.isArray(data?.query_tags) ? data.query_tags.map(String) : [];

    return NextResponse.json({ similar, others, queryTags });
  } catch (error) {
    return createErrorResponse('Internal server error', 500, error instanceof Error ? error.message : 'Unknown error');
  }
}
