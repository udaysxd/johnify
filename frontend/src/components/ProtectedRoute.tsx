'use client';

import { useRouter } from 'next/navigation';
import { useEffect, ReactNode } from 'react';
import { useSession } from 'next-auth/react';
import { Session } from 'next-auth';

// Define user role type
type UserRole = 'user' | 'admin' | 'premium' | string;

// Extended user type with role
interface AppUser {
  id: string;
  name?: string | null;
  email?: string | null;
  image?: string | null;
  role?: UserRole;
}

// Type guard to check if session has our custom user type
function hasUserWithRole(session: Session | null): session is Session & { user: AppUser } {
  return !!session?.user && typeof session.user === 'object';
}

interface ProtectedRouteProps {
  children: ReactNode;
  requiredRole?: UserRole;
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
      // Type-safe role check
      const userRole = hasUserWithRole(session) ? session.user.role : undefined;
      
      // Check if user has the required role
      if (requiredRole && userRole !== requiredRole) {
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
    // Type-safe role check
    const userRole = hasUserWithRole(session) ? session.user.role : undefined;
    
    // Check role if required
    if (requiredRole && userRole !== requiredRole) {
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
