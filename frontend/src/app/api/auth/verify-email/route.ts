import { NextRequest, NextResponse } from 'next/server';

type VerifyCompleteUser = {
  user_id?: string;
  user_email?: string;
  is_verified?: boolean;
};

type VerifyCompleteResponse = {
  access_token?: string;
  token_type?: string;
  user?: VerifyCompleteUser;
  expires_at?: string | number;
  message?: string;
  detail?: string;
};

function isVerifyCompleteResponse(x: unknown): x is VerifyCompleteResponse {
  if (typeof x !== 'object' || x === null) return false;
  const obj = x as Record<string, unknown>;
  return (
    (obj.access_token === undefined || typeof obj.access_token === 'string') &&
    (obj.token_type === undefined || typeof obj.token_type === 'string') &&
    (obj.user === undefined || typeof obj.user === 'object') &&
    (obj.expires_at === undefined || typeof obj.expires_at === 'string' || typeof obj.expires_at === 'number') &&
    (obj.message === undefined || typeof obj.message === 'string') &&
    (obj.detail === undefined || typeof obj.detail === 'string')
  );
}

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const token = searchParams.get('token') || '';
    if (!token) {
      return NextResponse.json({ message: 'token is required' }, { status: 400 });
    }

    // Derive a safe public origin using forwarded headers when running behind proxies/CDNs
    const xfProto = request.headers.get('x-forwarded-proto');
    const xfHost = request.headers.get('x-forwarded-host');
    const host = xfHost || request.headers.get('host') || request.nextUrl.host;
    const proto = xfProto || request.nextUrl.protocol.replace(':', '');
    const origin = `${proto}://${host}`;

    const backendUrl = (process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000').replace(/\/$/, '');

    // Call backend complete endpoint to validate token, mark user verified, and get JWT
    const resp = await fetch(`${backendUrl}/api/auth/verify-email/complete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify({ token })
    });

    const text = await resp.text();
    let dataUnknown: unknown = {};
    try { dataUnknown = text ? JSON.parse(text) : {}; } catch { dataUnknown = { message: text }; }
    const data: VerifyCompleteResponse = isVerifyCompleteResponse(dataUnknown) ? dataUnknown : {};

    if (!resp.ok) {
      const raw = (data.detail || data.message || '').toString().toLowerCase();
      let mapped: 'already_used' | 'expired' | 'invalid_token' | 'server_error' = 'invalid_token';
      if (raw.includes('already')) mapped = 'already_used';
      else if (raw.includes('expired')) mapped = 'expired';
      else if (raw.includes('invalid')) mapped = 'invalid_token';
      // Redirect back to frontend verify page with error reason so UI can show message
      const url = new URL('/auth/verify-email', origin);
      url.searchParams.set('error', mapped);
      return NextResponse.redirect(url, { status: 303 });
    }

    // On success, set access_token cookie for the site and redirect back to the
    // verify page with a success flag. The UI page will broadcast a cross-tab
    // signal and navigate the original tab to /preferences.
    const response = NextResponse.redirect(new URL('/auth/verify-email?success=true', origin), { status: 303 });

    const tokenValue = data.access_token;
    if (tokenValue) {
      const isLocalhost = process.env.NODE_ENV !== 'production';
      response.cookies.set('access_token', tokenValue, {
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
    console.error('verify-email API error:', err);
    return NextResponse.json({ message: 'Server error' }, { status: 500 });
  }
}
