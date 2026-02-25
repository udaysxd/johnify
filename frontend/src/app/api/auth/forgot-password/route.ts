import { NextRequest, NextResponse } from 'next/server';

export async function POST(request: NextRequest) {
  try {
    const isProduction = process.env.NODE_ENV === 'production';
    const backendUrl = (
      isProduction
        ? 'https://johnify-backend-873155673176.us-central1.run.app'
        : (process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000')
    ).replace(/\/$/, '');

    const bodyText = await request.text();
    const resp = await fetch(`${backendUrl}/api/auth/forgot-password`, {
      method: 'POST',
      headers: {
        'Content-Type': request.headers.get('content-type') || 'application/json',
        'Accept': 'application/json',
      },
      body: bodyText,
    });

    const text = await resp.text();
    const contentType = resp.headers.get('content-type') || 'application/json';
    if (!resp.ok) {
      return new NextResponse(text || JSON.stringify({ message: 'Backend error' }), {
        status: resp.status,
        headers: { 'Content-Type': contentType },
      });
    }
    return new NextResponse(text, { status: resp.status, headers: { 'Content-Type': contentType } });
  } catch (err) {
    console.error('Error in API /api/auth/forgot-password:', err);
    return NextResponse.json({ message: 'Internal server error' }, { status: 500 });
  }
}
