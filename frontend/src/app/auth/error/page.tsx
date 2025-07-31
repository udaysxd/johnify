'use client';

import { useEffect } from 'react';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';

export default function AuthErrorPage() {
  const searchParams = useSearchParams();
  const error = searchParams.get('error');
  
  // Common error messages
  const errorMessages: Record<string, string> = {
    Configuration: 'There is a problem with the server configuration.',
    AccessDenied: 'You do not have permission to sign in.',
    Verification: 'The sign in link is no longer valid.',
    Default: 'An error occurred during sign in.',
  };
  
  // Get the error message or use the default
  const errorMessage = error && error in errorMessages 
    ? errorMessages[error as keyof typeof errorMessages]
    : errorMessages.Default;

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-md w-full space-y-8">
        <div className="text-center">
          <h2 className="mt-6 text-3xl font-extrabold text-gray-900">
            Sign In Error
          </h2>
          <p className="mt-2 text-sm text-gray-600">
            {errorMessage}
          </p>
        </div>
        
        <div className="mt-8 space-y-6">
          <div className="rounded-md bg-red-50 p-4">
            <div className="flex">
              <div className="flex-shrink-0">
                <svg className="h-5 w-5 text-red-400" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                </svg>
              </div>
              <div className="ml-3">
                <h3 className="text-sm font-medium text-red-800">
                  Error: {error || 'Unknown error'}
                </h3>
                <div className="mt-2 text-sm text-red-700">
                  <p>Please try again or contact support if the problem persists.</p>
                </div>
              </div>
            </div>
          </div>
          
          <div className="flex items-center justify-between">
            <div className="text-sm">
              <Link href="/auth/signin" className="font-medium text-indigo-600 hover:text-indigo-500">
                Back to Sign In
              </Link>
            </div>
            <div className="text-sm">
              <Link href="/" className="font-medium text-gray-600 hover:text-gray-500">
                Return Home
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
