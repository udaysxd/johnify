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
      // Normalize backend error into a readable string and optional list
      let errorMessage = 'Registration failed';
      let errors: string[] | undefined = undefined;
      if (registerData) {
        if (typeof registerData.detail === 'string') {
          errorMessage = registerData.detail;
        } else if (Array.isArray(registerData.detail)) {
          // FastAPI/Pydantic validation style: detail is an array of { loc, msg, type }
          try {
            const msgs = registerData.detail
              .map((it: { msg?: unknown }) => (typeof it?.msg === 'string' ? (it.msg as string) : ''))
              .filter((s: string) => !!s);
            if (msgs.length) {
              errors = msgs;
              errorMessage = msgs.join(', ');
            }
          } catch {}
        } else if (registerData.detail && typeof registerData.detail === 'object') {
          const d = registerData.detail as { message?: string; errors?: string[] };
          errorMessage = d.message || errorMessage;
          if (Array.isArray(d.errors) && d.errors.length) {
            errors = d.errors;
            errorMessage = `${errorMessage}: ${d.errors.join(', ')}`;
          }
        } else if (typeof registerData.error === 'string') {
          errorMessage = registerData.error;
        } else if (registerData.detail && typeof registerData.detail !== 'string') {
          // Handle case where detail exists but is not a string (e.g., object that got stringified)
          errorMessage = 'Email already registered';
        }
      }
      return NextResponse.json(
        { error: String(errorMessage), errors },
        { status: registerResponse.status }
      );
    }

    // Registration succeeded: do not attempt auto-login.
    // Instruct the user to verify their email address instead.
    return NextResponse.json({
      message: 'Please check your email and verify your email.'
    }, { status: 200 });

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

