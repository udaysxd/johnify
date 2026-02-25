import { NextResponse } from 'next/server';

export async function POST(request: Request) {
  try {
    const isProduction = process.env.NODE_ENV === 'production';
    const backendUrl = (process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || (isProduction ? '' : 'http://localhost:8000')).replace(/\/$/, '');

    if (!backendUrl) {
      return NextResponse.json({ error: 'Server configuration error: BACKEND_URL not set' }, { status: 500 });
    }

    const cookieHeader = request.headers.get('cookie') || '';

    const resp = await fetch(`${backendUrl}/api/auth/me/deactivate`, {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
        'Cookie': cookieHeader,
      },
    });

    const text = await resp.text();

    if (!resp.ok) {
      return NextResponse.json({ error: text || 'Backend error' }, { status: resp.status });
    }

    const response = new NextResponse(text || JSON.stringify({ message: 'Account deactivated' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });

    // Clear cookie on the frontend domain as well
    const isLocalhost = process.env.NODE_ENV !== 'production';
    response.cookies.set('access_token', '', {
      httpOnly: true,
      secure: !isLocalhost,
      sameSite: isLocalhost ? 'lax' : 'none',
      path: '/',
      domain: isLocalhost ? undefined : '.johnify.com',
      maxAge: 0,
    });

    return response;
  } catch (err) {
    console.error('Error forwarding POST /api/auth/me/deactivate:', err);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}
