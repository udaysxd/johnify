import { NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const isProduction = process.env.NODE_ENV === 'production';
const API_BASE_URL = isProduction
  ? (process.env.BACKEND_URL || 'https://johnify-backend-873155673176.us-central1.run.app')
  : (process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000');

// Helper function to handle errors
function createErrorResponse(message: string, status: number, details?: unknown): NextResponse {
  console.error(`[API Error] ${message}`, details || '');
  
  const responseBody: { error: string; details?: unknown } = { error: message };
  if (details !== undefined) {
    responseBody.details = details;
  }
  
  return new NextResponse(
    JSON.stringify(responseBody), 
    { 
      status,
      headers: {
        'Content-Type': 'application/json',
      },
    }
  );
}

export async function POST(request: Request): Promise<NextResponse> {
  try {
    // Get the auth token from cookies
    const cookieStore = await cookies();
    const accessToken = cookieStore.get('access_token')?.value || cookieStore.get('auth_token')?.value;
    
    if (!accessToken) {
      return createErrorResponse('Authentication required', 401);
    }
    
    try {
      // Forward the multipart form data to the backend
      const formData = await request.formData();
      
      const backendResponse = await fetch(`${API_BASE_URL}/api/videos/upload`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${accessToken}`,
        },
        body: formData,
      });

      if (!backendResponse.ok) {
        const errorData = await backendResponse.json().catch(() => ({}));
        console.error('Error uploading video to backend:', errorData);
        return createErrorResponse(
          errorData.detail || 'Failed to upload video',
          backendResponse.status
        );
      }

      const data = await backendResponse.json();
      return NextResponse.json(data);
      
    } catch (error) {
      console.error('Error in videos upload API route:', error);
      return createErrorResponse(
        'Failed to upload video', 
        500, 
        error instanceof Error ? error.message : 'Unknown error'
      );
    }
    
  } catch (error) {
    console.error('Unexpected error in videos upload API route:', error);
    return createErrorResponse(
      'Internal server error', 
      500, 
      error instanceof Error ? error.message : 'Unknown error'
    );
  }
}
