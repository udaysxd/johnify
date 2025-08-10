import { NextResponse } from 'next/server';
import { NextRequest } from 'next/server';

export async function POST(request: NextRequest) {
  try {
    // Get the credentials from the request
    const formData = await request.formData();
    const credentials = {
      username: formData.get('username') as string,
      password: formData.get('password') as string,
    };

    if (!credentials.username || !credentials.password) {
      return NextResponse.json(
        { error: 'Missing credentials' },
        { status: 400 }
      );
    }

    try {
      // Call your backend API to validate credentials with form-encoded data
      const formData = new URLSearchParams();
      formData.append('username', credentials.username);
      formData.append('password', credentials.password);
      
      // Log the request details for debugging
      const loginUrl = `${process.env.NEXT_PUBLIC_API_URL}/api/auth/login`;
      console.log('Making login request to:', loginUrl);
      
      // Call the backend login endpoint
      const authResponse = await fetch(loginUrl, {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/x-www-form-urlencoded',
          'Accept': 'application/json',
        },
        body: formData.toString(),
        credentials: 'include'
      });
      
      // Get the response text first
      const responseText = await authResponse.text();
      console.log('Raw response:', responseText.substring(0, 500));
      
      // Try to parse as JSON
      let responseData;
      try {
        responseData = JSON.parse(responseText);
      } catch (e) {
        console.error('Failed to parse response as JSON:', e);
        return NextResponse.json(
          { 
            error: 'Invalid response format from server',
            details: 'The server returned an invalid JSON response',
            rawResponse: responseText.substring(0, 200) + (responseText.length > 200 ? '...' : '')
          },
          { status: 500 }
        );
      }
      
      // Handle error responses
      if (!authResponse.ok) {
        return NextResponse.json(
          { 
            error: responseData.detail || 'Authentication failed',
            status: authResponse.status
          },
          { status: authResponse.status }
        );
      }
      
      // Handle successful authentication
      if (!responseData.access_token) {
        return NextResponse.json(
          { error: 'Authentication successful but no access token received' },
          { status: 500 }
        );
      }
      
      // Get the redirect URL
      const url = new URL(request.url);
      const callbackUrl = url.searchParams.get('callbackUrl') || '/dashboard';
      
      // Create a redirect response
      const redirectUrl = new URL(callbackUrl, request.url);
      const response = NextResponse.redirect(redirectUrl);
      
      // Set the session cookie
      response.cookies.set({
        name: 'next-auth.session-token',
        value: responseData.access_token,
        httpOnly: true,
        secure: process.env.NODE_ENV === 'production',
        sameSite: 'lax',
        path: '/',
        maxAge: 30 * 24 * 60 * 60 // 30 days
      });
      
      return response;
      
    } catch (error) {
      console.error('Authentication error:', error);
      return NextResponse.json(
        { 
          error: 'Authentication failed', 
          details: error instanceof Error ? error.message : 'Unknown error' 
        },
        { status: 500 }
      );
    }
  } catch (error) {
    console.error('Request processing error:', error);
    return NextResponse.json(
      { 
        error: 'Request processing failed', 
        details: error instanceof Error ? error.message : 'Unknown error' 
      },
      { status: 500 }
    );
  }
}

export const dynamic = 'force-dynamic';
