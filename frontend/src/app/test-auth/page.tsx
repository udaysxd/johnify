'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';

export default function TestAuth() {
  const { user, loading, signOut } = useAuth();
  const isAuthenticated = !!user;
  const router = useRouter();
  const [isClient, setIsClient] = useState(false);

  useEffect(() => {
    setIsClient(true);
    console.log('Auth state:', { isAuthenticated, user, loading });
  }, [isAuthenticated, user, loading]);

  if (loading || !isClient) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-indigo-500"></div>
      </div>
    );
  }

  return (
    <div className="min-h-screen p-8">
      <h1 className="text-2xl font-bold mb-6">Authentication Test Page</h1>
      
      <div className="mb-6 p-4 border rounded-lg bg-gray-50">
        <h2 className="text-xl font-semibold mb-2">Authentication State</h2>
        <pre className="bg-white p-4 rounded overflow-auto">
          {JSON.stringify({ 
            isAuthenticated, 
            isLoading: loading, 
            user
          }, null, 2)}
        </pre>
      </div>

      <div className="space-y-4">
        {isAuthenticated ? (
          <>
            <button
              onClick={async () => {
                await signOut();
                router.push('/auth/signin');
              }}
              className="px-4 py-2 bg-red-500 text-white rounded hover:bg-red-600"
            >
              Sign Out
            </button>
            <div className="mt-4 p-4 bg-green-100 text-green-800 rounded">
              You are signed in as {user?.user_email || user?.user_name || 'User'}
            </div>
          </>
        ) : (
          <>
            <button
              onClick={() => router.push('/auth/signin')}
              className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
            >
              Go to Sign In
            </button>
            <div className="mt-4 p-4 bg-yellow-100 text-yellow-800 rounded">
              You are not signed in
            </div>
          </>
        )}
      </div>
    </div>
  );
}
