import { NextRequest, NextResponse } from 'next/server';
type LoginData = {
  access_token?: string;
  token_type?: string;
  user?: {
    user_id?: string;
    user_email?: string;
    user_name?: string;
    is_verified?: boolean;
    uuid?: string;
  };
  detail?: string;
  message?: string;
};

export async function POST(request: NextRequest) {
  try {
    const isProduction = process.env.NODE_ENV === 'production';
    const backendUrl = (process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || (isProduction ? '' : 'http://localhost:8000'))?.replace(/\/$/, '');

    if (!backendUrl) {
      return NextResponse.json({ error: 'Server configuration error: Backend URL not set' }, { status: 500 });
    }

    const body = await request.json().catch(() => ({}));

    const resp = await fetch(`${backendUrl}/api/auth/google`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify(body),
      redirect: 'follow',
    });

    const raw = await resp.text();
    let data: unknown = {};
    try { data = raw ? JSON.parse(raw) : {}; } catch { data = { message: raw } as { message: string }; }

    // Proxy non-OK directly
    if (!resp.ok) {
      const err = data as { detail?: string; message?: string };
      return NextResponse.json({ error: err?.detail || err?.message || 'Google sign-in failed' }, { status: resp.status });
    }

    const parsed: LoginData = (typeof data === 'object' && data !== null) ? (data as LoginData) : {} as LoginData;
    const response = NextResponse.json(parsed);

    // Forward cookie if present
    const setCookie = resp.headers.get('set-cookie');
    if (setCookie) {
      response.headers.set('set-cookie', setCookie);
    }

    // Also set cookie explicitly if token present
    if (parsed?.access_token) {
      const isLocalhost = process.env.NODE_ENV !== 'production';
      response.cookies.set('access_token', parsed.access_token as string, {
        httpOnly: true,
        secure: !isLocalhost,
        sameSite: isLocalhost ? 'lax' : 'none',
        path: '/',
        domain: isLocalhost ? undefined : '.johnify.com',
        maxAge: 60 * 60 * 24 * 7,
      });
    }

    return response;
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: 'Failed to process Google sign-in', details: message }, { status: 500 });
  }
}
