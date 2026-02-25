import { NextResponse } from 'next/server';

export async function PUT(request: Request) {
  try {
    const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || process.env.BACKEND_URL || 'http://localhost:8000';

    const cookieHeader = request.headers.get('cookie') || '';
    const body = await request.text();

    const resp = await fetch(`${backendUrl}/api/auth/me/password`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Cookie': cookieHeader,
      },
      body,
    });

    const text = await resp.text();
    if (!resp.ok) {
      return NextResponse.json({ error: text || 'Backend error' }, { status: resp.status });
    }

    return new NextResponse(text, {
      status: resp.status,
      headers: { 'Content-Type': resp.headers.get('Content-Type') || 'application/json' },
    });
  } catch (err) {
    console.error('Error forwarding PUT /api/auth/me/password:', err);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}
