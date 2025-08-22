import { NextRequest, NextResponse } from 'next/server';

// Allow only the backend origin defined in env
const BACKEND_URL = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || '';

function sanitizeBackendUrl(input: string): string | null {
  try {
    const u = new URL(input);
    // Strip any explicit port (Cloud Run shouldn't use :8000 externally)
    u.port = '';
    return u.toString();
  } catch {
    return null;
  }
}

function isAllowedTarget(target: URL, backendOrigin: URL): boolean {
  return (
    target.hostname === backendOrigin.hostname &&
    target.protocol === backendOrigin.protocol
  );
}

export async function GET(req: NextRequest) {
  try {
    const urlParam = req.nextUrl.searchParams.get('url');
    if (!urlParam) {
      return NextResponse.json({ error: 'Missing url parameter' }, { status: 400 });
    }

    const backendStr = BACKEND_URL;
    if (!backendStr) {
      return NextResponse.json({ error: 'Backend origin not configured' }, { status: 500 });
    }

    const backendOrigin = new URL(backendStr);

    const sanitized = sanitizeBackendUrl(urlParam);
    if (!sanitized) {
      return NextResponse.json({ error: 'Invalid target URL' }, { status: 400 });
    }

    const target = new URL(sanitized);

    if (!isAllowedTarget(target, backendOrigin)) {
      return NextResponse.json({ error: 'Target not allowed' }, { status: 403 });
    }

    // Forward range and relevant headers
    const range = req.headers.get('range') || undefined;
    const accept = req.headers.get('accept') || '*/*';

    const resp = await fetch(target.toString(), {
      method: 'GET',
      headers: {
        ...(range ? { Range: range } : {}),
        Accept: accept,
      },
      // No need for credentials; media is public
      cache: 'no-store',
    });

    // Build passthrough headers
    const headers = new Headers();
    const forwardHeaders = [
      'content-type',
      'content-length',
      'accept-ranges',
      'content-range',
      'etag',
      'last-modified',
      'cache-control',
    ];

    for (const h of forwardHeaders) {
      const v = resp.headers.get(h);
      if (v) headers.set(h, v);
    }

    // Ensure helpful headers
    if (!headers.has('accept-ranges')) headers.set('accept-ranges', 'bytes');
    headers.set('cross-origin-resource-policy', 'same-origin'); // served from same origin now

    return new NextResponse(resp.body, {
      status: resp.status,
      headers,
    });
  } catch (e) {
    return NextResponse.json(
      { error: 'Proxy failed', details: e instanceof Error ? e.message : 'Unknown error' },
      { status: 502 }
    );
  }
}
