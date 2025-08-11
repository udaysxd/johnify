import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

// List of public paths that don't require authentication
const publicPaths = [
  '/',
  '/about',
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
  '/api/auth/session',  // Keep for backward compatibility
  '/api/auth/csrf',     // Keep for backward compatibility
  '/api/auth/signin',   // Keep for backward compatibility
  '/api/auth/signout',  // Keep for backward compatibility
];

// Helper function to check if a path is public
function isPublicPath(pathname: string): boolean {
  return publicPaths.some(path => 
    pathname === path || 
    pathname.startsWith(`${path}/`) ||
    pathname.startsWith('/_next/') ||
    pathname.startsWith('/api/') ||
    pathname.match(/\.[^/]+$/) // Match any file with an extension
  );
}

// Helper function to check if an API path is public
function isPublicApiPath(pathname: string): boolean {
  return publicApiRoutes.some(route => 
    pathname === route || 
    pathname.startsWith(`${route}/`)
  );
}

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const origin = request.headers.get('origin') || '';
  
  // Add CORS headers for all responses
  const response = NextResponse.next();
  
  // Set CORS headers
  response.headers.set('Access-Control-Allow-Origin', origin || '*');
  response.headers.set('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
  response.headers.set('Access-Control-Allow-Headers', 'Content-Type, Authorization');
  response.headers.set('Access-Control-Allow-Credentials', 'true');
  
  // Handle preflight requests
  if (request.method === 'OPTIONS') {
    return new NextResponse(null, { 
      status: 200, 
      headers: {
        'Access-Control-Allow-Origin': origin || '*',
        'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, Authorization',
        'Access-Control-Allow-Credentials': 'true',
      } 
    });
  }
  
  // Allow all API routes for now - we'll handle auth at the API route level
  if (pathname.startsWith('/api/')) {
    return response;
  }
  
  // Allow public paths
  if (isPublicPath(pathname)) {
    return response;
  }
  
  // For protected pages, check for auth token in cookies
  const authToken = request.cookies.get('auth_token')?.value;
  
  // If no auth token, redirect to signin
  if (!authToken) {
    const signInUrl = new URL('/auth/signin', request.url);
    signInUrl.searchParams.set('callbackUrl', pathname);
    return NextResponse.redirect(signInUrl);
  }
  
  return response;
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
