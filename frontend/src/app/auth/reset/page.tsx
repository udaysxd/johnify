"use client";
import React, { useMemo, useState } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';

export default function ResetPasswordPage() {
  const params = useSearchParams();
  const router = useRouter();
  const token = useMemo(() => params.get('token') || '', [params]);

  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setMessage(null);

    if (!token) {
      setError('Missing reset token. Please use the link from your email.');
      return;
    }
    if (password !== confirm) {
      setError('Passwords do not match');
      return;
    }

    setSubmitting(true);
    try {
      const resp = await fetch('/api/auth/reset-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, new_password: password }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        setError(data?.detail || data?.error || data?.message || 'Failed to reset password');
      } else {
        setMessage(data?.message || 'Password has been reset successfully');
        // Optionally redirect to sign-in after a short delay
        setTimeout(() => router.push('/auth/signin'), 1500);
      }
    } catch (err: unknown) {
      let msg = 'Something went wrong';
      if (err instanceof Error) msg = err.message;
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-md w-full space-y-8">
        <div>
          <h2 className="mt-6 text-center text-3xl font-extrabold text-gray-900">Reset your password</h2>
          <p className="mt-2 text-center text-sm text-gray-600">Enter a new password for your account.</p>
        </div>

        <form className="mt-8 space-y-6" onSubmit={onSubmit}>
          <input type="hidden" name="token" value={token} />
          <div className="space-y-4">
            <div>
              <label htmlFor="password" className="block text-sm font-medium text-gray-700">New password</label>
              <input
                id="password"
                name="password"
                type="password"
                required
                minLength={8}
                className="appearance-none block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm placeholder-gray-400 focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="confirm" className="block text-sm font-medium text-gray-700">Confirm password</label>
              <input
                id="confirm"
                name="confirm"
                type="password"
                required
                minLength={8}
                className="appearance-none block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm placeholder-gray-400 focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
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
              {submitting ? 'Resetting...' : 'Reset password'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
