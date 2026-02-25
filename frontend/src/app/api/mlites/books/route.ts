import { NextResponse } from 'next/server';

function getBackendUrl() {
  const isProduction = process.env.NODE_ENV === 'production';
  const envUrl = process.env.NEXT_PUBLIC_BACKEND_URL;
  if (envUrl && envUrl.trim()) return envUrl;
  if (isProduction) return 'https://johnify-backend-873155673176.us-central1.run.app';
  return 'http://localhost:8000';
}

export async function POST(request: Request) {
  try {
    let parsed: unknown;
    try {
      parsed = await request.json();
    } catch {
      parsed = {};
    }
    const obj = (parsed && typeof parsed === 'object') ? (parsed as Record<string, unknown>) : {};
    const user_id = obj.user_id as string | number | undefined;
    const topics = Array.isArray(obj.topics) ? (obj.topics as Array<unknown>) : [];
    if (!user_id || topics.length === 0) {
      return NextResponse.json({ message: 'user_id and topics are required' }, { status: 400 });
    }

    const backendUrl = getBackendUrl();
    const url = `${backendUrl}/api/mlites/books`;

    const authHeader = request.headers.get('authorization') || request.headers.get('Authorization') || '';
    const cookieHeader = request.headers.get('cookie') || request.headers.get('Cookie') || '';

    const resp = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(authHeader ? { Authorization: authHeader } : {}),
        ...(cookieHeader ? { Cookie: cookieHeader } : {}),
      },
      credentials: 'include' as RequestCredentials,
      body: JSON.stringify({
        topics,
        user_id,
        user_email: (typeof obj.user_email === 'string' ? (obj.user_email as string) : undefined),
      }),
    });

    const ct = resp.headers.get('content-type') || '';
    if (!resp.ok) {
      if (ct.includes('application/json')) {
        const err = await resp.json().catch(() => ({} as { message?: string; detail?: string }));
        return NextResponse.json({ message: err?.message || err?.detail || 'Failed to start mlites books' }, { status: resp.status });
      } else {
        const text = await resp.text().catch(() => '');
        return NextResponse.json({ message: text?.slice(0, 500) || 'Failed to start mlites books' }, { status: resp.status });
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
    console.error('Error in /api/mlites/books proxy:', error);
    return NextResponse.json({ message: 'Internal server error' }, { status: 500 });
  }
}
