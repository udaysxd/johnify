import { NextResponse } from 'next/server';
type GoogleConfig = { client_id?: string };

export async function GET() {
  try {
    const isProduction = process.env.NODE_ENV === 'production';
    const backendUrl = (process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || (isProduction ? '' : 'http://localhost:8000'))?.replace(/\/$/, '');

    if (!backendUrl) {
      return NextResponse.json({ client_id: '' }, { status: 200 });
    }

    const resp = await fetch(`${backendUrl}/api/auth/google/config`, { headers: { 'Accept': 'application/json' } });
    const raw = await resp.text();
    let data: unknown = {};
    try { data = raw ? JSON.parse(raw) : {}; } catch { data = { client_id: '' } as GoogleConfig; }
    const cfg: GoogleConfig = (typeof data === 'object' && data !== null) ? (data as GoogleConfig) : {};
    return NextResponse.json({ client_id: cfg.client_id || '' });
  } catch {
    return NextResponse.json({ client_id: '' });
  }
}
