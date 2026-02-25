import { NextResponse } from 'next/server';

function getBackendUrl() {
  const isProduction = process.env.NODE_ENV === 'production';
  const envUrl = process.env.NEXT_PUBLIC_BACKEND_URL;
  if (envUrl && envUrl.trim()) return envUrl;
  if (isProduction) return 'https://johnify-backend-873155673176.us-central1.run.app';
  return 'http://localhost:8000';
}

export async function GET(request: Request) {
  try {
    const backendUrl = getBackendUrl();
    const url = `${backendUrl}/api/preferences/topics`;

    const authHeader = request.headers.get('authorization') || request.headers.get('Authorization') || '';
    const cookieHeader = request.headers.get('cookie') || request.headers.get('Cookie') || '';

    const resp = await fetch(url, {
      method: 'GET',
      headers: {
        ...(authHeader ? { Authorization: authHeader } : {}),
        ...(cookieHeader ? { Cookie: cookieHeader } : {}),
        'Accept': 'application/json',
      },
      credentials: 'include' as RequestCredentials,
      cache: 'no-store',
    });

    const ct = resp.headers.get('content-type') || '';
    if (!resp.ok) {
      if (ct.includes('application/json')) {
        const err = await resp.json().catch(() => ({} as { message?: string; detail?: string }));
        return NextResponse.json({ message: err?.message || err?.detail || 'Failed to fetch topics' }, { status: resp.status });
      } else {
        const text = await resp.text().catch(() => '');
        return NextResponse.json({ message: text?.slice(0, 500) || 'Failed to fetch topics' }, { status: resp.status });
      }
    }

    if (ct.includes('application/json')) {
      const data = await resp.json();
      return NextResponse.json(data);
    } else {
      const text = await resp.text();
      try {
        const parsed = JSON.parse(text);
        return NextResponse.json(parsed);
      } catch {
        return NextResponse.json({ message: text }, { status: 200 });
      }
    }
  } catch (error) {
    console.error('Error in GET /api/preferences/topics proxy:', error);
    return NextResponse.json({ message: 'Internal server error' }, { status: 500 });
  }
}
