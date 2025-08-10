
import { NextResponse } from 'next/server';

export async function POST(request: Request) {
  try {
    const { topic, numQuestions = 10 } = await request.json();
    console.log('Loaded backend URL:', process.env.NEXT_PUBLIC_BACKEND_URL);
    
    // Use backend URL from env or default to localhost
    const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';
    const response = await fetch(`${backendUrl}/generate_quiz`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        topic,
        num_questions: numQuestions
      }),
    });

    if (!response.ok) {
      // Try to extract message for frontend error handling
      let errorMessage = 'Failed to generate quiz';
      try {
        const errorData = await response.json();
        errorMessage = errorData.message || errorData.error || errorMessage;
      } catch {}
      throw new Error(errorMessage);
    }

    const data = await response.json();
    // Always include topic in the response for frontend compatibility
    return NextResponse.json({ ...data, topic });
  } catch (error) {
    console.error('Quiz generation error:', error);
    return NextResponse.json(
      { message: error instanceof Error ? error.message : 'Failed to generate quiz' },
      { status: 500 }
    );
  }
}

