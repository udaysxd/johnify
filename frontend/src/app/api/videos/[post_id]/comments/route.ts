import { NextResponse } from 'next/server';

function getBackendUrl() {
  return process.env.NEXT_PUBLIC_BACKEND_URL || process.env.BACKEND_URL || 'http://localhost:8000';
}

export async function GET(_req: Request, { params }: { params: Promise<{ post_id: string }> }) {
  try {
    const backend = getBackendUrl();
    const { post_id } = await params;
    const resp = await fetch(`${backend}/api/videos/${encodeURIComponent(post_id)}/comments`, {
      method: 'GET',
      headers: { 'Accept': 'application/json' },
      cache: 'no-store',
    });
    const ct = resp.headers.get('content-type') || '';
    if (!resp.ok) {
      const body = ct.includes('application/json') ? await resp.json().catch(() => ({} as Record<string, unknown>)) : await resp.text().catch(() => '');
      if (typeof body === 'string') {
        return NextResponse.json({ message: body || 'Failed to fetch comments' }, { status: resp.status });
      }
      const msg = typeof body.message === 'string' ? body.message : (typeof body.detail === 'string' ? body.detail : 'Failed to fetch comments');
      return NextResponse.json({ message: msg }, { status: resp.status });
    }
    const data = ct.includes('application/json') ? await resp.json() : await resp.text();
    return NextResponse.json(typeof data === 'string' ? { message: data } : data);
  } catch (e) {
    return NextResponse.json({ message: 'Internal server error' }, { status: 500 });
  }
}

export async function POST(req: Request, { params }: { params: Promise<{ post_id: string }> }) {
  try {
    const backend = getBackendUrl();
    const body = await req.json().catch(() => ({}));
    const cookieHeader = req.headers.get('cookie') || '';
    const authHeader = req.headers.get('authorization') || req.headers.get('Authorization') || '';
    const { post_id } = await params;
    const resp = await fetch(`${backend}/api/videos/${encodeURIComponent(post_id)}/comments`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        ...(authHeader ? { Authorization: authHeader } : {}),
        ...(cookieHeader ? { Cookie: cookieHeader } : {}),
      },
      credentials: 'include' as RequestCredentials,
      body: JSON.stringify(body || {}),
    });
    const ct = resp.headers.get('content-type') || '';
    if (!resp.ok) {
      const bodyErr = ct.includes('application/json') ? await resp.json().catch(() => ({} as Record<string, unknown>)) : await resp.text().catch(() => '');
      if (typeof bodyErr === 'string') {
        return NextResponse.json({ message: bodyErr || 'Failed to add comment' }, { status: resp.status });
      }
      const msg = typeof bodyErr.message === 'string' ? bodyErr.message : (typeof bodyErr.detail === 'string' ? bodyErr.detail : 'Failed to add comment');
      return NextResponse.json({ message: msg }, { status: resp.status });
    }
    const data = await resp.json().catch(() => ({}));
    return NextResponse.json(data);
  } catch (e) {
    return NextResponse.json({ message: 'Internal server error' }, { status: 500 });
  }
}

