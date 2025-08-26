import { NextResponse } from 'next/server';

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

export async function DELETE(request: Request, { params }: { params: Promise<{ post_id: string }> }): Promise<NextResponse> {
  try {
    const { post_id: postId } = await params;
    if (!postId) return createErrorResponse('post_id is required in URL', 400);

    // Extract tokens from incoming request headers
    const cookieHeader = request.headers.get('cookie') || '';
    const headerAuth = request.headers.get('authorization') || request.headers.get('Authorization') || '';
    const cookieMap = Object.fromEntries(
      cookieHeader.split(';').map((p) => p.trim()).filter(Boolean).map((p) => {
        const i = p.indexOf('=');
        return i === -1 ? [p, ''] : [decodeURIComponent(p.slice(0, i)), decodeURIComponent(p.slice(i + 1))];
      })
    ) as Record<string, string>;
    const cookieAccess = cookieMap['access_token']; // primary
    const cookieAuth = cookieMap['auth_token'];     // legacy
    const bearer = headerAuth.startsWith('Bearer ') ? headerAuth.substring(7) : undefined;
    const authToken = bearer || cookieAccess || cookieAuth;
    if (!authToken) return createErrorResponse('Authentication required', 401);

    const resp = await fetch(`${API_BASE_URL}/api/videos/${encodeURIComponent(postId)}`, {
      method: 'DELETE',
      headers: {
        Authorization: `Bearer ${authToken}`,
        'Content-Type': 'application/json',
        // forward cookies as well in case backend reads them
        ...(cookieHeader ? { Cookie: cookieHeader } : {}),
      },
      credentials: 'include',
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      return createErrorResponse(err.detail || 'Failed to delete video', resp.status);
    }

    const data = await resp.json();
    return NextResponse.json(data);
  } catch (error) {
    return createErrorResponse('Internal server error', 500, error instanceof Error ? error.message : 'Unknown error');
  }
}
