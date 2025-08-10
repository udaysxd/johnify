import { NextResponse } from 'next/server';
import { Question, VideoRequest, VideoResponse, QuestionOption } from '@/types/video';

// Helper function to get backend URL
function getBackendUrl(): string {
  // Check for environment variable first
  if (process.env.NEXT_PUBLIC_BACKEND_URL) {
    return process.env.NEXT_PUBLIC_BACKEND_URL;
  }
  
  // Default to local development URL
  return 'http://localhost:8000';
}

interface FormattedQuestion extends Omit<Question, 'opts'> {
  opts: Record<string, string>;
}

export async function POST(request: Request) {
  try {
    const { topic, questions, answers } = await request.json() as VideoRequest;
    
    // Format the answers to match backend expectations
    const formattedAnswers: Record<string, string> = {};
    Object.entries(answers).forEach(([questionIndex, answerIndex]) => {
      // Convert numeric answer index to letter (0->'a', 1->'b', etc.)
      const letterAnswer = String.fromCharCode(97 + parseInt(answerIndex, 10));
      formattedAnswers[questionIndex] = letterAnswer;
    });

    // Format questions to ensure they match the expected format
    const formattedQuestions: FormattedQuestion[] = questions.map((q) => {
      const formattedOpts: Record<string, string> = {};
      Object.entries(q.opts || {}).forEach(([key, value]) => {
        formattedOpts[key.toString().toUpperCase()] = String(value);
      });
      
      return {
        ...q,
        a: q.a ? q.a.toString().toLowerCase() : '',
        opts: formattedOpts
      };
    });

    const backendUrl = getBackendUrl();
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 600000); // 10 minute timeout
    
    try {
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
        signal: controller.signal
      });
      
      clearTimeout(timeoutId);
      
      if (!response.ok) {
        const errorText = await response.text();
        console.error('Backend error status:', response.status);
        console.error('Backend error response:', errorText);
        throw new Error(`Backend error: ${response.status} - ${errorText}`);
      }
      
      const data = await response.json() as VideoResponse;
      
      // Ensure the video URLs are absolute if they're not already
      if (data.videos && Array.isArray(data.videos)) {
        data.videos = data.videos.map((video) => ({
          ...video,
          url: video.url.startsWith('http') ? video.url : `${backendUrl}${video.url}`
        }));
      }
      
      console.log('Backend response data:', data);
      return NextResponse.json(data);
      
    } catch (error: unknown) {
      clearTimeout(timeoutId);
      
      if (error instanceof Error) {
        if (error.name === 'AbortError') {
          console.error('Request timed out after 10 minutes');
          return NextResponse.json(
            { 
              error: 'Video generation is taking longer than expected', 
              details: 'The server is still processing your request. Please try again in a few minutes.' 
            },
            { status: 504 }
          );
        }
        throw error; // Re-throw other errors to be caught by the outer catch
      }
      
      throw new Error('An unknown error occurred');
    }
  } catch (error: unknown) {
    console.error('Video generation error:', error);
    const errorMessage = error instanceof Error ? error.message : 'Unknown error occurred';
    
    return NextResponse.json(
      { 
        error: 'Failed to generate video', 
        details: errorMessage
      },
      { status: 500 }
    );
  }
}