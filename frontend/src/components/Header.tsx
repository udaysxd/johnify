'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';

export default function Header() {
  const pathname = usePathname();
  const { user, loading, handleSignOut } = useAuth();
  const [isClient, setIsClient] = useState(false);
  const [isSigningOut, setIsSigningOut] = useState(false);
  
  // Set client state to avoid hydration issues
  useEffect(() => {
    setIsClient(true);
  }, []);
  
  // Reset signing out state when auth state changes
  useEffect(() => {
    if (!loading) {
      setIsSigningOut(false);
    }
  }, [loading]);

  const handleSignOutClick = async () => {
    if (isSigningOut) return;
    
    try {
      setIsSigningOut(true);
      await handleSignOut();
      // The handleSignOut will handle the redirect
    } catch (error) {
      console.error('Error during sign out:', error);
      setIsSigningOut(false);
      // Force a full page reload to ensure clean state
      window.location.href = '/';
    }
  };

  const isAuthenticated = !!user;
  
  return (
    <header className="w-full border-b border-gray-200 bg-white">
      <div className="container mx-auto px-4 py-4 flex justify-between items-center">
        <Link href="/" className="text-2xl font-bold text-indigo-600 hover:text-indigo-700">
          Johnify
        </Link>
        
        <nav className="flex items-center space-x-4">
          {!isClient || loading || isSigningOut ? (
            <div className="h-8 w-24 bg-gray-200 rounded animate-pulse"></div>
          ) : isAuthenticated ? (
            <div className="flex items-center space-x-4">
              <span className="text-sm text-gray-600">
                {user?.user_email || user?.user_name || 'User'}
              </span>
              <button
                onClick={handleSignOutClick}
                disabled={isSigningOut}
                className={`px-4 py-2 text-sm font-medium ${
                  isSigningOut 
                    ? 'text-gray-400 cursor-not-allowed' 
                    : 'text-gray-700 hover:text-indigo-600'
                }`}
              >
                {isSigningOut ? 'Signing out...' : 'Sign Out'}
              </button>
            </div>
          ) : (
            <>
              {!pathname.startsWith('/auth/signin') && (
                <Link 
                  href="/auth/signin" 
                  className="px-4 py-2 text-sm font-medium text-gray-700 hover:text-indigo-600"
                >
                  Sign In
                </Link>
              )}
              {!pathname.startsWith('/auth/register') && (
                <Link 
                  href="/auth/register" 
                  className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700"
                >
                  Sign Up
                </Link>
              )}
            </>
          )}
        </nav>
      </div>
    </header>
  );
}
