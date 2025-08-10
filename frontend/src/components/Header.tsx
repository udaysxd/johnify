'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { signOut, useSession } from 'next-auth/react';
import { useRouter } from 'next/navigation';

export default function Header() {
  const router = useRouter();
  const { data: session, status } = useSession();
  const [isMounted, setIsMounted] = useState(false);
  
  // Set mounted state to avoid hydration issues
  useEffect(() => {
    setIsMounted(true);
  }, []);
  
  // Log session state for debugging (client-side only)
  useEffect(() => {
    if (isMounted) {
      console.log('Session status:', status);
      console.log('Session data:', session);
      console.log('Cookies:', document.cookie);
    }
  }, [session, status, isMounted]);
  
  const isAuthenticated = status === 'authenticated' && session?.user;
  const isLoading = status === 'loading' && !isMounted;

  const handleSignOut = async () => {
    try {
      // First, clear all auth-related data from the client
      if (typeof window !== 'undefined') {
        // Clear localStorage and sessionStorage
        ['nextauth.message', 'nextauth.user', 'nextauth.tokens'].forEach(key => {
          localStorage.removeItem(key);
          sessionStorage.removeItem(key);
        });
      }
      
      // Call the signout API
      const signoutResponse = await fetch('/api/auth/signout', { 
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include' // Important for cookies to be sent
      });
      
      if (!signoutResponse.ok) {
        throw new Error('Failed to sign out');
      }
      
      // Force a hard refresh to ensure all state is cleared
      window.location.href = '/';
    } catch (error) {
      console.error('Error during sign out:', error);
      // Still redirect even if there's an error
      window.location.href = '/';
    }
  };

  return (
    <header className="w-full border-b border-gray-200 bg-white">
      <div className="container mx-auto px-4 py-4 flex justify-between items-center">
        <Link href="/" className="text-2xl font-bold text-indigo-600 hover:text-indigo-700">
          Johnify
        </Link>
        
        <nav className="flex items-center space-x-4">
          {isLoading ? (
            <div className="h-8 w-24 bg-gray-200 rounded animate-pulse"></div>
          ) : isAuthenticated ? (
            <div className="flex items-center space-x-4">
              <span className="text-sm text-gray-600">
                {session?.user?.email || 'User'}
              </span>
              <button
                onClick={handleSignOut}
                className="px-4 py-2 text-sm font-medium text-gray-700 hover:text-indigo-600"
              >
                Sign Out
              </button>
            </div>
          ) : (
            <>
              <Link 
                href="/auth/signin" 
                className="px-4 py-2 text-sm font-medium text-gray-700 hover:text-indigo-600"
              >
                Sign In
              </Link>
              <Link 
                href="/auth/signup" 
                className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700"
              >
                Sign Up
              </Link>
            </>
          )}
        </nav>
      </div>
    </header>
  );
}
