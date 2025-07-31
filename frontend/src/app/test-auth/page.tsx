'use client';

import { useSession, signIn, signOut } from 'next-auth/react';
import { useRouter } from 'next/navigation';
import { useEffect } from 'react';

export default function TestAuth() {
  const { data: session, status } = useSession();
  const router = useRouter();

  useEffect(() => {
    console.log('Session status:', status);
    console.log('Session data:', session);
  }, [session, status]);

  if (status === 'loading') {
    return <div>Loading...</div>;
  }

  return (
    <div className="min-h-screen p-8">
      <h1 className="text-2xl font-bold mb-6">Authentication Test Page</h1>
      
      <div className="mb-6 p-4 border rounded-lg bg-gray-50">
        <h2 className="text-xl font-semibold mb-2">Session Status</h2>
        <pre className="bg-white p-4 rounded overflow-auto">
          {JSON.stringify({ status, session }, null, 2)}
        </pre>
      </div>

      <div className="space-y-4">
        {status === 'authenticated' ? (
          <>
            <button
              onClick={() => signOut()}
              className="px-4 py-2 bg-red-500 text-white rounded hover:bg-red-600"
            >
              Sign Out
            </button>
            <div className="mt-4 p-4 bg-green-100 text-green-800 rounded">
              You are signed in as {session.user?.email}
            </div>
          </>
        ) : (
          <>
            <button
              onClick={() => signIn()}
              className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
            >
              Sign In
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
