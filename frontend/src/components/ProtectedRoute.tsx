'use client';

import { useRouter } from 'next/navigation';
import { useEffect, ReactNode, useState } from 'react';
import { useAuth } from '@/providers/AuthProvider';

// Define user role type
type UserRole = 'user' | 'admin' | 'premium' | string;

interface ProtectedRouteProps {
  children: ReactNode;
  requiredRole?: UserRole;
  redirectTo?: string;
}

export default function ProtectedRoute({
  children,
  requiredRole,
  redirectTo = '/auth/signin',
}: ProtectedRouteProps) {
  const { user, isAuthenticated, isLoading } = useAuth();
  const router = useRouter();
  const [isClient, setIsClient] = useState(false);

  // Set isClient to true after component mounts (client-side only)
  useEffect(() => {
    setIsClient(true);
  }, []);

  useEffect(() => {
    // Only run client-side
    if (!isClient) return;

    // If still loading, do nothing
    if (isLoading) return;

    // If not authenticated, redirect to login
    if (!isAuthenticated) {
      // Store the current URL for redirecting after login
      const redirectUrl = window.location.pathname + window.location.search;
      router.push(`${redirectTo}?callbackUrl=${encodeURIComponent(redirectUrl)}`);
    } 
    // If authenticated but role is required and doesn't match, redirect to unauthorized
    else if (requiredRole) {
      // For now, we're not implementing role-based access control
      // You can add role checking logic here when needed
      // For example: if (user.role !== requiredRole) { ... }
    }
  }, [requiredRole, router, redirectTo, isLoading, isClient]);

  // Show loading state while checking authentication
  if (isLoading || !isClient) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-indigo-500"></div>
      </div>
    );
  }

  // Check if user has the required role if specified
  if (requiredRole) {
    // For now, we're not implementing role-based access control
    // You can add role checking logic here when needed
    // For example: if (user?.role !== requiredRole) { ... }
  }

  return <>{children}</>;
}
