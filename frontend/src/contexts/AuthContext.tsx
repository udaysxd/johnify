'use client';

import { createContext, useContext, useEffect, useState, ReactNode, useCallback } from 'react';
import { useRouter } from 'next/navigation';

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
  const router = useRouter();

  // Update user from session storage
  const updateUserFromStorage = useCallback(() => {
    setLoading(true);
    try {
      if (typeof window !== 'undefined') {
        const userData = sessionStorage.getItem('user');
        if (userData) {
          const parsedUser = JSON.parse(userData);
          const appUser: AppUser = {
            user_id: parsedUser.id || '',
            user_email: parsedUser.email || '',
            user_name: parsedUser.name || '',
            is_verified: true // Assuming the user is verified if they have a valid session
          };
          setUser(appUser);
          return;
        }
      }
      setUser(null);
    } catch (error) {
      console.error('Error updating user from storage:', error);
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  // Handle sign in
  const handleSignIn = useCallback(async (email: string, password: string) => {
    try {
      setLoading(true);
      
      // First, get the access token
      const formData = new URLSearchParams();
      formData.append('username', email);
      formData.append('password', password);
      
      const loginResponse = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/auth/login`, {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/x-www-form-urlencoded',
          'Accept': 'application/json',
        },
        body: formData.toString(),
        credentials: 'include',
      });

      const tokenData = await loginResponse.json();
      
      if (!loginResponse.ok) {
        return { error: tokenData.detail || 'Login failed', ok: false };
      }

      // Now fetch the user data using the token
      const userResponse = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/users/me`, {
        headers: {
          'Authorization': `Bearer ${tokenData.access_token}`,
          'Accept': 'application/json',
        },
        credentials: 'include',
      });

      if (!userResponse.ok) {
        throw new Error('Failed to fetch user data');
      }

      const userData = await userResponse.json();
      
      // Store user data in session storage
      const userInfo = {
        id: userData.user_id || '1',
        name: userData.user_name || email,
        email: userData.user_email || email,
      };
      
      sessionStorage.setItem('user', JSON.stringify(userInfo));
      sessionStorage.setItem('access_token', tokenData.access_token);
      
      // Update user state
      const appUser: AppUser = {
        user_id: userInfo.id,
        user_email: userInfo.email,
        user_name: userInfo.name,
        is_verified: userData.is_verified || true
      };
      
      setUser(appUser);
      return { ok: true };
    } catch (error) {
      console.error('Sign in error:', error);
      return { error: 'An error occurred during sign in', ok: false };
    } finally {
      setLoading(false);
    }
  }, []);

  // Handle sign out
  const handleSignOut = useCallback(async () => {
    try {
      setLoading(true);
      // Clear session storage
      sessionStorage.removeItem('user');
      sessionStorage.removeItem('access_token');
      setUser(null);
      router.push('/auth/signin');
    } catch (error) {
      console.error('Sign out error:', error);
    } finally {
      setLoading(false);
    }
  }, [router]);

  // Refresh user data
  const refreshUser = useCallback(async () => {
    updateUserFromStorage();
  }, [updateUserFromStorage]);

  // Update user when component mounts
  useEffect(() => {
    updateUserFromStorage();
  }, [updateUserFromStorage]);

  const value = {
    user,
    loading,
    signIn: handleSignIn,
    signOut: handleSignOut,
    refreshUser,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
