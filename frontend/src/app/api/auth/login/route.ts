import { NextRequest, NextResponse } from 'next/server';

// Types for backend login responses
type BackendUser = {
  user_id?: string;
  user_email?: string;
  user_name?: string;
  is_verified?: boolean;
  uuid?: string;
};

type BackendLoginResponse = {
  access_token?: string;
  token_type?: string;
  user?: BackendUser;
  expires_in?: number;
  expires_at?: number;
  // error shapes
  detail?: string;
  message?: string;
};

export async function POST(request: NextRequest) {
  try {
    // Log minimal environment context
    console.log('Login route env context:', {
      nodeEnv: process.env.NODE_ENV,
      hasBackendUrl: Boolean(process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL),
    });

    // Determine backend URL
    const isProduction = process.env.NODE_ENV === 'production';
    const backendUrl = (process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || (isProduction ? '' : 'http://localhost:8000'))?.replace(/\/$/, '');

    if (!backendUrl) {
      return NextResponse.json(
        { error: 'Server configuration error: Backend URL not set' },
        { status: 500 }
      );
    }

    // Prepare request to backend (keep form-urlencoded)
    const body = await request.text();
    const contentType = request.headers.get('content-type') || 'application/x-www-form-urlencoded';

    const endpoints = [
      `${backendUrl}/api/auth/login`,
      `${backendUrl}/api/auth/login/`,
    ];

    const doFetch = async (url: string) =>
      fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': contentType,
          'Accept': 'application/json, text/plain;q=0.8, */*;q=0.5',
        },
        body,
        // Important for cookie forwarding from backend if it sets any
        redirect: 'follow',
      });

    let backendResponse: Response | null = null;
    let lastErrorText = '';

    for (const url of endpoints) {
      try {
        const resp = await doFetch(url);
        backendResponse = resp;
        break;
      } catch (e) {
        lastErrorText = e instanceof Error ? e.message : String(e);
      }
    }

    if (!backendResponse) {
      return NextResponse.json(
        { error: 'Failed to reach auth server', details: lastErrorText },
        { status: 502 }
      );
    }

    const contentTypeResp = backendResponse.headers.get('content-type') || '';
    const isJson = /application\/json/i.test(contentTypeResp);

    // Read body once
    const rawText = await backendResponse.text();
    let data: BackendLoginResponse = {};
    if (isJson) {
      try { data = rawText ? JSON.parse(rawText) : {}; } catch {
        // fall back to text
        data = { message: rawText };
      }
    } else {
      data = { message: rawText };
    }

    // On non-OK, proxy status and message from backend
    if (!backendResponse.ok) {
      console.error('Backend login error:', { status: backendResponse.status, data });
      return NextResponse.json(
        {
          error: data?.detail || data?.message || `Login failed (status ${backendResponse.status})`,
          details: isJson ? data : undefined,
        },
        { status: backendResponse.status }
      );
    }

    // Create response and forward Set-Cookie if provided by backend
    const responseData = {
      access_token: data.access_token,
      token_type: data.token_type,
      user: {
        user_id: data.user?.user_id || '',
        user_email: data.user?.user_email || '',
        user_name: data.user?.user_name || '',
        is_verified: data.user?.is_verified || false,
        uuid: data.user?.uuid || ''
      },
      expires_in: data.expires_in || 3600,
      expires_at: data.expires_at || Math.floor(Date.now() / 1000) + 3600,
    };

    const response = NextResponse.json(responseData);

    // Forward backend Set-Cookie header if present
    const setCookie = backendResponse.headers.get('set-cookie');
    if (setCookie) {
      response.headers.set('set-cookie', setCookie);
    }

    // Also set access_token cookie explicitly if present
    if (data.access_token) {
      const isLocalhost = process.env.NODE_ENV !== 'production';
      response.cookies.set('access_token', data.access_token, {
        httpOnly: true,
        secure: !isLocalhost,
        sameSite: isLocalhost ? 'lax' : 'none',
        path: '/',
        domain: isLocalhost ? undefined : '.johnify.com',
        maxAge: 60 * 60 * 24 * 7,
      });
    }

    return response;
  } catch (error: unknown) {
    console.error('Error in login route:', error);
    const errorMessage = error instanceof Error ? error.message : 'Unknown error';
    return NextResponse.json(
      {
        error: 'Failed to process login',
        details: process.env.NODE_ENV !== 'production' ? errorMessage : undefined,
      },
      { status: 500 }
    );
  }
}
