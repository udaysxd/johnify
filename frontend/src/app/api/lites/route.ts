import { NextResponse } from 'next/server';

interface LiteTopicInput {
  topic: string;
  minutes_per_day: 1 | 2 | 3 | 4 | 5 | 10 | 15;
}

interface CreateLitesRequest {
  topics: LiteTopicInput[];
}

function getBackendUrl() {
  const isProduction = process.env.NODE_ENV === 'production';
  const envUrl = process.env.NEXT_PUBLIC_BACKEND_URL;
  if (envUrl && envUrl.trim()) return envUrl;
  if (isProduction) return 'https://johnify-backend-873155673176.us-central1.run.app';
  return 'http://localhost:8000';
}

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as CreateLitesRequest;
    if (!body || !Array.isArray(body.topics) || body.topics.length === 0) {
      return NextResponse.json({ message: 'At least one topic is required' }, { status: 400 });
    }

    // Basic validation and clamp values
    const topics = body.topics
      .slice(0, 100) // future-proof upper bound; UI may cap at 3 for now
      .map((t) => ({
        topic: String(t.topic || '').trim(),
        minutes_per_day: ([1, 2, 3, 4, 5, 10, 15].includes(Number(t.minutes_per_day)) ? Number(t.minutes_per_day) : 5) as 1 | 2 | 3 | 4 | 5 | 10 | 15,
      }))
      .filter((t) => t.topic.length > 0);

    if (topics.length === 0) {
      return NextResponse.json({ message: 'All topics are empty' }, { status: 400 });
    }

    const backendUrl = getBackendUrl();
    const url = `${backendUrl}/api/lites`;

    const authHeader = request.headers.get('authorization') || request.headers.get('Authorization') || '';
    const cookieHeader = request.headers.get('cookie') || request.headers.get('Cookie') || '';

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 600000); // 10 minutes

    let response: Response;
    try {
      response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authHeader ? { Authorization: authHeader } : {}),
          ...(cookieHeader ? { Cookie: cookieHeader } : {}),
        },
        body: JSON.stringify({ topics }),
        credentials: 'include' as RequestCredentials,
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timeoutId);
    }

    const ct = response.headers.get('content-type') || '';

    if (!response.ok) {
      if (ct.includes('application/json')) {
        const err = await response.json().catch(() => ({} as { message?: string; detail?: string }));
        return NextResponse.json(
          { message: err?.message || err?.detail || 'Failed to create lites' },
          { status: response.status }
        );
      } else {
        const text = await response.text().catch(() => '');
        return NextResponse.json(
          { message: text?.slice(0, 500) || 'Failed to create lites' },
          { status: response.status }
        );
      }
    }

    // Success path
    if (ct.includes('application/json')) {
      const data = await response.json();
      return NextResponse.json(data);
    } else {
      const text = await response.text();
      // Try to parse; otherwise, wrap into message
      try {
        const parsed = JSON.parse(text);
        return NextResponse.json(parsed);
      } catch {
        return NextResponse.json({ message: text }, { status: 200 });
      }
    }
  } catch (error: unknown) {
    const errObj = (error && typeof error === 'object') ? (error as { name?: string; message?: string }) : {};
    if (errObj.name === 'AbortError') {
      return NextResponse.json({ message: 'Request timed out. Please try again.' }, { status: 504 });
    }
    console.error('Error in /api/lites:', error);
    return NextResponse.json(
      {
        message: 'Internal server error',
        details: process.env.NODE_ENV === 'development' && errObj.message ? errObj.message : undefined,
      },
      { status: 500 }
    );
  }
}
