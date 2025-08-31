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
  const url = `${backendUrl}/api/mlites/stream?user_id=${encodeURIComponent(userId)}`;

  try {
    const controller = new AbortController();
    const upstream = await fetch(url, {
      method: 'GET',
      headers: {
        Accept: 'text/event-stream',
        Cookie: req.headers.get('cookie') || '',
        ...(req.headers.get('authorization')
          ? { Authorization: req.headers.get('authorization') as string }
          : {}),
      },
      signal: controller.signal,
    });

    if (!upstream.ok || !upstream.body) {
      return new Response(
        JSON.stringify({ message: 'Failed to connect to mlites stream', status: upstream.status }),
        { status: upstream.status || 502, headers: { 'Content-Type': 'application/json' } }
      );
    }

    const { readable, writable } = new TransformStream();
    upstream.body.pipeTo(writable);

    return new Response(readable, {
      status: 200,
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache, no-transform',
        Connection: 'keep-alive',
        'X-Accel-Buffering': 'no',
      },
    });
  } catch (err: any) {
    return new Response(
      JSON.stringify({ message: 'Error connecting to mlites stream', error: String(err && err.message || err) }),
      { status: 502, headers: { 'Content-Type': 'application/json' } }
    );
  }
}
