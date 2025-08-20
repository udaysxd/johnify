'use client';

import { useRouter } from 'next/navigation';
import { useEffect } from 'react';
import { useAuth } from '@/contexts/AuthContext';

export function useAuthState() {
  const router = useRouter();
  const { user, loading, handleSignOut } = useAuth();
  const isAuthenticated = !!user;
  
  // Handle sign out and redirect
  const signOut = async () => {
    try {
      await handleSignOut();
      // Force a full page reload to ensure all state is cleared
      if (typeof window !== 'undefined') {
        window.location.href = '/auth/signin';
      }
    } catch (error) {
      console.error('Error during sign out:', error);
    }
  };
  
  // Check authentication state on route changes
  useEffect(() => {
    const handleRouteChange = () => {
      if (!loading && !isAuthenticated && !window.location.pathname.startsWith('/auth/')) {
        router.push('/auth/signin');
      }
    };
    
    // Check auth state on mount
    handleRouteChange();
    
    // Set up route change listener
    window.addEventListener('popstate', handleRouteChange);
    
    return () => {
      window.removeEventListener('popstate', handleRouteChange);
    };
  }, [isAuthenticated, loading, router]);
  
  return { 
    isAuthenticated, 
    isLoading: loading,
    signOut,
    user
  };
}
