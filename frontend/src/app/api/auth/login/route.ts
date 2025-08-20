import { NextRequest, NextResponse } from 'next/server';

export async function POST(request: NextRequest) {
  try {
    // Log all environment variables (except sensitive ones) for debugging
    console.log('Login - Environment variables:', {
      nodeEnv: process.env.NODE_ENV,
      vercel: process.env.VERCEL,
      allEnvKeys: Object.keys(process.env).filter(key => 
        key.startsWith('NEXT_') || 
        key.startsWith('VERCEL_') ||
        key === 'NODE_ENV'
      ).reduce((obj, key) => ({
        ...obj,
        [key]: key.includes('SECRET') || key.includes('TOKEN') ? '***' : process.env[key]
      }), {})
    });

    // Forward the body and headers as-is (form-urlencoded) to the backend
    const isProduction = process.env.NODE_ENV === 'production';
    const backendUrl = isProduction
      ? 'https://johnify-backend-873155673176.us-central1.run.app'
      : process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';

    if (!backendUrl) {
      return NextResponse.json(
        { error: 'Server configuration error: Backend URL not set' },
        { status: 500 }
      );
    }

    const backendEndpoint = `${backendUrl}/api/auth/login`;
    // Get the raw body and content-type
    const body = await request.text();
    const contentType = request.headers.get('content-type') || 'application/x-www-form-urlencoded';

    try {
      const backendResponse = await fetch(backendEndpoint, {
        method: 'POST',
        headers: {
          'Content-Type': contentType,
          'Accept': 'application/json',
        },
        body,
        credentials: 'include',
      });

      const responseText = await backendResponse.text();
      let data;
      
      try {
        data = responseText ? JSON.parse(responseText) : {};
      } catch (e) {
        console.error('Failed to parse backend response:', responseText);
        throw new Error('Invalid response from backend');
      }

      if (!backendResponse.ok) {
        console.error('Backend error:', data);
        return NextResponse.json(
          { 
            error: data.detail || data.message || 'Login failed',
            details: process.env.NODE_ENV === 'development' ? data : undefined
          },
          { status: backendResponse.status }
        );
      }

      // Create a response with the token and user data
      const responseData = {
        access_token: data.access_token,
        token_type: data.token_type,
        user: {
          user_id: data.user?.user_id || '',
          user_email: data.user?.user_email || '',
          user_name: data.user?.user_name || '',
          is_verified: data.user?.is_verified || false,
          uuid: data.user?.uuid || ''
        },
        expires_in: data.expires_in || 3600, // Default to 1 hour if not provided
        expires_at: data.expires_at || Math.floor(Date.now() / 1000) + 3600 // Default to 1 hour from now
      };

      // Create a response with the data
      const response = NextResponse.json(responseData);

      // Explicitly set the auth cookie from the payload to ensure browser stores it
      if (data.access_token) {
        const isProduction = process.env.NODE_ENV === 'production';
        // In development on http://localhost cookies cannot be Secure or SameSite=None
        // Use secure=false and SameSite=Lax locally; production uses Secure+None for cross-site
        const isLocalhost = process.env.NODE_ENV !== 'production';
        response.cookies.set('access_token', data.access_token, {
          httpOnly: true,
          secure: !isLocalhost, // true in production, false in development
          sameSite: isLocalhost ? 'lax' : 'none',
          path: '/',
          // Only set domain in production; in dev let browser default to localhost
          domain: isLocalhost ? undefined : '.johnify.com',
          // 7 days
          maxAge: 60 * 60 * 24 * 7,
        });
      }

      return response;
    } catch (error: unknown) {
      console.error('Error in login route:', error);
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      return NextResponse.json(
        { 
          error: 'Failed to process login',
          details: process.env.NODE_ENV === 'development' ? errorMessage : undefined
        },
        { status: 500 }
      );
    }
  } catch (error) {
    console.error('Login error:', error);
    const errorMessage = error instanceof Error ? error.message : 'An unknown error occurred';
    console.error('Error details:', {
      message: errorMessage,
      stack: error instanceof Error ? error.stack : undefined,
      backendUrl: process.env.NEXT_PUBLIC_BACKEND_URL,
      nodeEnv: process.env.NODE_ENV
    });
    
    return NextResponse.json(
      { 
        error: 'An error occurred during login',
        details: process.env.NODE_ENV === 'development' ? errorMessage : undefined
      },
      { status: 500 }
    );
  }
}
