"use client";
import React, { useState } from 'react';

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    setMessage(null);
    try {
      const resp = await fetch('/api/auth/forgot-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_email: email }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        const detail = data?.detail || data?.error || data?.message;
        setError(detail || 'Failed to send reset link');
      } else {
        setMessage(
          data?.message ||
            'If the email exists, a reset link has been sent. Please check your inbox (and spam folder).'
        );
      }
    } catch (err: unknown) {
      const errMsg = (err && typeof err === 'object' && 'message' in err)
        ? (() => {
            const r = err as Record<string, unknown>;
            return typeof r.message === 'string' ? r.message : 'Something went wrong';
          })()
        : 'Something went wrong';
      setError(errMsg);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-md w-full space-y-8">
        <div>
          <h2 className="mt-6 text-center text-3xl font-extrabold text-gray-900">Forgot your password?</h2>
          <p className="mt-2 text-center text-sm text-gray-600">
            Enter your email and we&apos;ll send you a link to reset your password.
          </p>
        </div>
        <form className="mt-8 space-y-6" onSubmit={onSubmit}>
          <div className="rounded-md shadow-sm -space-y-px">
            <div>
              <label htmlFor="email" className="block text-sm font-medium text-gray-700">Email address</label>
              <input
                id="email"
                name="email"
                type="email"
                autoComplete="email"
                required
                className="appearance-none block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm placeholder-gray-400 focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
          </div>

          {message && <p className="text-green-700 text-sm">{message}</p>}
          {error && <p className="text-red-700 text-sm">{error}</p>}

          <div>
            <button
              type="submit"
              disabled={submitting}
              className={`w-full flex justify-center py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 ${submitting ? 'opacity-50 cursor-not-allowed' : ''}`}
            >
              {submitting ? 'Sending...' : 'Send reset link'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
