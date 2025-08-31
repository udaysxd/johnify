import { NextResponse } from 'next/server';

function getBackendUrl() {
  const isProduction = process.env.NODE_ENV === 'production';
  const envUrl = process.env.NEXT_PUBLIC_BACKEND_URL;
  if (envUrl && envUrl.trim()) return envUrl;
  if (isProduction) return 'https://johnify-backend-873155673176.us-central1.run.app';
  return 'http://localhost:8000';
}

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const user_id = searchParams.get('user_id');
    if (!user_id) {
      return NextResponse.json({ message: 'user_id is required' }, { status: 400 });
    }

    const backendUrl = getBackendUrl();
    const url = `${backendUrl}/api/mlites/topics?user_id=${encodeURIComponent(user_id)}`;

    const authHeader = request.headers.get('authorization') || request.headers.get('Authorization') || '';
    const cookieHeader = request.headers.get('cookie') || request.headers.get('Cookie') || '';

    const resp = await fetch(url, {
      method: 'GET',
      headers: {
        ...(authHeader ? { Authorization: authHeader } : {}),
        ...(cookieHeader ? { Cookie: cookieHeader } : {}),
      },
      credentials: 'include' as RequestCredentials,
      cache: 'no-store',
    });

    const ct = resp.headers.get('content-type') || '';
    if (!resp.ok) {
      if (ct.includes('application/json')) {
        const err = await resp.json().catch(() => ({} as any));
        return NextResponse.json({ message: err?.message || err?.detail || 'Failed to fetch topics' }, { status: resp.status });
      } else {
        const text = await resp.text().catch(() => '');
        return NextResponse.json({ message: text?.slice(0, 500) || 'Failed to fetch topics' }, { status: resp.status });
      }
    }

    if (ct.includes('application/json')) {
      const data = await resp.json();
      return NextResponse.json(data);
    } else {
      const text = await resp.text();
      try {
        const parsed = JSON.parse(text);
        return NextResponse.json(parsed);
      } catch {
        return NextResponse.json({ message: text }, { status: 200 });
      }
    }
  } catch (error) {
    console.error('Error in GET /api/mlites/topics proxy:', error);
    return NextResponse.json({ message: 'Internal server error' }, { status: 500 });
  }
}

export async function DELETE(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const user_id = searchParams.get('user_id');
    const topic_id = searchParams.get('topic_id');
    if (!user_id || !topic_id) {
      return NextResponse.json({ message: 'user_id and topic_id are required' }, { status: 400 });
    }

    const backendUrl = getBackendUrl();
    const url = `${backendUrl}/api/mlites/topics?user_id=${encodeURIComponent(user_id)}&topic_id=${encodeURIComponent(topic_id)}`;

    const authHeader = request.headers.get('authorization') || request.headers.get('Authorization') || '';
    const cookieHeader = request.headers.get('cookie') || request.headers.get('Cookie') || '';

    const resp = await fetch(url, {
      method: 'DELETE',
      headers: {
        ...(authHeader ? { Authorization: authHeader } : {}),
        ...(cookieHeader ? { Cookie: cookieHeader } : {}),
      },
      credentials: 'include' as RequestCredentials,
    });

    const ct = resp.headers.get('content-type') || '';
    if (!resp.ok) {
      if (ct.includes('application/json')) {
        const err = await resp.json().catch(() => ({} as any));
        return NextResponse.json({ message: err?.message || err?.detail || 'Failed to unsubscribe topic' }, { status: resp.status });
      } else {
        const text = await resp.text().catch(() => '');
        return NextResponse.json({ message: text?.slice(0, 500) || 'Failed to unsubscribe topic' }, { status: resp.status });
      }
    }

    if (ct.includes('application/json')) {
      const data = await resp.json();
      return NextResponse.json(data);
    } else {
      const text = await resp.text();
      try {
        const parsed = JSON.parse(text);
        return NextResponse.json(parsed);
      } catch {
        return NextResponse.json({ message: text }, { status: 200 });
      }
    }
  } catch (error) {
    console.error('Error in DELETE /api/mlites/topics proxy:', error);
    return NextResponse.json({ message: 'Internal server error' }, { status: 500 });
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json();
    if (!body || !body.user_id || !Array.isArray(body.topics)) {
      return NextResponse.json({ message: 'user_id and topics are required' }, { status: 400 });
    }

    const backendUrl = getBackendUrl();
    const url = `${backendUrl}/api/mlites/topics`;

    const authHeader = request.headers.get('authorization') || request.headers.get('Authorization') || '';
    const cookieHeader = request.headers.get('cookie') || request.headers.get('Cookie') || '';

    const resp = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(authHeader ? { Authorization: authHeader } : {}),
        ...(cookieHeader ? { Cookie: cookieHeader } : {}),
      },
      credentials: 'include' as RequestCredentials,
      body: JSON.stringify(body),
    });

    const ct = resp.headers.get('content-type') || '';

    if (!resp.ok) {
      if (ct.includes('application/json')) {
        const err = await resp.json().catch(() => ({} as any));
        return NextResponse.json({ message: err?.message || err?.detail || 'Failed to upsert topics' }, { status: resp.status });
      } else {
        const text = await resp.text().catch(() => '');
        return NextResponse.json({ message: text?.slice(0, 500) || 'Failed to upsert topics' }, { status: resp.status });
      }
    }

    if (ct.includes('application/json')) {
      const data = await resp.json();
      return NextResponse.json(data);
    } else {
      const text = await resp.text();
      try {
        const parsed = JSON.parse(text);
        return NextResponse.json(parsed);
      } catch {
        return NextResponse.json({ message: text }, { status: 200 });
      }
    }
  } catch (error) {
    console.error('Error in /api/mlites/topics proxy:', error);
    return NextResponse.json({ message: 'Internal server error' }, { status: 500 });
  }
}
