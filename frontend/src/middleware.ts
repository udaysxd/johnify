import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import { jwtVerify } from 'jose';

// This should match your backend's JWT secret
const JWT_SECRET = process.env.JWT_SECRET || 'your-secret-key';

// Verify JWT token
async function verifyToken(token: string, secret: string) {
  try {
    const secretKey = new TextEncoder().encode(secret);
    const { payload } = await jwtVerify(token, secretKey, {
      issuer: 'johnify-backend',
      audience: 'johnify-frontend',
    });
    return { isValid: true, payload };
  } catch (error) {
    console.error('JWT verification failed:', error);
    return { isValid: false, error };
  }
}

// List of public paths that don't require authentication
const publicPaths = [
  '/',
  '/about',
  '/auth/signin',
  '/auth/register',
  '/auth/error',
  '/_next',
  
  // Handle signout separately
  { path: '/auth/signout', method: 'GET' },
  '/favicon.ico',
  '/test-auth',
];

// List of API routes that don't require authentication
const publicApiRoutes = [
  '/api/health',
  '/api/public',
  // Add any other public API endpoints here
];

// Helper function to check if a path is public
function isPublicPath(pathname: string, request: NextRequest): boolean {
  return publicPaths.some(path => 
    typeof path === 'string' 
      ? pathname.startsWith(path) 
      : pathname.startsWith(path.path) && 
        (!path.method || request.method === path.method)
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
  
  // Handle signout - clear cookies and redirect to signin
  if (pathname === '/auth/signout') {
    // Create a redirect response first
    const response = NextResponse.redirect(new URL('/auth/signin', request.url));
    
    // Clear all auth cookies with proper options
    const clearCookie = (name: string, response: NextResponse) => {
      // Root path
      response.cookies.set(name, '', {
        path: '/',
        maxAge: 0,
        httpOnly: true,
        secure: process.env.NODE_ENV === 'production',
        sameSite: 'lax',
      });
      
      // For production, clear with domain
      if (process.env.NODE_ENV === 'production') {
        response.cookies.set(name, '', {
          path: '/',
          domain: '.johnify.com',
          maxAge: 0,
          httpOnly: true,
          secure: true,
          sameSite: 'lax',
        });
      }
    };
    
    // Clear all possible auth cookies
    ['access_token', 'refresh_token', 'session', 'auth_token', 'token'].forEach(
      (cookie) => clearCookie(cookie, response)
    );
    
    // Add headers to prevent caching
    response.headers.set('Cache-Control', 'no-store, max-age=0');
    response.headers.set('Pragma', 'no-cache');
    
    return response;
  }

  // Allow public paths
  if (isPublicPath(pathname, request)) {
    return response;
  }
  
  // For protected pages, check for access token in cookies
  const accessToken = request.cookies.get('access_token')?.value;
  
  // If no access token, redirect to signin
  if (!accessToken) {
    const signInUrl = new URL('/auth/signin', request.url);
    signInUrl.searchParams.set('callbackUrl', pathname);
    return NextResponse.redirect(signInUrl);
  }
  
  // Verify the JWT token
  const { isValid } = await verifyToken(accessToken, JWT_SECRET);
  
  // If token is invalid, clear cookies and redirect to signin
  if (!isValid) {
    console.log('Invalid or expired token, redirecting to signin');
    const response = NextResponse.redirect(new URL('/auth/signin', request.url));
    
    // Clear cookies using the correct syntax
    const cookieOptions = { path: '/' };
    response.cookies.set('access_token', '', { ...cookieOptions, maxAge: 0 });
    response.cookies.set('refresh_token', '', { ...cookieOptions, maxAge: 0 });
    
    // Also clear domain-specific cookies in production
    if (process.env.NODE_ENV === 'production') {
      const domainOptions = { ...cookieOptions, domain: '.johnify.com' };
      response.cookies.set('access_token', '', { ...domainOptions, maxAge: 0 });
      response.cookies.set('refresh_token', '', { ...domainOptions, maxAge: 0 });
    }
    
    return response;
  }
  
  return response;
}

export const config = {
  matcher: [
    /*
     * Match all request paths except for the ones starting with:
     * - _next/static (static files)
     * - _next/image (image optimization files)
     * - favicon.ico (favicon file)
     * - public/ (public files)
     * - api/auth/ (auth API routes)
     * - auth/ (auth pages)
     * - about (about page)
     * - _next (Next.js internals)
     */
    '/((?!_next/static|_next/image|favicon.ico|public/|api/auth/|auth/|about|_next).*)',
    
    // Match all API routes except auth
    '/api/:path*',
  ],
};
