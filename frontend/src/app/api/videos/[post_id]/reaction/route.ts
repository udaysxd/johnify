import { NextResponse } from 'next/server';

function getBackendUrl() {
  const isProduction = process.env.NODE_ENV === 'production';
  const envUrl = process.env.NEXT_PUBLIC_BACKEND_URL;
  if (envUrl && envUrl.trim()) return envUrl;
  if (isProduction) return 'https://johnify-backend-873155673176.us-central1.run.app';
  return 'http://localhost:8000';
}

export async function GET(_request: Request, ctx: { params: Promise<{ post_id: string }> }) {
  const { post_id } = await ctx.params;
  const backendUrl = getBackendUrl();
  const url = `${backendUrl}/api/videos/${encodeURIComponent(post_id)}/reactions`;
  try {
    const resp = await fetch(url, { method: 'GET', headers: { 'Accept': 'application/json' }, cache: 'no-store' });
    const ct = resp.headers.get('content-type') || '';
    if (!resp.ok) {
      if (ct.includes('application/json')) {
        const err = await resp.json().catch(() => ({} as { message?: string; detail?: string }));
        return NextResponse.json({ message: err?.message || err?.detail || 'Failed to fetch reactions' }, { status: resp.status });
      }
      const text = await resp.text().catch(() => '');
      return NextResponse.json({ message: text?.slice(0, 500) || 'Failed to fetch reactions' }, { status: resp.status });
    }
    const data = ct.includes('application/json') ? await resp.json() : await resp.text();
    return NextResponse.json(typeof data === 'string' ? { message: data } : data);
  } catch (e) {
    return NextResponse.json({ message: 'Internal server error' }, { status: 500 });
  }
}

export async function PUT(request: Request, ctx: { params: Promise<{ post_id: string }> }) {
  const { post_id } = await ctx.params;
  const backendUrl = getBackendUrl();
  const url = `${backendUrl}/api/videos/${encodeURIComponent(post_id)}/reaction`;
  try {
    const body = await request.json().catch(() => ({}));
    const authHeader = request.headers.get('authorization') || request.headers.get('Authorization') || '';
    const cookieHeader = request.headers.get('cookie') || request.headers.get('Cookie') || '';
    const resp = await fetch(url, {
      method: 'PUT',
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
      if (ct.includes('application/json')) {
        const err = await resp.json().catch(() => ({} as { message?: string; detail?: string }));
        return NextResponse.json({ message: err?.message || err?.detail || 'Failed to set reaction' }, { status: resp.status });
      }
      const text = await resp.text().catch(() => '');
      return NextResponse.json({ message: text?.slice(0, 500) || 'Failed to set reaction' }, { status: resp.status });
    }
    const data = ct.includes('application/json') ? await resp.json() : await resp.text();
    return NextResponse.json(typeof data === 'string' ? { message: data } : data);
  } catch (e) {
    return NextResponse.json({ message: 'Internal server error' }, { status: 500 });
  }
}

export async function DELETE(request: Request, ctx: { params: Promise<{ post_id: string }> }) {
  const { post_id } = await ctx.params;
  const backendUrl = getBackendUrl();
  const url = `${backendUrl}/api/videos/${encodeURIComponent(post_id)}/reaction`;
  try {
    const authHeader = request.headers.get('authorization') || request.headers.get('Authorization') || '';
    const cookieHeader = request.headers.get('cookie') || request.headers.get('Cookie') || '';
    const resp = await fetch(url, {
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
      if (ct.includes('application/json')) {
        const err = await resp.json().catch(() => ({} as { message?: string; detail?: string }));
        return NextResponse.json({ message: err?.message || err?.detail || 'Failed to remove reaction' }, { status: resp.status });
      }
      const text = await resp.text().catch(() => '');
      return NextResponse.json({ message: text?.slice(0, 500) || 'Failed to remove reaction' }, { status: resp.status });
    }
    const data = ct.includes('application/json') ? await resp.json() : await resp.text();
    return NextResponse.json(typeof data === 'string' ? { message: data } : data);
  } catch (e) {
    return NextResponse.json({ message: 'Internal server error' }, { status: 500 });
  }
}
