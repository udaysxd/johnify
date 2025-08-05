import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import { getToken } from 'next-auth/jwt';



// List of public paths that don't require authentication
const publicPaths = [
  '/',
  '/auth/signin',
  '/auth/signup',
  '/auth/error',
  '/_next',
  '/favicon.ico',
  '/api/auth',
  '/test-auth',  // Add any test or public API endpoints here
];

// List of API routes that don't require authentication
const publicApiRoutes = [
  '/api/auth',
  '/api/health',
  '/api/public',
];

export async function middleware(request: NextRequest) {
  // JWT secret for token verification
  const secret = process.env.NEXTAUTH_SECRET;
  if (!secret) {
    return new NextResponse(JSON.stringify({ error: 'NEXTAUTH_SECRET is not set. Please check your environment variables.' }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    });
  }
  const { pathname } = request.nextUrl;
  const origin = request.headers.get('origin') || '';
  
  // Handle CORS preflight requests
  if (request.method === 'OPTIONS') {
    const response = new NextResponse(null, { status: 204 });
    addCorsHeaders(response, origin);
    return response;
  }

  // Add CORS headers to all responses
  const response = NextResponse.next();
  addCorsHeaders(response, origin);

  // Skip middleware for public paths and static files
  if (
    isPublicPath(pathname) ||
    pathname.startsWith('/_next/') ||
    pathname.endsWith('.png') ||
    pathname.endsWith('.jpg') ||
    pathname.endsWith('.jpeg') ||
    pathname.endsWith('.svg') ||
    pathname.endsWith('.ico') ||
    pathname.endsWith('.json') ||
    pathname.endsWith('.webmanifest') ||
    pathname.endsWith('.css') ||
    pathname.endsWith('.js') ||
    pathname.endsWith('.txt') ||
    pathname.endsWith('.woff') ||
    pathname.endsWith('.woff2') ||
    pathname.endsWith('.ttf') ||
    pathname.endsWith('.eot') ||
    pathname.endsWith('.otf') ||
    pathname.endsWith('.mp4') ||
    pathname.endsWith('.webm') ||
    pathname.endsWith('.ogg') ||
    pathname.endsWith('.mp3') ||
    pathname.endsWith('.wav') ||
    pathname.endsWith('.pdf')
  ) {
    return response;
  }

  try {
    // Get the token from the request
    const token = await getToken({ 
      req: request,
      secret,
      // Add any additional options needed for your token verification
    });

    // If there's no token and the path requires authentication, redirect to signin
    if (!token && !isPublicPath(pathname) && !pathname.startsWith('/api/')) {
      const signInUrl = new URL('/auth/signin', request.url);
      signInUrl.searchParams.set('callbackUrl', pathname);
      return NextResponse.redirect(signInUrl);
    }

    // For API routes, return 401 if not authenticated
    if (pathname.startsWith('/api/') && !isPublicApiPath(pathname) && !token) {
      return new NextResponse(JSON.stringify({ error: 'Unauthorized' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    return response;
  } catch (error) {
    console.error('Authentication error:', error);
    // Don't expose internal errors to the client
    return new NextResponse(JSON.stringify({ error: 'Authentication error' }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}

// Helper function to check if a path is public
function isPublicPath(pathname: string): boolean {
  return publicPaths.some(path => 
    pathname === path || pathname.startsWith(`${path}/`)
  );
}

// Helper function to check if an API path is public
function isPublicApiPath(pathname: string): boolean {
  return publicApiRoutes.some(route => 
    pathname === route || pathname.startsWith(`${route}/`)
  );
}

// Helper function to add CORS headers
function addCorsHeaders(response: NextResponse, origin: string) {
  response.headers.set('Access-Control-Allow-Origin', origin || '*');
  response.headers.set('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
  response.headers.set('Access-Control-Allow-Headers', 'Content-Type, Authorization');
  response.headers.set('Access-Control-Allow-Credentials', 'true');
}

export const config = {
  matcher: [
    /*
     * Match all request paths except for the ones starting with:
     * - api (API routes)
     * - _next/static (static files)
     * - _next/image (image optimization files)
     * - favicon.ico (favicon file)
     * - public folder
     */
    '/((?!_next/static|_next/image|favicon.ico|public/).*)',
  ],
};
