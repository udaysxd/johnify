import { NextResponse } from 'next/server';
import { Agent, setGlobalDispatcher } from 'undici';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// Configure a long-lived Undici Agent to disable default timeouts for polling
const longLivedAgent = new Agent({ headersTimeout: 0, bodyTimeout: 0 });
setGlobalDispatcher(longLivedAgent);

type VideoItem = {
  url?: string;
  [key: string]: unknown;
};

type BackendStatus = {
  status?: string;
  videos?: VideoItem[];
  [key: string]: unknown;
};

function isBackendStatus(value: unknown): value is BackendStatus {
  return typeof value === 'object' && value !== null;
}

function getBackendUrl(): string {
  const serverUrl = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL;
  if (serverUrl) return serverUrl.replace(/\/$/, '');
  return 'http://localhost:8000';
}

export async function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const jobId = url.searchParams.get('job_id');
    if (!jobId) {
      return NextResponse.json({ error: 'Missing job_id' }, { status: 400 });
    }

    const backend = getBackendUrl();
    const target = `${backend}/generate-video/status/${encodeURIComponent(jobId)}`;

    const incomingCookie = request.headers.get('cookie') || '';
    const incomingAuth = request.headers.get('authorization') || '';

    const res = await fetch(target, {
      headers: {
        ...(incomingCookie ? { Cookie: incomingCookie } : {}),
        ...(incomingAuth ? { Authorization: incomingAuth } : {}),
      },
      cache: 'no-store',
    });

    let dataUnknown: unknown;
    try {
      dataUnknown = await res.json();
    } catch {
      const text = await res.text();
      return NextResponse.json({ error: 'Invalid backend response', details: text }, { status: 502 });
    }

    if (!isBackendStatus(dataUnknown)) {
      return NextResponse.json({ error: 'Unexpected backend payload shape' }, { status: 502 });
    }
    const data: BackendStatus = dataUnknown;

    if (!res.ok) {
      return NextResponse.json({ error: 'Status check failed', details: data }, { status: res.status });
    }

    // If done and videos present, rewrite URLs through same-origin proxy
    if (data.status === 'done' && Array.isArray(data.videos)) {
      const backendUrl = backend;
      data.videos = data.videos.map((v: VideoItem) => {
        const absolute = typeof v.url === 'string' && v.url.startsWith('http') ? v.url : `${backendUrl}${v.url ?? ''}`;
        const proxied = `/api/proxy-video?url=${encodeURIComponent(absolute)}`;
        return { ...v, url: proxied };
      });
    }

    const out = NextResponse.json(data);
    out.headers.set('X-Route-Version', 'quiz-generate-video-status:v2');
    return out;
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: 'Failed to fetch job status', details: message }, { status: 500 });
  }
}

