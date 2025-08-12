'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/providers/AuthProvider';

export default function Header() {
  const router = useRouter();
  const { user, isAuthenticated, isLoading, logout } = useAuth();
  const [isClient, setIsClient] = useState(false);
  
  // Set client state to avoid hydration issues
  useEffect(() => {
    setIsClient(true);
  }, []);
  
  // Log auth state for debugging (client-side only)
  useEffect(() => {
    if (isClient) {
      console.log('Auth state:', { isAuthenticated, user, isLoading });
    }
  }, [user, isAuthenticated, isLoading, isClient]);

  const handleSignOut = () => {
    try {
      // Clear auth data using our logout function
      logout();
      // Redirect to home page
      router.push('/');
    } catch (error) {
      console.error('Error during sign out:', error);
      // Still redirect even if there's an error
      router.push('/');
    }
  };

  return (
    <header className="w-full border-b border-gray-200 bg-white">
      <div className="container mx-auto px-4 py-4 flex justify-between items-center">
        <Link href="/" className="text-2xl font-bold text-indigo-600 hover:text-indigo-700">
          Johnify
        </Link>
        
        <nav className="flex items-center space-x-4">
          {!isClient || isLoading ? (
            <div className="h-8 w-24 bg-gray-200 rounded animate-pulse"></div>
          ) : isAuthenticated ? (
            <div className="flex items-center space-x-4">
              <span className="text-sm text-gray-600">
                {user?.email || user?.name || 'User'}
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
                href="/auth/register" 
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
