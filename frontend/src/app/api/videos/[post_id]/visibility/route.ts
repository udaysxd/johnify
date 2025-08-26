import { NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const isProduction = process.env.NODE_ENV === 'production';
const API_BASE_URL = isProduction
  ? (process.env.BACKEND_URL || 'https://johnify-backend-873155673176.us-central1.run.app')
  : (process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000');

function createErrorResponse(message: string, status: number, details?: unknown): NextResponse {
  console.error(`[API Error] ${message}`, details || '');
  const body: { error: string; details?: unknown } = { error: message };
  if (details !== undefined) body.details = details;
  return new NextResponse(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

export async function PATCH(request: Request): Promise<NextResponse> {
  try {
    // Derive post_id from URL: /api/videos/{post_id}/visibility
    const url = new URL(request.url);
    const parts = url.pathname.split('/').filter(Boolean);
    const videosIdx = parts.indexOf('videos');
    const postId = videosIdx >= 0 && parts[videosIdx + 1] ? parts[videosIdx + 1] : undefined;
    if (!postId) return createErrorResponse('post_id is required in URL', 400);

    const body = await request.json().catch(() => undefined) as { public?: boolean } | undefined;
    if (!body || typeof body.public !== 'boolean') {
      return createErrorResponse('Body must be { public: boolean }', 400);
    }

    const cookieStore = await cookies();
    const cookieAccess = cookieStore.get('access_token')?.value; // primary used by app
    const cookieAuth = cookieStore.get('auth_token')?.value;     // legacy fallback
    const headerAuth = request.headers.get('authorization') || request.headers.get('Authorization');
    const bearer = headerAuth?.startsWith('Bearer ') ? headerAuth.substring(7) : undefined;
    const authToken = bearer || cookieAccess || cookieAuth;
    if (!authToken) return createErrorResponse('Authentication required', 401);

    const resp = await fetch(`${API_BASE_URL}/api/videos/${encodeURIComponent(postId)}/visibility`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${authToken}`,
      },
      body: JSON.stringify({ public: body.public }),
      credentials: 'include',
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      return createErrorResponse(err.detail || 'Failed to update visibility', resp.status);
    }

    const data = await resp.json();
    return NextResponse.json(data);
  } catch (error) {
    return createErrorResponse('Internal server error', 500, error instanceof Error ? error.message : 'Unknown error');
  }
}
