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
    type ResendBody = { user_email?: string };
    const body: ResendBody = await request.json().catch(() => ({}) as ResendBody);
    const email = body?.user_email;
    if (!email) {
      return NextResponse.json({ message: 'user_email is required' }, { status: 400 });
    }

    const backendUrl = getBackendUrl();
    const url = `${backendUrl}/api/auth/resend-verification`;

    const resp = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify({ user_email: email }),
    });

    const ct = resp.headers.get('content-type') || '';
    if (!resp.ok) {
      if (ct.includes('application/json')) {
        const err: { message?: string; detail?: string } = await resp
          .json()
          .catch(() => ({} as { message?: string; detail?: string }));
        return NextResponse.json({ message: err?.message || err?.detail || 'Failed to resend verification email' }, { status: resp.status });
      } else {
        const text = await resp.text().catch(() => '');
        return NextResponse.json({ message: text?.slice(0, 500) || 'Failed to resend verification email' }, { status: resp.status });
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
    console.error('Error in POST /api/auth/resend-verification proxy:', error);
    return NextResponse.json({ message: 'Internal server error' }, { status: 500 });
  }
}
