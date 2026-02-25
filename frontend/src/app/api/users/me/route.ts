import { NextResponse } from 'next/server';

function getBackendUrl() {
  return process.env.NEXT_PUBLIC_BACKEND_URL || process.env.BACKEND_URL || 'http://localhost:8000';
}

export async function GET(request: Request) {
  try {
    const backendUrl = getBackendUrl();
    const url = `${backendUrl}/api/users/me`;
    const authHeader = request.headers.get('authorization') || request.headers.get('Authorization') || '';
    const cookieHeader = request.headers.get('cookie') || request.headers.get('Cookie') || '';

    const resp = await fetch(url, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
        ...(authHeader ? { Authorization: authHeader } : {}),
        ...(cookieHeader ? { Cookie: cookieHeader } : {}),
      },
      credentials: 'include' as RequestCredentials,
      cache: 'no-store',
    });

    const ct = resp.headers.get('content-type') || '';
    if (!resp.ok) {
      if (ct.includes('application/json')) {
        const err = await resp.json().catch(() => ({} as { message?: string; detail?: string }));
        return NextResponse.json({ message: err?.message || err?.detail || 'Failed to fetch user' }, { status: resp.status });
      }
      const text = await resp.text().catch(() => '');
      return NextResponse.json({ message: text?.slice(0, 500) || 'Failed to fetch user' }, { status: resp.status });
    }

    const data = ct.includes('application/json') ? await resp.json() : await resp.text();
    return NextResponse.json(typeof data === 'string' ? { message: data } : data);
  } catch (e) {
    return NextResponse.json({ message: 'Internal server error' }, { status: 500 });
  }
}
