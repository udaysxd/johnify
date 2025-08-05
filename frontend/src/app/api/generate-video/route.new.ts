import { NextResponse } from 'next/server';

interface QuestionOption {
  [key: string]: string;
}

interface Question {
  q: string;
  a: string;
  opts: QuestionOption;
  [key: string]: unknown; // For any additional properties
}

interface VideoRequest {
  topic: string;
  questions: Question[];
  answers: Record<string, string>;
}

interface VideoResponse {
  videoUrl?: string;
  video_url?: string; // For backward compatibility
  [key: string]: unknown; // For any additional properties
}

// Helper function to get backend URL
function getBackendUrl() {
  // Check for environment variable first
  if (process.env.NEXT_PUBLIC_BACKEND_URL) {
    // Ensure no trailing slash
    return process.env.NEXT_PUBLIC_BACKEND_URL.replace(/\/$/, '');
  }
  
  // Default to local development URL
  return 'http://localhost:8000';
}

export async function POST(request: Request) {
  try {
    const { topic, questions, answers } = await request.json() as VideoRequest;
    
    // Format the answers to match backend expectations
    const formattedAnswers: Record<string, string> = {};
    Object.entries(answers).forEach(([questionIndex, answerIndex]) => {
      // Convert numeric answer index to letter (0->'a', 1->'b', etc.)
      const letterAnswer = String.fromCharCode(97 + parseInt(answerIndex as string));
      formattedAnswers[questionIndex] = letterAnswer;
    });

    // Format questions to ensure they match the expected format
    const formattedQuestions = questions.map((q) => ({
      ...q,
      a: q.a.toString().toLowerCase(),
      opts: Object.fromEntries(
        Object.entries(q.opts).map(([key, value]) => [key.toString().toUpperCase(), value])
      )
    }));

    const backendUrl = getBackendUrl();
    console.log(`Sending request to backend: ${backendUrl}/generate-video`);
    
    const response = await fetch(`${backendUrl}/generate-video`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        topic,
        questions: formattedQuestions,
        answers: formattedAnswers
      }),
      credentials: 'include',
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error('Backend error status:', response.status);
      console.error('Backend error response:', errorText);
      throw new Error(`Backend error: ${response.status} - ${errorText}`);
    }

    const data = await response.json();
    console.log('Raw backend response:', JSON.stringify(data, null, 2));
    
    // Normalize the response to use camelCase and ensure video URL is absolute
    const normalizedResponse: VideoResponse = { ...data };
    
    // Handle both snake_case and camelCase video URL fields
    const videoUrl = data.video_url || data.videoUrl;
    
    if (videoUrl) {
      // Convert to absolute URL if it's not already
      const absoluteUrl = videoUrl.startsWith('http')
        ? videoUrl
        : `${backendUrl}${videoUrl.startsWith('/') ? '' : '/'}${videoUrl}`;
      
      // Always use camelCase in the response
      normalizedResponse.videoUrl = absoluteUrl;
      
      // Remove snake_case version if it exists
      if ('video_url' in normalizedResponse) {
        delete normalizedResponse.video_url;
      }
      
      console.log('Generated video URL:', absoluteUrl);
    }
    
    return NextResponse.json(normalizedResponse);
    
  } catch (error: unknown) {
    console.error('Video generation error:', error);
    return NextResponse.json(
      { 
        error: 'Failed to generate video', 
        details: error instanceof Error ? error.message : 'Unknown error occurred',
        stack: process.env.NODE_ENV === 'development' && error instanceof Error ? error.stack : undefined
      },
      { status: 500 }
    );
  }
}

// Enable CORS preflight
export async function OPTIONS() {
  return new Response(null, {
    status: 204,
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    },
  });
}
