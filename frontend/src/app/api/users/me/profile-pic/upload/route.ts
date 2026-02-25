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
    const url = `${backendUrl}/api/users/me/profile-pic/upload`;

    const contentType = request.headers.get('content-type') || '';
    if (!contentType.toLowerCase().includes('multipart/form-data')) {
      return NextResponse.json({ message: 'Content-Type must be multipart/form-data' }, { status: 400 });
    }

    const authHeader = request.headers.get('authorization') || request.headers.get('Authorization') || '';
    const cookieHeader = request.headers.get('cookie') || request.headers.get('Cookie') || '';

    const init: RequestInit & { duplex?: 'half' } = {
      method: 'POST',
      headers: {
        // Let the runtime forward the boundary; don't set Content-Type explicitly here
        ...(authHeader ? { Authorization: authHeader } : {}),
        ...(cookieHeader ? { Cookie: cookieHeader } : {}),
      },
      body: request.body,
      duplex: 'half',
      credentials: 'include' as RequestCredentials,
    };
    const resp = await fetch(url, init);

    const ct = resp.headers.get('content-type') || '';
    if (!resp.ok) {
      if (ct.includes('application/json')) {
        const err = await resp.json().catch(() => ({} as { message?: string; detail?: string }));
        return NextResponse.json({ message: err?.message || err?.detail || 'Upload failed' }, { status: resp.status });
      }
      const text = await resp.text().catch(() => '');
      return NextResponse.json({ message: text?.slice(0, 500) || 'Upload failed' }, { status: resp.status });
    }

    const data = await resp.json().catch(() => ({}));
    return NextResponse.json(data);
  } catch (e) {
    return NextResponse.json({ message: 'Internal server error' }, { status: 500 });
  }
}
