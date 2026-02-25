'use client';

import { useSearchParams } from 'next/navigation';
import { useState, useEffect } from 'react';
import { useAuth } from '@/contexts/AuthContext';

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
  const { signIn, loading: isAuthLoading } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [googleClientId, setGoogleClientId] = useState<string>('');
  
  useEffect(() => {
    // Surface friendly messages based on query params
    const deactivated = searchParams.get('deactivated');
    if (deactivated) {
      setError('Your account is no longer active. Reach out to customer support at hello@johnify.com');
    }
  }, [searchParams]);

  useEffect(() => {
    let cleanup = false;
    const load = async () => {
      try {
        const res = await fetch('/api/auth/google/config', { cache: 'no-store' });
        const data = await res.json();
        const clientId = data?.client_id || '';
        if (!clientId) return;
        if (cleanup) return;
        setGoogleClientId(clientId);
        const script = document.createElement('script');
        script.src = 'https://accounts.google.com/gsi/client';
        script.async = true;
        script.defer = true;
        script.onload = () => {
          try {
            // @ts-expect-error Google Identity script attaches `google` to window at runtime
            const google = window.google;
            if (!google) return;
            google.accounts.id.initialize({
              client_id: clientId,
              callback: async (response: { credential?: string }) => {
                try {
                  const id_token = response?.credential;
                  if (!id_token) return;
                  const r = await fetch('/api/auth/google', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
                    body: JSON.stringify({ id_token }),
                    credentials: 'include',
                  });
                  const j = await r.json();
                  if (!r.ok) {
                    setError(j?.error || 'Google sign-in failed');
                    return;
                  }
                  window.location.href = '/my-learning';
                } catch {
                  setError('Google sign-in failed');
                }
              },
              ux_mode: 'popup',
              auto_select: false,
            });
            const btn = document.getElementById('google_signin_btn');
            if (btn) {
              google.accounts.id.renderButton(btn, { theme: 'outline', size: 'large', width: 320 });
            }
          } catch {}
        };
        document.body.appendChild(script);
      } catch {}
    };
    load();
    return () => { cleanup = true; };
  }, []);

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    console.log('[SignInPage] handleSubmit called', e);

    e.preventDefault();
    setIsSubmitting(true);
    setError('');

    try {
      const formData = new FormData(e.currentTarget as HTMLFormElement);
      const username = formData.get('username')?.toString().trim();
      const password = formData.get('password')?.toString();
      
      // Get and validate callback URL
      let callbackUrl = searchParams.get('callbackUrl') || '/my-learning';
      try {
        // Ensure the callback URL is a relative path
        const url = new URL(callbackUrl, window.location.origin);
        callbackUrl = url.pathname + url.search + url.hash;
      } catch {
        console.warn('Invalid callback URL, using default');
        callbackUrl = '/my-learning';
      }

      if (!username || !password) {
        throw new Error('Username and password are required');
      }

      console.log('[SignInPage] Attempting sign in with:', { username, callbackUrl });
      
      // Use the signIn function from our auth hook
      const { error } = await signIn(username, password);
      if (error) {
        // Normalize backend inactive message
        if (/no longer active/i.test(error)) {
          throw new Error('Your account is no longer active. Reach out to customer support at hello@johnify.com');
        }
        throw new Error(error);
      }
      
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
      console.error('[SignInPage] Sign in error:', error);
    } finally {
      setIsSubmitting(false);
      console.log('[SignInPage] handleSubmit finished', { error, isSubmitting });
    }
  };

  return (
    <NoSSRWrapper>
      <div className="min-h-screen flex items-center justify-center bg-[var(--color-background)] py-12 px-4 sm:px-6 lg:px-8">
        <div className="max-w-md w-full space-y-8">
          <div>
            <h2 className="mt-6 text-center text-3xl font-extrabold text-[var(--color-foreground)]">
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
              <label htmlFor="username" className="block text-sm font-medium text-[var(--color-foreground)]">
                Username
              </label>
              <div className="mt-1">
                <input
                  id="username"
                  name="username"
                  type="text"
                  required
                  className="appearance-none block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-[var(--color-secondary)] focus:border-[var(--color-secondary)] sm:text-sm"
                />
              </div>
            </div>

            <div>
              <label htmlFor="password" className="block text-sm font-medium text-[var(--color-foreground)]">
                Password
              </label>
              <div className="mt-1 relative">
                <input
                  id="password"
                  name="password"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  required
                  className="appearance-none block w-full pr-10 px-3 py-2 border border-gray-300 rounded-md shadow-sm placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-[var(--color-secondary)] focus:border-[var(--color-secondary)] sm:text-sm"
                />
                <button
                  type="button"
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute inset-y-0 right-2 flex items-center text-gray-500 hover:text-gray-700"
                >
                  {showPassword ? (
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M17.94 17.94A10.94 10.94 0 0 1 12 20C7 20 2.73 16.11 1 12c.58-1.27 1.4-2.45 2.43-3.5M9.88 9.88A3 3 0 0 1 12 9c1.66 0 3 1.34 3 3 0 .7-.24 1.34-.64 1.84" />
                      <path d="M1 1l22 22" />
                    </svg>
                  ) : (
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z" />
                      <circle cx="12" cy="12" r="3" />
                    </svg>
                  )}
                </button>
              </div>
            </div>

            <div className="flex justify-end -mt-2 mb-2">
              <a href="/auth/forgot" className="text-sm text-[var(--color-secondary)] hover:opacity-80">
                Forgot password?
              </a>
            </div>

            <div>
              <button
                type="submit"
                disabled={isSubmitting || isAuthLoading}
                className={`w-full flex justify-center py-2 px-4 rounded-md shadow-sm text-sm font-medium btn-primary ${isSubmitting || isAuthLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
              >
                {isSubmitting || isAuthLoading ? 'Signing in...' : 'Sign in'}
              </button>
            </div>

            {googleClientId ? (
              <>
                <div className="flex items-center gap-4 my-4">
                  <span className="h-px flex-1 bg-gray-200" aria-hidden="true" />
                  <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Or continue with</span>
                  <span className="h-px flex-1 bg-gray-200" aria-hidden="true" />
                </div>
                <div className="flex items-center justify-center">
                  <div id="google_signin_btn" aria-label="Sign in with Google" />
                </div>
              </>
            ) : null}
          </form>
        </div>
      </div>
    </NoSSRWrapper>
  );
}
