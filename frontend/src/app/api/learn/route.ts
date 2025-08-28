import { NextResponse } from 'next/server';
// Note: Avoid importing 'undici' to keep build portable. We'll rely on AbortController
// and simple retries to mitigate transient upstream timeouts.

interface LearnRequest {
  topic: string;
  complexity_level?: number;
}

// Helper function to get backend URL with safe production fallback
function getBackendUrl() {
  const isProduction = process.env.NODE_ENV === 'production';
  const envUrl = process.env.NEXT_PUBLIC_BACKEND_URL;
  if (envUrl && envUrl.trim()) return envUrl;
  // Never point to localhost in production
  if (isProduction) {
    return 'https://johnify-backend-873155673176.us-central1.run.app';
  }
  // Development default
  return 'http://localhost:8000';
}

export async function POST(request: Request) {
  try {
    const { topic, complexity_level = 3 } = await request.json() as LearnRequest;
    
    if (!topic) {
      return NextResponse.json(
        { error: 'Topic is required' },
        { status: 400 }
      );
    }

    const backendUrl = getBackendUrl();
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 600000); // 10 minute timeout
    
    try {
      // Simple retry for transient network issues
      const maxRetries = 2;
      let lastError: unknown = null;
      let response: Response | null = null;
      for (let attempt = 0; attempt <= maxRetries; attempt++) {
        try {
          // Forward auth context (cookies and authorization header) to backend
          const authHeader = request.headers.get('authorization') || request.headers.get('Authorization') || '';
          const cookieHeader = request.headers.get('cookie') || request.headers.get('Cookie') || '';

          response = await fetch(`${backendUrl}/learn`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              ...(authHeader ? { 'Authorization': authHeader } : {}),
              ...(cookieHeader ? { 'Cookie': cookieHeader } : {}),
            },
            body: JSON.stringify({
              topic,
              complexity_level: Math.min(5, Math.max(1, complexity_level || 3)) // Ensure between 1-5
            }),
            signal: controller.signal,
            // Not strictly required in Node env, but documented for intent
            credentials: 'include' as RequestCredentials,
          });
          break; // success
        } catch (e) {
          lastError = e;
          if (attempt === maxRetries) throw e;
        }
      }

      if (!response) {
        throw lastError || new Error('Unknown network error');
      }

      clearTimeout(timeoutId);

      if (!response.ok) {
        const contentType = response.headers.get('content-type') || '';
        if (contentType.includes('application/json')) {
          const errorData = await response.json().catch(() => ({}));
          return NextResponse.json(
            {
              // Frontend checks detail || message || error
              message: 'Failed to generate learning video',
              detail: errorData.message || errorData.detail || response.statusText
            },
            { status: response.status }
          );
        } else {
          const textBody = await response.text().catch(() => '');
          return NextResponse.json(
            {
              message: 'Backend returned non-JSON error',
              status: response.status,
              detail: response.statusText,
              body: textBody?.slice(0, 500) || ''
            },
            { status: response.status }
          );
        }
      }

      // Success path: be robust to non-JSON success bodies in production
      const successContentType = response.headers.get('content-type') || '';
      let data: unknown;
      if (successContentType.includes('application/json')) {
        data = await response.json();
      } else {
        const textBody = await response.text();
        try {
          data = JSON.parse(textBody);
        } catch {
          return NextResponse.json(
            {
              error: 'Backend returned non-JSON success body',
              body: textBody?.slice(0, 500) || ''
            },
            { status: 502 }
          );
        }
      }
      // Ensure video_url is absolute if present
      if (data && typeof data === 'object' && data !== null) {
        const d = data as { video_url?: unknown };
        if (typeof d.video_url === 'string') {
          const v = d.video_url as string;
          if (!v.startsWith('http')) {
            (d as Record<string, unknown>).video_url = `${backendUrl}${v.startsWith('/') ? '' : '/'}${v}`;
          }
        }
      }
      return NextResponse.json(data as Record<string, unknown>);
      
    } catch (error: unknown) {
      clearTimeout(timeoutId);
      if (error instanceof Error && error.name === 'AbortError') {
        return NextResponse.json(
          { error: 'Request timed out. Please try again.' },
          { status: 504 }
        );
      }
      throw error;
    }
    
  } catch (error: unknown) {
    console.error('Error in /api/learn:', error);
    return NextResponse.json(
      { 
        error: 'Internal server error',
        details: process.env.NODE_ENV === 'development' && error instanceof Error ? error.message : undefined
      },
      { status: 500 }
    );
  }
}
