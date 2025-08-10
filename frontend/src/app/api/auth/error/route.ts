import { NextResponse } from 'next/server';

export async function GET() {
  try {
    // Return a basic error response
    return NextResponse.json(
      { error: 'Authentication error', ok: false },
      { status: 401 }
    );
  } catch (error) {
    console.error('Error in auth error endpoint:', error);
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
  }
}
