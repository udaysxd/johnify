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
    const { searchParams } = new URL(request.url);
    const dirs = searchParams.getAll('dir').filter(Boolean);
    if (dirs.length === 0) {
      return NextResponse.json({ message: "Provide one or more 'dir' query parameters" }, { status: 400 });
    }

    const backendUrl = getBackendUrl();
    const qs = new URLSearchParams();
    dirs.forEach((d) => qs.append('dir', d));
    const url = `${backendUrl}/api/lites/status?${qs.toString()}`;

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 20000);

    let resp: Response;
    try {
      resp = await fetch(url, {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
        signal: controller.signal,
        credentials: 'include' as RequestCredentials,
      });
    } finally {
      clearTimeout(timeoutId);
    }

    const ct = resp.headers.get('content-type') || '';
    if (!resp.ok) {
      if (ct.includes('application/json')) {
        const err = await resp.json().catch(() => ({} as any));
        return NextResponse.json({ message: err?.message || err?.detail || 'Failed to fetch status' }, { status: resp.status });
      } else {
        const text = await resp.text().catch(() => '');
        return NextResponse.json({ message: text?.slice(0, 500) || 'Failed to fetch status' }, { status: resp.status });
      }
    }

    if (ct.includes('application/json')) {
      const data = await resp.json();
      return NextResponse.json(data, { status: 200 });
    } else {
      const text = await resp.text();
      try {
        const parsed = JSON.parse(text);
        return NextResponse.json(parsed, { status: 200 });
      } catch {
        return NextResponse.json({ message: text }, { status: 200 });
      }
    }
  } catch (error: any) {
    if (error?.name === 'AbortError') {
      return NextResponse.json({ message: 'Status request timed out' }, { status: 504 });
    }
    console.error('Error in /api/lites/status:', error);
    return NextResponse.json({ message: 'Internal server error' }, { status: 500 });
  }
}
