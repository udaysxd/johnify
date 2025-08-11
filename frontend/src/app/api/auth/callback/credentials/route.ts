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

    // Prepare form data for the backend
    const formDataToSend = new URLSearchParams();
    formDataToSend.append('username', credentials.username);
    formDataToSend.append('password', credentials.password);
    
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
      body: formDataToSend.toString(),
      credentials: 'include'
    });
    
    // Get the response text first
    const responseText = await authResponse.text();
    console.log('Raw response:', responseText);
    
    // Try to parse as JSON
    let responseData;
    try {
      responseData = JSON.parse(responseText);
    } catch (parseError) {
      console.error('Failed to parse response as JSON:', parseError);
      return NextResponse.json(
        { 
          error: 'Invalid response from authentication server',
          details: 'The server returned an invalid JSON response.',
          response: responseText.substring(0, 500)
        },
        { status: 500 }
      );
    }

    // Check if the response indicates success
    if (!authResponse.ok) {
      console.error('Authentication failed:', responseData);
      return NextResponse.json(
        { 
          error: responseData.detail || 'Authentication failed',
          status: authResponse.status 
        },
        { status: authResponse.status }
      );
    }

    // If we get here, authentication was successful
    // Return the token and user information
    return NextResponse.json({
      user: {
        id: '1',
        name: credentials.username,
        email: credentials.username,
      },
      accessToken: responseData.access_token,
      refreshToken: responseData.refresh_token || '',
      expiresIn: 24 * 60 * 60, // 24 hours
    });

  } catch (error) {
    console.error('Authentication error:', error);
    return NextResponse.json(
      { 
        error: 'An unexpected error occurred during authentication',
        details: error instanceof Error ? error.message : 'Unknown error'
      },
      { status: 500 }
    );
  }
}

export const dynamic = 'force-dynamic';
