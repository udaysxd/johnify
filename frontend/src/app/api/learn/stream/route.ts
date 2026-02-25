import { NextRequest } from 'next/server';

function getBackendUrl() {
  const isProduction = process.env.NODE_ENV === 'production';
  const envUrl = process.env.NEXT_PUBLIC_BACKEND_URL;
  if (envUrl && envUrl.trim()) return envUrl;
  if (isProduction) return 'https://johnify-backend-873155673176.us-central1.run.app';
  return 'http://localhost:8000';
}

export const runtime = 'edge';

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const userId = searchParams.get('user_id');
  if (!userId) {
    return new Response(JSON.stringify({ message: 'user_id is required' }), {
      status: 400,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  const backendUrl = getBackendUrl();
  const url = `${backendUrl}/api/learn/stream?user_id=${encodeURIComponent(userId)}`;

  const controller = new AbortController();
  const upstream = await fetch(url, {
    method: 'GET',
    headers: {
      Accept: 'text/event-stream',
      // forward cookies to maintain session on backend
      Cookie: req.headers.get('cookie') || '',
      // forward auth header if present
      ...(req.headers.get('authorization')
        ? { Authorization: req.headers.get('authorization') as string }
        : {}),
    },
    signal: controller.signal,
  });

  if (!upstream.ok || !upstream.body) {
    return new Response(JSON.stringify({ message: 'Failed to connect to stream' }), {
      status: upstream.status || 502,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  // Stream passthrough
  const { readable, writable } = new TransformStream();
  upstream.body.pipeTo(writable);

  return new Response(readable, {
    status: 200,
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      // Allow the browser to receive events immediately
      'X-Accel-Buffering': 'no',
    },
  });
}
