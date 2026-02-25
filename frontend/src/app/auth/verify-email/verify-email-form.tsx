'use client';

import { useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';

export default function VerifyEmailForm() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const token = searchParams.get('token');
  const [status, setStatus] = useState<'verifying' | 'success' | 'error' | 'invalid'>('verifying');
  const [error, setError] = useState('');

  useEffect(() => {
    const verifyEmail = async () => {
      // Check for success/error in URL first
      const success = searchParams.get('success');
      const errorParam = searchParams.get('error');
      
      if (success === 'true') {
        setStatus('success');
        return;
      }
      
      if (errorParam) {
        setError(
          errorParam === 'invalid_token' ? 'Invalid or expired verification link' :
          errorParam === 'already_used' ? 'Your email has already been verified.' :
          errorParam === 'expired' ? 'This verification link has expired' :
          errorParam === 'user_not_found' ? 'User not found' :
          'Verification failed'
        );
        setStatus('error');
        return;
      }

      // If no success/error in URL but we have a token, navigate to API route so cookies and redirects work reliably
      if (token) {
        window.location.href = `/api/auth/verify-email?token=${encodeURIComponent(token)}`;
        return;
      } else {
        setStatus('invalid');
      }
    };

    verifyEmail();
  }, [token, searchParams]);

  // When success is reached, broadcast to opener/original tab, but keep this page showing success
  useEffect(() => {
    if (status !== 'success') return;

    try {
      // 1) Broadcast via BroadcastChannel (works same-origin)
      try {
        const bc = new BroadcastChannel('johnify-auth');
        bc.postMessage({ type: 'emailVerified' });
        // Close channel shortly after to avoid leaks
        setTimeout(() => bc.close(), 500);
      } catch {}

      // 2) localStorage flag to trigger storage events for other tabs
      try {
        localStorage.setItem('johnify:emailVerified', String(Date.now()));
        // Clean up the flag soon after
        setTimeout(() => {
          try { localStorage.removeItem('johnify:emailVerified'); } catch {}
        }, 2000);
      } catch {}

      // 3) Best-effort notify opener if same-origin
      try {
        if (window.opener && !window.opener.closed) {
          // Prefer postMessage for safety
          window.opener.postMessage({ source: 'johnify', type: 'emailVerified' }, window.location.origin);
        }
      } catch {}

      // Do not close or auto-redirect this page; we just inform the user.
      // Original signup tab should navigate via the broadcast signals.
      return () => {};
    } catch {}
  }, [status]);

  if (status === 'verifying') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
        <div className="max-w-md w-full space-y-8 text-center">
          <div className="flex flex-col items-center">
            <div className="w-16 h-16 border-4 border-indigo-500 border-t-transparent rounded-full animate-spin mb-4"></div>
            <h2 className="mt-6 text-2xl font-extrabold text-gray-900">
              Verifying your email...
            </h2>
            <p className="mt-2 text-sm text-gray-600">
              Please wait while we verify your email address.
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (status === 'success') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
        <div className="max-w-md w-full space-y-8 text-center">
          <div className="flex flex-col items-center">
            <div className="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-green-100">
              <svg
                className="h-6 w-6 text-green-600"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M5 13l4 4L19 7"
                />
              </svg>
            </div>
            <h2 className="mt-6 text-2xl font-extrabold text-gray-900">
              Email Verified!
            </h2>
            <p className="mt-2 text-sm text-gray-600">
              Your email has been successfully verified.
            </p>
            <div className="mt-6">
              <Link
                href="/preferences"
                className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500"
              >
                Go to Preferences
              </Link>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-md w-full space-y-8 text-center">
        <div className="flex flex-col items-center">
          <div className="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-red-100">
            <svg
              className="h-6 w-6 text-red-600"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </div>
          <h2 className="mt-6 text-2xl font-extrabold text-gray-900">
            {status === 'invalid' ? 'Invalid Verification Link' : 'Verification Failed'}
          </h2>
          <p className="mt-2 text-sm text-gray-600">
            {status === 'invalid' 
              ? 'The verification link is invalid or has expired.' 
              : error || 'An error occurred while verifying your email.'}
          </p>
          <div className="mt-6">
            <Link
              href="/auth/register"
              className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-indigo-700 bg-indigo-100 hover:bg-indigo-200 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500"
            >
              Register Again
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
