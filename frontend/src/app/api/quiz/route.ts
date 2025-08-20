
import { NextResponse } from 'next/server';

export async function POST(request: Request) {
  try {
    const { topic, numQuestions = 10 } = await request.json();
    
    // Resolve backend URL with safe production fallback
    const isProduction = process.env.NODE_ENV === 'production';
    const envUrl = process.env.NEXT_PUBLIC_BACKEND_URL;
    const backendUrl = (envUrl && envUrl.trim())
      ? envUrl
      : (isProduction
          ? 'https://johnify-backend-873155673176.us-central1.run.app'
          : 'http://localhost:8000');
    
    // Forward the request to the backend with credentials
    const response = await fetch(`${backendUrl}/api/quiz/generate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        // Forward necessary headers from the original request
        ...(request.headers.get('authorization') && {
          'Authorization': request.headers.get('authorization') || ''
        })
      },
      credentials: 'include', // Important for cookies
      body: JSON.stringify({
        topic,
        num_questions: numQuestions
      }),
    });

    if (!response.ok) {
      // Try to extract error message from the response
      let errorMessage = 'Failed to generate quiz';
      try {
        const errorData = await response.json();
        errorMessage = errorData.detail || errorData.message || errorData.error || errorMessage;
      } catch (e) {
        console.error('Error parsing error response:', e);
      }
      
      // Return appropriate status code and error message
      return NextResponse.json(
        { message: errorMessage },
        { status: response.status }
      );
    }

    const data = await response.json();
    // Include topic in the response for frontend compatibility
    return NextResponse.json({ ...data, topic });
  } catch (error) {
    console.error('Quiz generation error:', error);
    return NextResponse.json(
      { 
        message: error instanceof Error ? error.message : 'An unexpected error occurred',
        code: 'INTERNAL_SERVER_ERROR'
      },
      { status: 500 }
    );
  }
}

