'use client';

import { useAuth } from '@/providers/AuthProvider';

export function useAuthState() {
  const { isAuthenticated, isLoading } = useAuth();
  
  return { isAuthenticated, isLoading };
}
