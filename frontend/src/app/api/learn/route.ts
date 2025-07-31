import { NextResponse } from 'next/server';

interface LearnRequest {
  topic: string;
  complexity_level?: number;
}

// Helper function to get backend URL
function getBackendUrl() {
  // Check for environment variable first
  if (process.env.NEXT_PUBLIC_BACKEND_URL) {
    return process.env.NEXT_PUBLIC_BACKEND_URL;
  }
  
  // Default to local development URL
  return 'http://localhost:8000';
}

export async function POST(request: Request) {
  try {
    const { topic, complexity_level = 3 } = await request.json() as LearnRequest;
    
    if (!topic) {
      return NextResponse.json(
        { error: 'Topic is required' },
        { status: 400 }
      );
    }

    const backendUrl = getBackendUrl();
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 600000); // 10 minute timeout
    
    try {
      const response = await fetch(`${backendUrl}/learn`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          topic,
          complexity_level: Math.min(5, Math.max(1, complexity_level || 3)) // Ensure between 1-5
        }),
        signal: controller.signal
      });

      clearTimeout(timeoutId);

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        return NextResponse.json(
          { 
            error: 'Failed to generate learning video',
            details: errorData.message || response.statusText
          },
          { status: response.status }
        );
      }

      const data = await response.json();
      return NextResponse.json(data);
      
    } catch (error) {
      clearTimeout(timeoutId);
      if (error.name === 'AbortError') {
        return NextResponse.json(
          { error: 'Request timed out. Please try again.' },
          { status: 504 }
        );
      }
      throw error;
    }
    
  } catch (error) {
    console.error('Error in /api/learn:', error);
    return NextResponse.json(
      { 
        error: 'Internal server error',
        details: process.env.NODE_ENV === 'development' ? error.message : undefined
      },
      { status: 500 }
    );
  }
}
