import { NextResponse } from 'next/server';

function getBackendUrl() {
  const isProduction = process.env.NODE_ENV === 'production';
  const env = process.env.NEXT_PUBLIC_BACKEND_URL || process.env.BACKEND_URL;
  if (env && env.trim()) return env;
  return isProduction ? 'https://johnify-backend-873155673176.us-central1.run.app' : 'http://localhost:8000';
}

export async function PUT(req: Request, { params }: { params: Promise<{ commentId: string }> }) {
  try {
    const backend = getBackendUrl();
    const { commentId } = await params;
    const cookieHeader = req.headers.get('cookie') || '';
    const authHeader = req.headers.get('authorization') || req.headers.get('Authorization') || '';
    const resp = await fetch(`${backend}/api/videos/comments/${encodeURIComponent(commentId)}/like`, {
      method: 'PUT',
      headers: {
        'Accept': 'application/json',
        ...(authHeader ? { Authorization: authHeader } : {}),
        ...(cookieHeader ? { Cookie: cookieHeader } : {}),
      },
      credentials: 'include' as RequestCredentials,
    });
    const ct = resp.headers.get('content-type') || '';
    if (!resp.ok) {
      const body = ct.includes('application/json') ? await resp.json().catch(() => ({} as Record<string, unknown>)) : await resp.text().catch(() => '');
      if (typeof body === 'string') {
        return NextResponse.json({ message: body || 'Failed to like comment' }, { status: resp.status });
      }
      const msg = typeof body.message === 'string' ? body.message : (typeof body.detail === 'string' ? body.detail : 'Failed to like comment');
      return NextResponse.json({ message: msg }, { status: resp.status });
    }
    const data = await resp.json().catch(() => ({}));
    return NextResponse.json(data);
  } catch (e) {
    return NextResponse.json({ message: 'Internal server error' }, { status: 500 });
  }
}

export async function DELETE(req: Request, { params }: { params: Promise<{ commentId: string }> }) {
  try {
    const backend = getBackendUrl();
    const { commentId } = await params;
    const cookieHeader = req.headers.get('cookie') || '';
    const authHeader = req.headers.get('authorization') || req.headers.get('Authorization') || '';
    const resp = await fetch(`${backend}/api/videos/comments/${encodeURIComponent(commentId)}/like`, {
      method: 'DELETE',
      headers: {
        'Accept': 'application/json',
        ...(authHeader ? { Authorization: authHeader } : {}),
        ...(cookieHeader ? { Cookie: cookieHeader } : {}),
      },
      credentials: 'include' as RequestCredentials,
    });
    const ct = resp.headers.get('content-type') || '';
    if (!resp.ok) {
      const body = ct.includes('application/json') ? await resp.json().catch(() => ({} as Record<string, unknown>)) : await resp.text().catch(() => '');
      if (typeof body === 'string') {
        return NextResponse.json({ message: body || 'Failed to unlike comment' }, { status: resp.status });
      }
      const msg = typeof body.message === 'string' ? body.message : (typeof body.detail === 'string' ? body.detail : 'Failed to unlike comment');
      return NextResponse.json({ message: msg }, { status: resp.status });
    }
    const data = await resp.json().catch(() => ({}));
    return NextResponse.json(data);
  } catch (e) {
    return NextResponse.json({ message: 'Internal server error' }, { status: 500 });
  }
}

