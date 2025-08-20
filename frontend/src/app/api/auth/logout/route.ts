import { NextResponse } from 'next/server';

export async function POST() {
  try {
    // Create a response with success message
    const response = NextResponse.json(
      { message: 'Successfully logged out' },
      { status: 200 }
    );

    // Clear all auth cookies
    const clearCookie = (name: string) => {
      const isProd = process.env.NODE_ENV === 'production';
      // Clear host-only cookie (in case it was set without Domain)
      response.cookies.set({
        name,
        value: '',
        expires: new Date(0),
        path: '/',
        httpOnly: true,
        secure: isProd,
        sameSite: isProd ? 'none' : 'lax',
      });

      // Also clear domain cookie used in production logins
      if (isProd) {
        response.cookies.set({
          name,
          value: '',
          expires: new Date(0),
          path: '/',
          httpOnly: true,
          secure: true,
          sameSite: 'none',
          domain: '.johnify.com',
        });
      }
    };

    // Clear all possible auth cookies
    ['access_token', 'refresh_token', 'session', 'auth_token', 'token'].forEach(clearCookie);

    return response;
  } catch (error) {
    console.error('Logout error:', error);
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
  }
}

export const dynamic = 'force-dynamic';
