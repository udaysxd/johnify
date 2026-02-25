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
    const backendUrl = getBackendUrl();
    const bodyText = await request.text();
    const resp = await fetch(`${backendUrl}/api/auth/forgot-password-direct`, {
      method: 'POST',
      headers: {
        'Content-Type': request.headers.get('content-type') || 'application/json',
      },
      body: bodyText,
    });

    const contentType = resp.headers.get('content-type') || 'application/json';
    const text = await resp.text();
    if (!resp.ok) {
      return new NextResponse(text, { status: resp.status, headers: { 'Content-Type': contentType } });
    }
    return new NextResponse(text, { status: resp.status, headers: { 'Content-Type': contentType } });
  } catch (err) {
    console.error('Error in API /api/auth/forgot-password-direct:', err);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}
