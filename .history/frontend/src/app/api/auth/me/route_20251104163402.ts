import { NextResponse } from 'next/server';

export async function GET(request: Request) {
  try {
    const isProduction = process.env.NODE_ENV === 'production';
    const backendUrl = (process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || (isProduction ? '' : 'http://localhost:8000'))?.replace(/\/$/, '');

    if (!backendUrl) {
      return NextResponse.json({ error: 'Server configuration error: BACKEND_URL not set' }, { status: 500 });
    }
    
    const cookieHeader = request.headers.get('cookie');
    if (process.env.NODE_ENV !== 'production') {
      console.log('[/api/auth/me] Incoming Cookie header:', cookieHeader);
    }

    if (!cookieHeader) {
      return NextResponse.json({ error: 'Authentication cookie not found' }, { status: 401 });
    }

    // Extract access_token from cookie as a fallback Authorization header
    let bearerToken: string | undefined = undefined;
    try {
      const parts = cookieHeader.split(';').map(p => p.trim());
      const accessPart = parts.find(p => p.startsWith('access_token='));
      if (accessPart) {
        bearerToken = decodeURIComponent(accessPart.split('=')[1]);
      }
    } catch {}

    // Small retry with backoff to handle transient 429/503 from backend or edge
    const fetchWithRetry = async (attempt = 1): Promise<Response> => {
      const resp = await fetch(`${backendUrl}/api/auth/me`, {
        headers: {
          'Accept': 'application/json',
          // Forward the cookie header from the client to the backend
          'Cookie': cookieHeader,
          // Fallback in case backend misses cookies
          ...(bearerToken ? { 'Authorization': `Bearer ${bearerToken}` } : {}),
        },
        cache: 'no-store',
      });
      if ((resp.status === 429 || resp.status === 503) && attempt < 3) {
        const delay = 150 * Math.pow(2, attempt - 1);
        await new Promise(r => setTimeout(r, delay));
        return fetchWithRetry(attempt + 1);
      }
      return resp;
    };

    const response = await fetchWithRetry();

    if (!response.ok) {
      let backendError = 'Unknown error';
      try {
        const errorBody = await response.text();
        console.error('Backend /api/users/me error:', errorBody);
        backendError = errorBody;
      } catch (e) {
        console.error('Failed to read backend error body:', e);
      }
      return NextResponse.json(
        { error: `Backend error: ${backendError}`, status: response.status },
        { status: response.status }
      );
    }

    const userData = await response.json();
    
    // Create a new response with the user data
    const responseData = NextResponse.json(userData);
    // Short private cache to reduce bursts from multiple components
    responseData.headers.set('Cache-Control', 'private, max-age=20');
    
    // Forward any set-cookie headers from the backend
    const setCookie = response.headers.get('set-cookie');
    if (setCookie) {
      // In development, modify the cookie to be compatible with localhost
      const isLocalhost = process.env.NODE_ENV !== 'production';
      let modifiedCookie = setCookie;
      
      if (isLocalhost) {
        // Remove secure and SameSite=None attributes for local development
        modifiedCookie = setCookie
          .replace(/; Secure/gi, '')
          .replace(/; SameSite=None/gi, '; SameSite=Lax')
          .replace(/; Domain=[^;]+/gi, '');
      }
      
      responseData.headers.set('set-cookie', modifiedCookie);
    }
    
    return responseData;
  } catch (error) {
    console.error('Error in /api/auth/me:', error);
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
  }
}
