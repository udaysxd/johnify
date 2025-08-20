'use client';

import Link from 'next/link';
import { useAuth } from '@/contexts/AuthContext';

export default function SignupCTA() {
  const { user, loading } = useAuth();

  // Don't render on loading to avoid flicker; only show when explicitly logged out
  if (loading || user) return null;

  return (
    <section className="relative py-20 px-4 sm:px-6 lg:px-8 bg-gradient-to-r from-gray-900 via-gray-900 to-gray-800 text-white">
      <div className="max-w-5xl mx-auto text-center">
        <h2 className="text-3xl md:text-4xl font-bold text-white mb-4">
          Ready to transform your learning experience?
        </h2>
        <p className="text-gray-300 mb-8">
          Join Johnify today and start learning with your personalised tutor.
        </p>
        <Link
          href="/auth/register"
          className="inline-flex items-center justify-center px-8 py-3 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white text-lg font-medium shadow-sm transition-colors"
        >
          Sign up free
        </Link>
      </div>
    </section>
  );
}
