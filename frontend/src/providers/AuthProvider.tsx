'use client';

import { SessionProvider, useSession } from 'next-auth/react';
import { ReactNode, useEffect, useState } from 'react';

// Debug component to log session changes
function SessionDebugger() {
  const { data: session, status } = useSession();
  const [isMounted, setIsMounted] = useState(false);
  
  useEffect(() => {
    setIsMounted(true);
    
    if (isMounted) {
      console.group('SessionDebugger - Session Update');
      console.log('Session status:', status);
      console.log('Session data:', session);
      
      // Only access localStorage on the client side
      if (typeof window !== 'undefined') {
        console.log('localStorage next-auth.session-token:', 
          localStorage.getItem('next-auth.session-token'));
      }
      
      console.groupEnd();
    }
  }, [session, status, isMounted]);
  
  return null;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  return (
    <SessionProvider 
      refetchInterval={5 * 60} // Refetch session every 5 minutes
      refetchOnWindowFocus={true}
      // Ensure we're using a stable session and not re-rendering unnecessarily
      session={undefined} // Let NextAuth handle the session
    >
      <SessionDebugger />
      {children}
    </SessionProvider>
  );
}
