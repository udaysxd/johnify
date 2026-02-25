'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/contexts/AuthContext';

export default function RegisterPage() {
  const [formData, setFormData] = useState({
    user_name: '',
    user_email: '',
    password: ''
  });
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  // Removed confirm password; only track main password visibility
  const router = useRouter();
  const { signIn, setUser } = useAuth();
  const [showVerifyNotice, setShowVerifyNotice] = useState(false);
  const [registeredEmail, setRegisteredEmail] = useState('');
  const [resendStatus, setResendStatus] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle');
  const [resendMessage, setResendMessage] = useState<string | null>(null);

  // Listen for verification completion from other tab/window and redirect to preferences
  useEffect(() => {
    let bc: BroadcastChannel | null = null;
    let storageHandler: ((e: StorageEvent) => void) | null = null;
    let messageHandler: ((e: MessageEvent) => void) | null = null;

    const goToPreferences = () => {
      try {
        // Hard navigation ensures a refresh as requested
        window.location.assign('/preferences');
      } catch {
        router.replace('/preferences');
      }
    };

    // BroadcastChannel listener (same-origin modern browsers)
    try {
      bc = new BroadcastChannel('johnify-auth');
      bc.onmessage = (evt) => {
        if (evt && evt.data && evt.data.type === 'emailVerified') {
          goToPreferences();
        }
      };
    } catch {}

    // storage event listener (fallback, works across tabs)
    storageHandler = (e: StorageEvent) => {
      if (e.key === 'johnify:emailVerified' && e.newValue) {
        goToPreferences();
      }
    };
    window.addEventListener('storage', storageHandler);

    // postMessage listener from opener/child
    messageHandler = (e: MessageEvent) => {
      try {
        if (e.origin === window.location.origin && e.data && e.data.type === 'emailVerified') {
          goToPreferences();
        }
      } catch {}
    };
    window.addEventListener('message', messageHandler);

    return () => {
      try { if (bc) bc.close(); } catch {}
      if (storageHandler) window.removeEventListener('storage', storageHandler);
      if (messageHandler) window.removeEventListener('message', messageHandler);
    };
  }, [router]);

  // Live password requirement checks
  const pw = formData.password || '';
  const pwReq = {
    len: pw.length >= 8,
    upper: /[A-Z]/.test(pw),
    lower: /[a-z]/.test(pw),
    number: /[0-9]/.test(pw),
  } as const;

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: value
    }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    console.log('[RegisterPage] handleSubmit called', e, formData);

    e.preventDefault();
    setError('');
    
    // Basic validation
    if (formData.password.length < 8) {
      setError('Password must be at least 8 characters long');
      return;
    }

    try {
      setIsLoading(true);
      
      // Register the user
      const response = await fetch('/api/auth/register', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          user_name: formData.user_name.trim(),
          user_email: formData.user_email.trim(),
          password: formData.password,
        }),
        credentials: 'include',
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || data.detail || 'Registration failed');
      }

      // Show verification notice instead of auto-login
      setShowVerifyNotice(true);
      setRegisteredEmail(formData.user_email.trim());
      setResendStatus('idle');
      setResendMessage(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Registration failed');
      console.error('[RegisterPage] Registration error:', err);
    } finally {
      setIsLoading(false);
      console.log('[RegisterPage] handleSubmit finished');
    }
  };

  const handleResend = async () => {
    try {
      if (!registeredEmail && !formData.user_email) return;
      setResendStatus('sending');
      setResendMessage(null);
      const email = (registeredEmail || formData.user_email).trim();
      const resp = await fetch('/api/auth/resend-verification', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_email: email }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        setResendStatus('error');
        setResendMessage(data?.message || 'Failed to resend verification email');
        return;
      }
      setResendStatus('sent');
      setResendMessage(data?.message || 'Verification email sent.');
    } catch (e) {
      setResendStatus('error');
      setResendMessage(e instanceof Error ? e.message : 'Failed to resend verification email');
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--color-background)] py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-md w-full space-y-8">
        <div>
          <h2 className="mt-6 text-center text-3xl font-extrabold text-gray-900">
            Create an account
          </h2>
          <p className="mt-2 text-center text-sm text-gray-600">
            Or{' '}
            <Link href="/auth/signin" className="font-medium text-indigo-600 hover:text-indigo-500">
              sign in to your account
            </Link>
          </p>
        </div>
        
        {error && (
          <div className="bg-red-50 border-l-4 border-red-400 p-4">
            <div className="flex">
              <div className="flex-shrink-0">
                <svg className="h-5 w-5 text-red-400" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                </svg>
              </div>
              <div className="ml-3">
                <p className="text-sm text-red-700">{error}</p>
              </div>
            </div>
          </div>
        )}
        
        {showVerifyNotice ? (
          <div className="mt-6 space-y-4 bg-green-50 border border-green-200 rounded p-4">
            <h3 className="text-lg font-semibold text-green-800">Thank you!</h3>
            <p className="text-sm text-green-900">
              You must have received an email at <span className="font-medium">{registeredEmail || formData.user_email}</span>. Please verify your email to continue.
            </p>
            <div className="flex gap-3 items-center">
              <button
                type="button"
                onClick={handleResend}
                disabled={resendStatus === 'sending'}
                className={`inline-flex items-center px-4 py-2 rounded-md text-white text-sm font-medium ${resendStatus === 'sending' ? 'bg-indigo-400' : 'bg-indigo-600 hover:bg-indigo-700'}`}
              >
                {resendStatus === 'sending' ? 'Resending...' : 'Resend verification email'}
              </button>
              <Link href="/auth/signin" className="text-sm text-indigo-700 hover:text-indigo-900">Go to Sign in</Link>
            </div>
            {resendMessage && (
              <div className={`text-sm ${resendStatus === 'error' ? 'text-red-700' : 'text-green-700'}`}>{resendMessage}</div>
            )}
          </div>
        ) : (
        <form className="mt-8 space-y-6" onSubmit={handleSubmit}>
          <div className="rounded-md shadow-sm space-y-4">
            <div>
              <label htmlFor="user_name" className="sr-only">Full Name</label>
              <input
                id="user_name"
                name="user_name"
                type="text"
                required
                className="appearance-none relative block w-full px-3 py-2 border border-gray-300 placeholder-gray-500 text-gray-900 rounded-md focus:outline-none focus:ring-2 focus:ring-[var(--color-secondary)] focus:border-[var(--color-secondary)] focus:z-10 sm:text-sm"
                placeholder="Name"
                value={formData.user_name}
                onChange={handleChange}
                suppressHydrationWarning
              />
            </div>
            <div>
              <label htmlFor="user_email" className="sr-only">Email address</label>
              <input
                id="user_email"
                name="user_email"
                type="email"
                autoComplete="email"
                required
                className="appearance-none relative block w-full px-3 py-2 border border-gray-300 placeholder-gray-500 text-gray-900 rounded-md focus:outline-none focus:ring-2 focus:ring-[var(--color-secondary)] focus:border-[var(--color-secondary)] focus:z-10 sm:text-sm"
                placeholder="Email address"
                value={formData.user_email}
                onChange={handleChange}
                suppressHydrationWarning
              />
            </div>
            <div>
              <label htmlFor="password" className="sr-only">Password</label>
              <div className="relative">
                <input
                  id="password"
                  name="password"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="new-password"
                  required
                  className="appearance-none relative block w-full pr-10 px-3 py-2 border border-gray-300 placeholder-gray-500 text-gray-900 rounded-md focus:outline-none focus:ring-2 focus:ring-[var(--color-secondary)] focus:border-[var(--color-secondary)] focus:z-10 sm:text-sm"
                  placeholder="Password"
                  value={formData.password}
                  onChange={handleChange}
                  suppressHydrationWarning
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
              {/* Password requirements */}
              <div className="mt-2 text-xs text-gray-600">
                <ul className="space-y-1">
                  <li className={pwReq.len ? 'text-green-600' : ''}>
                    {pwReq.len ? '✓' : '•'} At least 8 characters
                  </li>
                  <li className={pwReq.upper ? 'text-green-600' : ''}>
                    {pwReq.upper ? '✓' : '•'} At least one uppercase letter
                  </li>
                  <li className={pwReq.lower ? 'text-green-600' : ''}>
                    {pwReq.lower ? '✓' : '•'} At least one lowercase letter
                  </li>
                  <li className={pwReq.number ? 'text-green-600' : ''}>
                    {pwReq.number ? '✓' : '•'} At least one number
                  </li>
                </ul>
              </div>
            </div>
            {/* Confirm password removed */}
          </div>

          <div>
            <button
              type="submit"
              disabled={isLoading}
              className={`group relative w-full flex justify-center py-2 px-4 text-sm font-medium rounded-md btn-primary ${isLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
              suppressHydrationWarning
            >
              {isLoading ? 'Creating account...' : 'Create Account'}
            </button>
          </div>
        </form>
        )}
      </div>
    </div>
  );
}
