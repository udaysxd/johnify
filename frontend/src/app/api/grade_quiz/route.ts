import { NextResponse } from 'next/server';

export async function POST(request: Request) {
  try {
    const { answers, questions } = await request.json();
    const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';
    const response = await fetch(`${backendUrl}/api/quiz/grade`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ answers, questions }),
    });

    if (!response.ok) {
      let errorMessage = 'Failed to grade quiz';
      try {
        const errorData = await response.json();
        errorMessage = errorData.message || errorData.error || errorMessage;
      } catch {}
      throw new Error(errorMessage);
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Quiz grading error:', error);
    return NextResponse.json(
      { message: error instanceof Error ? error.message : 'Failed to grade quiz' },
      { status: 500 }
    );
  }
}
