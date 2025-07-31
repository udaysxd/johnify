'use client';

import { useState, useEffect } from 'react';
import { useSession } from 'next-auth/react';

export function useAuthState() {
  const { data: session, status } = useSession();
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    console.group('useAuthState - Status Change');
    console.log('Previous state:', { isAuthenticated, isLoading });
    console.log('New status:', status);
    console.log('Session data:', session);
    
    if (status === 'authenticated') {
      console.log('User is authenticated');
      setIsAuthenticated(!!session?.user);
      setIsLoading(false);
    } else if (status === 'unauthenticated') {
      console.log('User is not authenticated');
      setIsAuthenticated(false);
      setIsLoading(false);
    } else if (status === 'loading') {
      console.log('Authentication status is loading...');
      setIsLoading(true);
    }
    
    console.log('Updated state:', { isAuthenticated, isLoading });
    console.groupEnd();
  }, [status, session]);

  return { isAuthenticated, isLoading, session };
}
