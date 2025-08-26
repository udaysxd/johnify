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

function extractDetail(value: unknown): string | undefined {
  if (value && typeof value === 'object' && 'detail' in value) {
    const d = (value as { detail?: unknown }).detail;
    if (typeof d === 'string') return d;
  }
  return undefined;
}

export async function GET(request: Request, { params }: { params: Promise<{ post_id: string }> }): Promise<NextResponse> {
  const { post_id } = await params;
  try {
    const cookieHeader = request.headers.get('cookie') ?? undefined;
    const authHeader = request.headers.get('authorization') ?? undefined;
    const resp = await fetch(`${API_BASE_URL}/api/videos/${encodeURIComponent(post_id)}/likes`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
        ...(cookieHeader ? { Cookie: cookieHeader } : {}),
        ...(authHeader ? { Authorization: authHeader } : {}),
      },
      cache: 'no-store',
    });
    if (!resp.ok) {
      const raw: unknown = await resp.json().catch(() => ({}));
      return createErrorResponse(extractDetail(raw) || 'Failed to get likes', resp.status, raw);
    }
    const data = await resp.json();
    return NextResponse.json(data);
  } catch (error) {
    return createErrorResponse('Internal server error', 500, error instanceof Error ? error.message : 'Unknown error');
  }
}

export async function POST(request: Request, { params }: { params: Promise<{ post_id: string }> }): Promise<NextResponse> {
  const { post_id } = await params;
  try {
    const cookieHeader = request.headers.get('cookie') ?? undefined;
    const authHeader = request.headers.get('authorization') ?? undefined;
    const body = await request.json().catch(() => ({}));
    const resp = await fetch(`${API_BASE_URL}/api/videos/${encodeURIComponent(post_id)}/likes`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(cookieHeader ? { Cookie: cookieHeader } : {}),
        ...(authHeader ? { Authorization: authHeader } : {}),
      },
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      const raw: unknown = await resp.json().catch(() => ({}));
      return createErrorResponse(extractDetail(raw) || 'Failed to update like', resp.status, raw);
    }
    const data = await resp.json();
    return NextResponse.json(data);
  } catch (error) {
    return createErrorResponse('Internal server error', 500, error instanceof Error ? error.message : 'Unknown error');
  }
}
