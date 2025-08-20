import { NextRequest, NextResponse } from 'next/server';

// Helper function to safely clone and parse JSON responses
async function parseResponse(response: Response) {
  try {
    const clone = response.clone();
    const contentType = clone.headers.get('content-type') || '';
    // Prefer JSON when content-type indicates JSON
    const text = await clone.text();
    if (contentType.includes('application/json')) {
      try {
        return text ? JSON.parse(text) : {};
      } catch (e) {
        console.error('Failed to parse JSON body, returning text:', e);
        return { error: 'Invalid JSON from backend', detail: text };
      }
    }
    // Not JSON: return as text payload for better diagnostics
    return { error: 'Non-JSON response from backend', detail: text };
  } catch (e) {
    console.error('Failed to parse response:', e);
    return {};
  }
}

export async function POST(request: NextRequest) {
  try {
    // Resolve backend URL
    const isProduction = process.env.NODE_ENV === 'production';
    const backendUrl = isProduction
      ? 'https://johnify-backend-873155673176.us-central1.run.app'
      : process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';
    
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
    const registerData = await parseResponse(registerResponse);
    if (!registerResponse.ok) {
      console.error('Registration failed:', registerData);
      // Return the error from the backend
      return NextResponse.json(
        registerData,
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
      body: loginPayload.toString(),
      credentials: 'include',
    });

    // Handle login response
    const loginData = await parseResponse(loginResponse);
    if (!loginResponse.ok) {
      console.error('Login after registration failed:', loginData);
      // Return the error from the backend
      return NextResponse.json(
        loginData,
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
      // Parse cookie name and value
      const cookieParts = setCookieHeader.split(';');
      const [cookieNameValue, ...rest] = cookieParts;
      const [cookieName, cookieValue] = cookieNameValue.split('=');

      response.cookies.set({
        name: cookieName.trim(),
        value: cookieValue,
        httpOnly: true,
        secure: isProduction,
        sameSite: isProduction ? 'none' : 'lax',
        path: '/',
        maxAge: loginData.expires_in || 3600,
        domain: isProduction ? '.johnify.com' : undefined
      });
    }

    return response;

  } catch (error) {
    console.error('Error in register route:', error);
    const errorMessage = error instanceof Error ? error.message : 'Unknown error';
    
    console.error('Error details:', {
      message: errorMessage,
      backendUrl: process.env.NEXT_PUBLIC_BACKEND_URL,
      nodeEnv: process.env.NODE_ENV
    });
    
    return NextResponse.json(
      { 
        error: 'An error occurred during registration',
        details: process.env.NODE_ENV === 'development' ? errorMessage : undefined
      },
      { status: 500 }
    );
  }
}

