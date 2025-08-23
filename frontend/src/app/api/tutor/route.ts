import { NextResponse } from 'next/server';

// Tutor API route: independent copy of quiz route
export async function POST(request: Request) {
  try {
    const { topic, numQuestions = 10 } = await request.json();

    const isProduction = process.env.NODE_ENV === 'production';
    const envUrl = process.env.NEXT_PUBLIC_BACKEND_URL;
    const backendUrl = (envUrl && envUrl.trim())
      ? envUrl
      : (isProduction
          ? 'https://johnify-backend-873155673176.us-central1.run.app'
          : 'http://localhost:8000');

    const response = await fetch(`${backendUrl}/api/quiz/generate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(request.headers.get('authorization') && {
          'Authorization': request.headers.get('authorization') || ''
        })
      },
      credentials: 'include',
      body: JSON.stringify({ topic, num_questions: numQuestions }),
    });

    if (!response.ok) {
      let errorMessage = 'Failed to generate tutor quiz';
      try {
        const errorData = await response.json();
        errorMessage = errorData.detail || errorData.message || errorData.error || errorMessage;
      } catch (e) {
        console.error('Error parsing error response:', e);
      }
      return NextResponse.json({ message: errorMessage }, { status: response.status });
    }

    const data = await response.json();
    return NextResponse.json({ ...data, topic });
  } catch (error) {
    console.error('Tutor generation error:', error);
    return NextResponse.json(
      {
        message: error instanceof Error ? error.message : 'An unexpected error occurred',
        code: 'INTERNAL_SERVER_ERROR'
      },
      { status: 500 }
    );
  }
}
