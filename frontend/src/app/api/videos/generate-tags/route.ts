import { NextResponse } from 'next/server';

const isProduction = process.env.NODE_ENV === 'production';
const API_BASE_URL = isProduction
  ? (process.env.BACKEND_URL || 'https://johnify-backend-873155673176.us-central1.run.app')
  : (process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000');

function createErrorResponse(message: string, status: number, details?: unknown): NextResponse {
  console.error(`[API Error] ${message}`, details || '');
  const body: { error: string; details?: unknown } = { error: message };
  if (details !== undefined) body.details = details;
  return new NextResponse(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

export async function GET(request: Request): Promise<NextResponse> {
  try {
    const url = new URL(request.url);
    const topic = url.searchParams.get('topic') || '';
    if (!topic.trim()) {
      return createErrorResponse('Missing topic', 400);
    }

    const resp = await fetch(`${API_BASE_URL}/api/videos/generate-tags?` + new URLSearchParams({ topic }), {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
      cache: 'no-store',
    });

    if (!resp.ok) {
      const errorData = await resp.json().catch(() => ({}));
      return createErrorResponse(errorData.detail || 'Failed to generate tags', resp.status);
    }

    const data = await resp.json();
    const tags: string[] = Array.isArray(data?.tags) ? data.tags.map(String) : [];
    const source: string = typeof data?.source === 'string' ? data.source : 'unknown';

    return NextResponse.json({ tags, source });
  } catch (error) {
    return createErrorResponse('Internal server error', 500, error instanceof Error ? error.message : 'Unknown error');
  }
}
