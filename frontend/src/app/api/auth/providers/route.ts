import { NextResponse } from 'next/server';

export async function GET() {
  try {
    // Return a basic providers configuration
    return NextResponse.json({
      credentials: {
        id: 'credentials',
        name: 'Credentials',
        type: 'credentials',
        authorize: null,
        credentials: {
          email: { label: 'Email', type: 'email' },
          password: { label: 'Password', type: 'password' }
        }
      }
    });
  } catch (error) {
    console.error('Error getting auth providers:', error);
    return NextResponse.json(
      { error: 'Failed to get authentication providers' },
      { status: 500 }
    );
  }
}
