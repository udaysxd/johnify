import { NextResponse } from 'next/server';
import { getToken } from 'next-auth/jwt';

export async function POST(request: Request) {
  try {
    const response = NextResponse.json(
      { success: true, message: 'Successfully signed out' },
      { status: 200 }
    );
    
    // Clear all possible auth cookies
    const cookieNames = [
      'next-auth.session-token',
      '__Secure-next-auth.session-token',
      'next-auth.callback-url',
      'next-auth.csrf-token',
      'next-auth.callback-url',
      '__Secure-next-auth.callback-url',
      'next-auth.session-token',
      '__Secure-next-auth.session-token'
    ];

    // Delete all auth-related cookies
    cookieNames.forEach(cookieName => {
      response.cookies.set({
        name: cookieName,
        value: '',
        path: '/',
        expires: new Date(0), // Expire immediately
        httpOnly: true,
        secure: process.env.NODE_ENV === 'production',
        sameSite: 'lax'
      });
    });

    // Clear any session data in localStorage
    if (typeof window !== 'undefined') {
      localStorage.removeItem('nextauth.message');
      localStorage.removeItem('nextauth.user');
      sessionStorage.clear();
    }
    
    return response;
  } catch (error) {
    console.error('Signout error:', error);
    return NextResponse.json(
      { error: 'Failed to sign out', success: false },
      { status: 500 }
    );
  }
}
