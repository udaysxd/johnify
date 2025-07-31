import { NextResponse } from 'next/server';

export async function POST(request: Request) {
  try {
    const { user_name, user_email, password } = await request.json();
    
    // Validate input
    if (!user_name || !user_email || !password) {
      return NextResponse.json(
        { error: 'Missing required fields' },
        { status: 400 }
      );
    }

    const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/auth/register`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        user_name,
        user_email,
        password,
      }),
    });

    let data;
    try {
      const text = await response.text();
      data = text ? JSON.parse(text) : {};
    } catch (e) {
      console.error('Failed to parse response as JSON:', e);
      return NextResponse.json(
        { error: 'Invalid response from server', details: 'The server returned an invalid response' },
        { status: 500 }
      );
    }

    if (!response.ok) {
      console.error('Registration failed:', {
        status: response.status,
        statusText: response.statusText,
        data
      });
      
      return NextResponse.json(
        { 
          error: data.detail || 'Registration failed',
          details: data.detail || 'Unknown error occurred',
          status: response.status 
        },
        { status: response.status }
      );
    }

    return NextResponse.json(data, { status: 201 });
  } catch (error) {
    console.error('Registration error:', error);
    return NextResponse.json(
      { 
        error: 'Internal server error',
        details: error instanceof Error ? error.message : 'Unknown error occurred'
      },
      { status: 500 }
    );
  }
}
