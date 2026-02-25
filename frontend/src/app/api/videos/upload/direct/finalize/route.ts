import { NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const isProduction = process.env.NODE_ENV === 'production';
const API_BASE_URL = isProduction
  ? (process.env.BACKEND_URL || 'https://johnify-backend-873155673176.us-central1.run.app')
  : (process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000');

export async function POST(request: Request) {
  try {
    const body = await request.json().catch(() => ({}));
    const cookieStore = await cookies();
    const accessToken = cookieStore.get('access_token')?.value || cookieStore.get('auth_token')?.value;
    if (!accessToken) {
      return NextResponse.json({ error: 'Authentication required' }, { status: 401 });
    }

    const resp = await fetch(`${API_BASE_URL}/api/videos/upload/direct/finalize`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${accessToken}`,
        'Accept': 'application/json',
      },
      body: JSON.stringify(body),
    });

    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      return NextResponse.json({ error: data.detail || 'Failed to finalize upload' }, { status: resp.status });
    }

    return NextResponse.json(data);
  } catch (e) {
    return NextResponse.json({ error: 'Internal error' }, { status: 500 });
  }
}
