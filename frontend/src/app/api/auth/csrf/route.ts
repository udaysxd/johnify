import { NextResponse } from 'next/server';
import { getToken } from 'next-auth/jwt';

export async function GET() {
  try {
    // This is a simplified CSRF token endpoint
    // In a production app, you'd want to implement proper CSRF protection
    return NextResponse.json({ csrfToken: 'dummy-csrf-token' });
  } catch (error) {
    console.error('CSRF token error:', error);
    return NextResponse.json(
      { error: 'Failed to generate CSRF token' },
      { status: 500 }
    );
  }
}
