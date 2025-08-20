import { NextResponse } from 'next/server';

// Helper function to safely parse JSON responses
async function handleResponse(response: Response) {
  try {
    return await response.json();
  } catch (e) {
    console.error('Failed to parse response:', e);
    return {};
  }
}

export async function POST(request: Request) {
  try {
    const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';
    
    console.log('Register - Running in', process.env.NODE_ENV, 'mode');
    console.log('Using backend URL:', backendUrl);

    // Parse request data
    const requestData = await request.json();
    const { user_email, password, user_name } = requestData;

    if (!user_email || !password) {
      return NextResponse.json(
        { error: 'Email and password are required' },
        { status: 400 }
      );
    }

    // 1. Make registration request
    console.log('Registering user:', user_email);
    const registerResponse = await fetch(`${backendUrl}/api/auth/register`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify({
        user_name: user_name?.trim() || user_email.split('@')[0],
        user_email: user_email.trim(),
        password: password,
      }),
      credentials: 'include',
    });

    // Handle registration response
    const registerData = await handleResponse(registerResponse);
    if (!registerResponse.ok) {
      console.error('Registration failed:', registerData);
      return NextResponse.json(
        { 
          error: registerData.detail || registerData.message || 'Registration failed',
          details: process.env.NODE_ENV === 'development' ? registerData : undefined
        },
        { status: registerResponse.status }
      );
    }

    console.log('Registration successful, attempting login...');
    
    // 2. If registration was successful, log the user in
    const loginPayload = new URLSearchParams({
      username: user_email.trim(),
      password: password,
    });
    console.log('Login payload after registration (form):', loginPayload.toString());
    const loginResponse = await fetch(`${backendUrl}/api/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json',
      },
      body: loginPayload,
      credentials: 'include',
    });

    // Handle login response
    const loginData = await handleResponse(loginResponse);
    if (!loginResponse.ok) {
      console.error('Login after registration failed:', loginData);
      return NextResponse.json(
        { 
          error: loginData.detail || loginData.message || 'Registration successful but login failed',
          details: process.env.NODE_ENV === 'development' ? loginData : undefined
        },
        { status: loginResponse.status }
      );
    }

    // 3. Prepare the success response
    const responseData = {
      access_token: loginData.access_token,
      token_type: loginData.token_type || 'bearer',
      user: {
        user_id: loginData.user_id || loginData.user?.user_id,
        user_email: loginData.user_email || loginData.user?.user_email,
        user_name: loginData.user_name || loginData.user?.user_name || user_name || user_email.split('@')[0],
        is_verified: loginData.is_verified || loginData.user?.is_verified || false,
        uuid: loginData.uuid || loginData.user?.uuid || ''
      },
      expires_in: loginData.expires_in || 3600,
      expires_at: loginData.expires_at || Math.floor(Date.now() / 1000) + 3600
    };

    // 4. Create the response
    const response = NextResponse.json(responseData);
    
    // 5. Handle cookies from login response
    const setCookieHeader = loginResponse.headers.get('set-cookie');
    if (setCookieHeader) {
      const cookieName = setCookieHeader.split('=')[0];
      const cookieValue = setCookieHeader
        .split('; ')[0]
        .split('=')[1];
      
      response.cookies.set({
        name: cookieName,
        value: cookieValue,
        httpOnly: true,
        secure: process.env.NODE_ENV === 'production',
        sameSite: 'lax',
        path: '/',
        maxAge: loginData.expires_in || 3600,
        domain: process.env.NODE_ENV === 'production' ? '.johnify.com' : undefined
      });
    }

    return response;

  } catch (error) {
    console.error('Error in register route:', error);
    const errorMessage = error instanceof Error ? error.message : 'Unknown error';
    return NextResponse.json(
      { 
        error: 'Internal server error',
        details: process.env.NODE_ENV === 'development' ? errorMessage : undefined
      },
      { status: 500 }
    );
  }
}

export const dynamic = 'force-dynamic';
