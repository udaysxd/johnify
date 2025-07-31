'use client';

import { useRouter } from 'next/navigation';
import { useEffect, ReactNode } from 'react';
import { useSession } from 'next-auth/react';

interface ProtectedRouteProps {
  children: ReactNode;
  requiredRole?: string;
  redirectTo?: string;
}

export default function ProtectedRoute({
  children,
  requiredRole,
  redirectTo = '/auth/login',
}: ProtectedRouteProps) {
  const { data: session, status } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (status === 'unauthenticated') {
      // Store the current URL for redirecting after login
      const redirectUrl = window.location.pathname + window.location.search;
      router.push(`${redirectTo}?callbackUrl=${encodeURIComponent(redirectUrl)}`);
    } else if (status === 'authenticated' && requiredRole) {
      // Check if user has the required role
      const userRole = session?.user?.role; // Assuming role is stored in the user object
      if (userRole !== requiredRole) {
        router.push('/unauthorized');
      }
    }
  }, [status, requiredRole, router, redirectTo, session]);

  if (status === 'loading') {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-indigo-500"></div>
      </div>
    );
  }

  if (status === 'authenticated') {
    // Check role if required
    if (requiredRole && session?.user?.role !== requiredRole) {
      return null; // Will be redirected by the useEffect
    }
    return <>{children}</>;
  }

  // Will be redirected by the useEffect
  return (
    <div className="flex items-center justify-center min-h-screen">
      <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-indigo-500"></div>
    </div>
  );
}
