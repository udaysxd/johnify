'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/providers/AuthProvider';

export default function SignOutPage() {
  const router = useRouter();
  const { logout } = useAuth();
  
  useEffect(() => {
    // Sign out when the component mounts
    const handleSignOut = async () => {
      try {
        await logout();
        // Redirect to sign-in page after signing out
        router.push('/auth/signin');
      } catch (error) {
        console.error('Error signing out:', error);
        // If there's an error, still redirect to sign-in
        router.push('/auth/signin');
      }
    };
    
    handleSignOut();
  }, [router, logout]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-md w-full space-y-8 text-center">
        <div className="flex justify-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-600"></div>
        </div>
        <h2 className="mt-6 text-3xl font-extrabold text-gray-900">
          Signing out...
        </h2>
        <p className="mt-2 text-sm text-gray-600">
          You are being signed out of your account.
        </p>
      </div>
    </div>
  );
}
