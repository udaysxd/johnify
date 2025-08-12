'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { useState, useEffect } from 'react';
import { useAuth } from '@/providers/AuthProvider';

// Disable SSR for this component to prevent hydration issues
const NoSSRWrapper = ({ children }: { children: React.ReactNode }) => {
  const [isMounted, setIsMounted] = useState(false);
  
  useEffect(() => {
    setIsMounted(true);
  }, []);

  if (!isMounted) {
    return null; // Return null on server-side and during hydration
  }
  
  return <>{children}</>;
};

export default function SignInPage() {
  const searchParams = useSearchParams();
  const { login, isLoading: isAuthLoading } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setIsSubmitting(true);
    setError('');

    try {
      const formData = new FormData(e.currentTarget as HTMLFormElement);
      const username = formData.get('username')?.toString().trim();
      const password = formData.get('password')?.toString();
      
      // Get and validate callback URL
      let callbackUrl = searchParams.get('callbackUrl') || '/dashboard';
      try {
        // Ensure the callback URL is a relative path
        const url = new URL(callbackUrl, window.location.origin);
        callbackUrl = url.pathname + url.search + url.hash;
      } catch {
        console.warn('Invalid callback URL, using default');
        callbackUrl = '/dashboard';
      }

      if (!username || !password) {
        throw new Error('Username and password are required');
      }

      console.log('Attempting sign in with:', { username, callbackUrl });
      
      // Use the login function from our auth hook
      await login(username, password);
      
      // If login is successful, redirect to the callback URL
      window.location.href = callbackUrl;
    } catch (error) {
      let errorMessage = 'An unexpected error occurred. Please try again.';
      
      if (error instanceof Error) {
        errorMessage = error.message;
      } else if (typeof error === 'string') {
        errorMessage = error;
      } else if (error && typeof error === 'object' && 'message' in error) {
        errorMessage = String(error.message);
      }
      
      setError(errorMessage);
      console.error('Sign in error:', error);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <NoSSRWrapper>
      <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
        <div className="max-w-md w-full space-y-8">
          <div>
            <h2 className="mt-6 text-center text-3xl font-extrabold text-gray-900">
              Sign in to your account
            </h2>
          </div>
          <form onSubmit={handleSubmit} className="space-y-6">
            {error && (
              <div className="bg-red-50 text-red-700 p-4 rounded-md">
                {error}
              </div>
            )}
            <div>
              <label htmlFor="username" className="block text-sm font-medium text-gray-700">
                Username
              </label>
              <div className="mt-1">
                <input
                  id="username"
                  name="username"
                  type="text"
                  required
                  className="appearance-none block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm placeholder-gray-400 focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm"
                />
              </div>
            </div>

            <div>
              <label htmlFor="password" className="block text-sm font-medium text-gray-700">
                Password
              </label>
              <div className="mt-1">
                <input
                  id="password"
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  required
                  className="appearance-none block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm placeholder-gray-400 focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm"
                />
              </div>
            </div>

            <div>
              <button
                type="submit"
                disabled={isSubmitting || isAuthLoading}
                className={`w-full flex justify-center py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 ${isSubmitting || isAuthLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
              >
                {isSubmitting || isAuthLoading ? 'Signing in...' : 'Sign in'}
              </button>
            </div>
          </form>
        </div>
      </div>
    </NoSSRWrapper>
  );
}
