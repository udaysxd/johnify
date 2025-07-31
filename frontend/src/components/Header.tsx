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
  
  // Log session state for debugging
  useEffect(() => {
    console.log('Session status:', status);
    console.log('Session data:', session);
    
    // Check for session token in cookies
    if (typeof document !== 'undefined') {
      console.log('Cookies:', document.cookie);
    }
  }, [session, status]);
  
  const isAuthenticated = status === 'authenticated' && session?.user;
  const isLoading = status === 'loading' && !isMounted;

  const handleSignOut = async () => {
    try {
      // Clear any existing session data
      await fetch('/api/auth/signout', { method: 'POST' });
      
      // Sign out using NextAuth
      const data = await signOut({ 
        redirect: false,
        callbackUrl: '/'
      });
      
      // Force a hard refresh to clear all state
      window.location.href = data.url;
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
