import { auth, handlers } from '@/lib/auth';
import { NextResponse, type NextRequest } from 'next/server';

// Extend the session type to include accessToken
declare module 'next-auth' {
  interface Session {
    accessToken?: string;
  }
}

// Helper function to add CORS headers
const addCorsHeaders = (response: NextResponse, origin: string) => {
  // Set CORS headers
  const headers = new Headers(response.headers);
  headers.set('Access-Control-Allow-Origin', origin);
  headers.set('Access-Control-Allow-Methods', 'GET, POST, OPTIONS, DELETE, PUT');
  headers.set('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Requested-With');
  headers.set('Access-Control-Allow-Credentials', 'true');
  headers.set('Vary', 'Origin');
  
  return new NextResponse(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers
  });
};

// Helper to convert Response to NextResponse
const toNextResponse = async (response: Response): Promise<NextResponse> => {
  const headers = new Headers(response.headers);
  const status = response.status;
  const body = await response.text();
  
  // Create a new NextResponse with all headers set in the constructor
  return new NextResponse(body, {
    status,
    statusText: response.statusText,
    headers: Object.fromEntries(headers.entries())
  });
};

// Handle GET requests to /api/auth/*
export const GET = async (req: NextRequest) => {
  try {
    const origin = req.headers.get('origin') || '*';
    const { nextUrl } = req;
    const pathname = nextUrl.pathname;
    
    // Handle session endpoint specifically
    if (pathname.endsWith('/session')) {
      const session = await auth();
      const response = NextResponse.json(session);
      return addCorsHeaders(response, origin);
    }
    
    // For other auth endpoints, use the default NextAuth handler
    const response = await handlers.GET?.(req);
    
    if (!response) {
      return new NextResponse('Not found', { status: 404 });
    }
    
    // Convert Response to NextResponse if needed
    const nextResponse = response instanceof NextResponse 
      ? response 
      : await toNextResponse(response);
      
    return addCorsHeaders(nextResponse, origin);
  } catch (error) {
    console.error('Auth GET error:', error);
    const response = NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
    return addCorsHeaders(response, req.headers.get('origin') || '*');
  }
};

// Handle POST requests to /api/auth/*
export const POST = async (req: NextRequest) => {
  const origin = req.headers.get('origin') || '*';
  
  try {
    const response = await handlers.POST?.(req);
    
    if (!response) {
      return new NextResponse('Not found', { status: 404 });
    }
    
    // Convert Response to NextResponse if needed
    const nextResponse = response instanceof NextResponse 
      ? response 
      : await toNextResponse(response);
      
    return addCorsHeaders(nextResponse, origin);
  } catch (error) {
    console.error('Auth POST error:', error);
    const response = NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
    return addCorsHeaders(response, origin);
  }
};

// Handle OPTIONS requests for CORS preflight
export const OPTIONS = async (req: NextRequest) => {
  const origin = req.headers.get('origin') || '*';
  
  return new NextResponse(null, {
    status: 204,
    headers: {
      'Access-Control-Allow-Origin': origin,
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS, DELETE, PUT',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With',
      'Access-Control-Allow-Credentials': 'true',
      'Vary': 'Origin',
    },
  });
};
