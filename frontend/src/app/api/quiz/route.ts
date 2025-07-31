
import { NextResponse } from 'next/server';

export async function POST(request: Request) {
  try {
    const { topic, numQuestions = 10 } = await request.json();
    
    const response = await fetch('http://localhost:8000/generate_quiz', {
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
      const error = await response.text();
      throw new Error(error);
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Quiz generation error:', error);
    return NextResponse.json(
      { error: 'Failed to generate quiz' },
      { status: 500 }
    );
  }
}

