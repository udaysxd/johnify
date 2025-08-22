import { NextResponse, NextRequest } from 'next/server';

function joinUrl(base: string, path: string) {
  const b = base.replace(/\/$/, '');
  const p = path.startsWith('/') ? path : `/${path}`;
  return `${b}${p}`;
}

export async function POST(request: NextRequest) {
  try {
    const { answers, questions } = await request.json();
    const backendBase = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';
    const url = joinUrl(backendBase, '/api/quiz/grade');

    const cookie = request.headers.get('cookie') || undefined;

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(cookie ? { Cookie: cookie } : {}),
      },
      body: JSON.stringify({ answers, questions }),
      cache: 'no-store',
    });

    // Pass through backend error details and status
    if (!response.ok) {
      const text = await response.text().catch(() => '');
      let body: unknown = undefined;
      try { body = text ? JSON.parse(text) : undefined; } catch {}
      let message = text || 'Failed to grade quiz';
      if (typeof body === 'object' && body !== null) {
        const b = body as Record<string, unknown>;
        const msg = (typeof b.message === 'string' ? b.message : undefined) ||
                    (typeof b.error === 'string' ? b.error : undefined);
        if (msg) message = msg;
      }
      return NextResponse.json({ message }, { status: response.status });
    }

    const data = await response.json();
    return NextResponse.json(data, { status: 200 });
  } catch (error) {
    console.error('Quiz grading error:', error);
    return NextResponse.json(
      { message: error instanceof Error ? error.message : 'Failed to grade quiz' },
      { status: 500 }
    );
  }
}
