'use client';

import Link from 'next/link';

export default function VerifyRequestPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-md w-full space-y-8 text-center">
        <div>
          <h2 className="mt-6 text-3xl font-extrabold text-gray-900">
            Check your email
          </h2>
          <p className="mt-2 text-sm text-gray-600">
            We&apos;ve sent you a magic link to sign in. Please check your email and click the link to continue.
          </p>
        </div>
        
        <div className="rounded-md bg-blue-50 p-4">
          <div className="flex">
            <div className="flex-shrink-0">
              <svg className="h-5 w-5 text-blue-400" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h.01a1 1 0 100-2H10V9z" clipRule="evenodd" />
              </svg>
            </div>
            <div className="ml-3">
              <h3 className="text-sm font-medium text-blue-800">
                Didn&apos;t receive an email?
              </h3>
              <div className="mt-2 text-sm text-blue-700">
                <p>Check your spam folder or try again.</p>
              </div>
            </div>
          </div>
        </div>
        
        <div className="text-sm text-center">
          <Link href="/auth/signin" className="font-medium text-indigo-600 hover:text-indigo-500">
            Back to Sign In
          </Link>
        </div>
      </div>
    </div>
  );
}
