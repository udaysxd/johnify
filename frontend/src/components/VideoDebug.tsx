'use client';

import { useState, useEffect, useRef } from 'react';

interface VideoDebugProps {
  videoUrl: string | null;
}

export default function VideoDebug({ videoUrl }: VideoDebugProps) {
  const [debugInfo, setDebugInfo] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  
  useEffect(() => {
    if (!videoUrl) {
      setDebugInfo(null);
      setError('No video URL provided');
      return;
    }

    // Add cache-busting parameter
    const urlWithTimestamp = `${videoUrl}${videoUrl.includes('?') ? '&' : '?'}t=${Date.now()}`;
    
    console.log('Debugging video URL:', urlWithTimestamp);
    
    // Test video element
    const video = document.createElement('video');
    let isMounted = true;
    
    const updateDebugInfo = (newInfo: any) => {
      if (isMounted) {
        setDebugInfo(prev => ({
          ...prev,
          ...newInfo,
          timestamp: new Date().toISOString()
        }));
      }
    };
    
    // Set up event listeners
    const events = [
      'loadstart', 'loadeddata', 'canplay', 'canplaythrough', 'play', 'playing',
      'waiting', 'stalled', 'suspend', 'abort', 'error', 'emptied', 'ended'
    ];
    
    const eventHandlers: Record<string, (e: Event) => void> = {};
    
    events.forEach(event => {
      eventHandlers[event] = (e: Event) => {
        console.log(`Video ${event} event:`, e);
        updateDebugInfo({
          events: [...(debugInfo?.events || []), { event, time: Date.now() }]
        });
      };
      video.addEventListener(event, eventHandlers[event]);
    });
    
    // Set up error handler
    video.onerror = (e) => {
      console.error('Video error:', e);
      console.error('Video error details:', video.error);
      setError(`Error ${video.error?.code}: ${video.error?.message || 'Unknown error'}`);
      updateDebugInfo({
        error: {
          code: video.error?.code,
          message: video.error?.message,
          name: video.error?.name
        }
      });
    };
    
    // Set the source
    video.src = urlWithTimestamp;
    
    // Check if the video can be played
    const checkPlayback = async () => {
      try {
        const canPlay = await video.play();
        if (canPlay !== undefined) {
          canPlay.catch(e => {
            console.error('Playback failed:', e);
            setError(`Playback failed: ${e.message}`);
          });
        }
      } catch (e: any) {
        console.error('Playback check failed:', e);
        setError(`Playback check failed: ${e.message}`);
      }
    };
    
    checkPlayback();
    
    // Clean up
    return () => {
      isMounted = false;
      events.forEach(event => {
        video.removeEventListener(event, eventHandlers[event]);
      });
      video.pause();
      video.removeAttribute('src');
      video.load();
    };
  }, [videoUrl]);
  
  if (!videoUrl) {
    return <div className="p-4 bg-yellow-50 text-yellow-800 rounded">No video URL provided</div>;
  }
  
  return (
    <div className="space-y-4 p-4 bg-gray-50 rounded-lg">
      <h3 className="text-lg font-medium">Video Debugger</h3>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <h4 className="font-medium mb-2">Video Player</h4>
          <div className="aspect-video bg-black rounded overflow-hidden">
            <video
              ref={videoRef}
              controls
              className="w-full h-full"
              src={videoUrl}
              onError={(e) => {
                console.error('Video element error:', e);
                const target = e.target as HTMLVideoElement;
                setError(`Video error: ${target.error?.message || 'Unknown error'}`);
              }}
            >
              Your browser does not support the video tag.
            </video>
          </div>
          
          {error && (
            <div className="mt-2 p-2 bg-red-50 text-red-700 rounded text-sm">
              <strong>Error:</strong> {error}
            </div>
          )}
        </div>
        
        <div>
          <h4 className="font-medium mb-2">Debug Information</h4>
          <div className="bg-white p-3 rounded border border-gray-200 text-sm overflow-auto max-h-64">
            <pre className="whitespace-pre-wrap break-words">
              {JSON.stringify({
                videoUrl,
                timestamp: new Date().toISOString(),
                userAgent: typeof navigator !== 'undefined' ? navigator.userAgent : 'N/A',
                ...debugInfo
              }, null, 2)}
            </pre>
          </div>
          
          <div className="mt-3">
            <button
              onClick={() => {
                if (videoRef.current) {
                  videoRef.current.load();
                }
              }}
              className="px-3 py-1 bg-blue-100 text-blue-700 rounded text-sm hover:bg-blue-200"
            >
              Reload Video
            </button>
            
            <a
              href={videoUrl}
              download
              target="_blank"
              rel="noopener noreferrer"
              className="ml-2 px-3 py-1 bg-green-100 text-green-700 rounded text-sm hover:bg-green-200"
            >
              Download Video
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}
