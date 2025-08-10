'use client';

import { createContext, useContext, useEffect, useState, ReactNode, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { signIn, signOut as nextAuthSignOut, useSession } from 'next-auth/react';
import { User as AuthUser } from '@/types/auth';

interface AppUser {
  user_id: string;
  user_email: string;
  user_name: string;
  is_verified: boolean;
}

interface AuthContextType {
  user: AppUser | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<{ error?: string; ok: boolean }>;
  signOut: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AppUser | null>(null);
  const [loading, setLoading] = useState(true);
  const { data: session, status, update: updateSession } = useSession();
  const router = useRouter();

  // Update user when session changes
  const updateUserFromSession = useCallback(async () => {
    setLoading(true);
    try {
      if (status === 'authenticated' && session?.user) {
        // Map the session user to our AppUser type
        const userData: AppUser = {
          user_id: session.user.id || '',
          user_email: session.user.email || '',
          user_name: session.user.name || '',
          is_verified: false // You might want to get this from your session
        };
        setUser(userData);
      } else {
        setUser(null);
      }
    } catch (error) {
      console.error('Error updating user from session:', error);
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, [status, session]);

  useEffect(() => {
    updateUserFromSession();
  }, [updateUserFromSession, status]);

  const handleSignIn = async (email: string, password: string) => {
    try {
      const result = await signIn('credentials', {
        redirect: false,
        username: email,
        password,
      });

      if (result?.error) {
        return { error: result.error, ok: false };
      }

      return { ok: true };
    } catch (error) {
      console.error('Sign in error:', error);
      return { error: 'An error occurred during sign in', ok: false };
    }
  };

  const handleSignOut = async () => {
    try {
      await nextAuthSignOut({ redirect: false });
      setUser(null);
      router.push('/auth/signin');
    } catch (error) {
      console.error('Sign out error:', error);
    }
  };

  const refreshUser = async () => {
    try {
      // This will trigger a session refresh
      await signIn('credentials', { redirect: false });
    } catch (error) {
      console.error('Error refreshing user:', error);
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        signIn: handleSignIn,
        signOut: handleSignOut,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
