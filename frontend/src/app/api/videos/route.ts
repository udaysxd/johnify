import { NextResponse } from 'next/server';
import { cookies } from 'next/headers';

// Define types for our video response
interface VideoItem {
  id: string;
  title: string;
  url: string;
  thumbnail?: string;
  duration?: number;
  createdAt: string;
  [key: string]: unknown;
}

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

export async function GET(): Promise<NextResponse> {
  try {
    // Get the auth token from cookies (prefer access_token, fallback to legacy auth_token)
    const cookieStore = await cookies();
    const accessToken = cookieStore.get('access_token')?.value || cookieStore.get('auth_token')?.value;
    
    if (!accessToken) {
      return createErrorResponse('Authentication required', 401);
    }
    
    try {
      // Call the backend API with the user's access token
      const backendResponse = await fetch(`${API_BASE_URL}/api/videos/my-videos`, {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        cache: 'no-store',
      });

      if (!backendResponse.ok) {
        const errorData = await backendResponse.json().catch(() => ({}));
        console.error('Error fetching videos from backend:', errorData);
        return createErrorResponse(
          errorData.detail || 'Failed to fetch videos',
          backendResponse.status
        );
      }

      const data = await backendResponse.json();
      
      // Define the expected shape of video data from the backend
      interface BackendVideoItem {
        id?: string;
        title?: string;
        url?: string;
        thumbnail?: string;
        duration?: number;
        created_at?: string;
      }
      
      // Transform the response to match the expected format
      const videos: VideoItem[] = Array.isArray(data) ? data.map((video: BackendVideoItem) => ({
        id: video.id || '',
        title: video.title || 'Untitled Video',
        url: video.url || '',
        thumbnail: video.thumbnail || '',
        duration: video.duration || 0,
        createdAt: video.created_at || new Date().toISOString(),
      })) : [];
      
      return NextResponse.json(videos);
      
    } catch (error) {
      console.error('Error in videos API route:', error);
      return createErrorResponse(
        'Failed to fetch videos', 
        500, 
        error instanceof Error ? error.message : 'Unknown error'
      );
    }
    
  } catch (error) {
    console.error('Unexpected error in videos API route:', error);
    return createErrorResponse(
      'Internal server error', 
      500, 
      error instanceof Error ? error.message : 'Unknown error'
    );
  }
}
