import { NextResponse } from 'next/server';
import { getBackendUrl } from '../utils';

export async function POST(request: Request) {
  try {
    const { videoUrl } = await request.json();
    
    if (!videoUrl) {
      return NextResponse.json(
        { error: 'Missing videoUrl parameter' },
        { status: 400 }
      );
    }

    console.log(`Checking video URL: ${videoUrl}`);
    
    // Check if the URL is absolute or relative
    const isAbsoluteUrl = videoUrl.startsWith('http');
    const fullUrl = isAbsoluteUrl ? videoUrl : `${getBackendUrl()}${videoUrl}`;
    
    console.log(`Checking video at: ${fullUrl}`);
    
    // First, try a HEAD request to check if the file exists
    const headResponse = await fetch(fullUrl, { 
      method: 'HEAD',
      cache: 'no-store',
    });

    if (!headResponse.ok) {
      console.error('HEAD request failed:', {
        status: headResponse.status,
        statusText: headResponse.statusText,
        headers: Object.fromEntries(headResponse.headers.entries())
      });
      
      // Try a GET request to get more detailed error information
      try {
        const getResponse = await fetch(fullUrl, { cache: 'no-store' });
        const text = await getResponse.text();
        console.error('GET response:', {
          status: getResponse.status,
          statusText: getResponse.statusText,
          headers: Object.fromEntries(getResponse.headers.entries()),
          body: text.substring(0, 500) // First 500 chars of response
        });
      } catch (getError) {
        console.error('GET request failed:', getError);
      }
      
      return NextResponse.json(
        { 
          error: 'Video file not found or inaccessible',
          status: headResponse.status,
          statusText: headResponse.statusText,
          url: fullUrl,
          isAbsoluteUrl,
          backendUrl: getBackendUrl()
        },
        { status: 404 }
      );
    }
    
    // If HEAD request succeeds, check if the content type is video
    const contentType = headResponse.headers.get('content-type') || '';
    const isVideo = contentType.startsWith('video/');
    
    if (!isVideo) {
      console.error('URL does not point to a video file:', {
        contentType,
        url: fullUrl,
        headers: Object.fromEntries(headResponse.headers.entries())
      });
      
      return NextResponse.json(
        { 
          error: 'URL does not point to a video file',
          contentType,
          url: fullUrl,
          headers: Object.fromEntries(headResponse.headers.entries())
        },
        { status: 400 }
      );
    }
    
    // If we get here, the video should be accessible
    return NextResponse.json({
      success: true,
      url: fullUrl,
      contentType,
      contentLength: headResponse.headers.get('content-length'),
      acceptRanges: headResponse.headers.get('accept-ranges'),
      lastModified: headResponse.headers.get('last-modified'),
      eTag: headResponse.headers.get('etag'),
      headers: Object.fromEntries(headResponse.headers.entries())
    });
    
  } catch (error) {
    console.error('Error checking video URL:', error);
    return NextResponse.json(
      { 
        error: 'Failed to check video URL',
        message: error instanceof Error ? error.message : String(error)
      },
      { status: 500 }
    );
  }
}
