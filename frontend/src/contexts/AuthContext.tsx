'use client';

import { createContext, useContext, useEffect, useState, ReactNode, useCallback } from 'react';
import { useRouter } from 'next/navigation';

interface AppUser {
  user_id: string;
  user_email: string;
  user_name: string;
  is_verified: boolean;
}

export interface AuthContextType {
  user: AppUser | null;
  loading: boolean;
  signIn: (email: string, password: string, skipLogin?: boolean) => Promise<{ error?: string; ok: boolean }>;
  signOut: () => Promise<void>;
  refreshUser: () => Promise<void>;
  setUser: (user: AppUser | null) => void;
  handleSignOut: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextType | undefined>(undefined);

// Helper function to handle API errors
const handleApiError = async (response: Response) => {
  if (!response.ok) {
    let errorMessage = 'An error occurred';
    try {
      const errorData = await response.json();
      errorMessage = errorData.detail || errorData.message || errorMessage;
    } catch (e) {
      errorMessage = response.status === 401 ? 'Unauthorized' : 'Network error';
    }
    throw new Error(errorMessage);
  }
  return response.json();
};

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AppUser | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  // Fetch the current user
  const fetchCurrentUser = useCallback(async () => {
    try {
      // First try to get user data from the backend using the HTTP-only cookie
      const response = await fetch('/api/auth/me', {
        credentials: 'include',
        headers: {
          'Accept': 'application/json',
        },
      });

      if (response.ok) {
        const userData = await response.json();
        setUser({
          user_id: userData.user_id || '',
          user_email: userData.user_email || '',
          user_name: userData.user_name || userData.user_email || '',
          is_verified: userData.is_verified ?? true,
        });
        console.log('[Auth] User state set from /api/auth/me:', userData);
        return true;
      }
      
      // If that fails, try the direct backend URL as a fallback
      if (process.env.NEXT_PUBLIC_BACKEND_URL) {
        const fallbackResponse = await fetch(`${process.env.NEXT_PUBLIC_BACKEND_URL}/api/users/me`, {
          credentials: 'include',
          headers: {
            'Accept': 'application/json',
          },
        });

        if (fallbackResponse.ok) {
          const userData = await fallbackResponse.json();
          setUser({
            user_id: userData.user_id || '',
            user_email: userData.user_email || '',
            user_name: userData.user_name || userData.user_email || '',
            is_verified: userData.is_verified ?? true,
          });
          return true;
        }
      }
      
      return false;
    } catch (error) {
      console.error('Error fetching user:', error);
      return false;
    }
  }, []);

  // Initialize auth state
  const initializeAuth = useCallback(async () => {
    try {
      setLoading(true);
      const success = await fetchCurrentUser();
      
      // If we couldn't fetch user, clear any invalid auth state
      if (!success) {
        setUser(null);
        // Clear any invalid tokens
        document.cookie = 'access_token=; Path=/; Expires=Thu, 01 Jan 1970 00:00:01 GMT;';
      }
    } catch (error) {
      console.error('Auth initialization error:', error);
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, [fetchCurrentUser]);

  // Initialize on mount
  useEffect(() => {
    initializeAuth();
  }, [initializeAuth]);

  // Handle sign in
  const handleSignIn = useCallback(async (email: string, password: string, skipLogin: boolean = false) => {
    try {
      setLoading(true);
      
      if (!skipLogin) {
        // Login request - will set HTTP-only cookie
        const formData = new URLSearchParams();
        formData.append('username', email.trim());
        formData.append('password', password);
        const loginResponse = await fetch(`/api/auth/login`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
          },
          body: formData.toString(),
          credentials: 'include',
        });

        if (!loginResponse.ok) {
          const errorData = await loginResponse.json().catch(() => ({}));
          throw new Error(errorData.error || 'Login failed');
        }
        
        const loginData = await loginResponse.json();
        
        // Set user data from login response
        if (loginData.user) {
          setUser({
            user_id: loginData.user.user_id || '',
            user_email: loginData.user.user_email || email.trim(),
            user_name: loginData.user.user_name || email.trim(),
            is_verified: loginData.user.is_verified ?? true,
          });
          // Immediately refresh user state from backend to ensure cookie/session is picked up
          await fetchCurrentUser();
          console.log('[Auth] User state refreshed after login:', loginData.user);
          // Force a full page reload to ensure header and state update
          if (typeof window !== 'undefined') {
            window.location.reload();
          }
          return { ok: true };
        }

        // Fallback: Fetch user data from /me endpoint if not in login response
        const userResponse = await fetch(`${process.env.NEXT_PUBLIC_BACKEND_URL}/api/users/me`, {
          credentials: 'include',
          headers: {
            'Accept': 'application/json',
          },
        });

        if (!userResponse.ok) {
          return { ok: false, error: 'Failed to fetch user data' };
        }
        
        const userData = await userResponse.json();
        setUser({
          user_id: userData.user_id || '',
          user_email: userData.user_email || email.trim(),
          user_name: userData.user_name || userData.user_email || email.trim(),
          is_verified: userData.is_verified ?? true,
        });

        return { ok: true };
      }
      // Defensive: if somehow no return above, return failure
      return { ok: false, error: 'Login failed (unexpected state)' };
    } catch (error) {
      console.error('Login error:', error);
      return { 
        error: error instanceof Error ? error.message : 'An error occurred during login', 
        ok: false 
      };
    } finally {
      setLoading(false);
    }
  }, []);

  // Handle sign out
  const handleSignOut = useCallback(async () => {
    try {
      // Optimistically update the UI first
      setUser(null);
      
      // Clear any client-side storage
      if (typeof window !== 'undefined') {
        // Clear all storage
        localStorage.clear();
        sessionStorage.clear();
        
        // Clear all auth-related cookies
        const clearCookie = (name: string) => {
          // Standard path with all possible cookie attributes
          const cookieAttributes = [
            'Path=/',
            'Expires=Thu, 01 Jan 1970 00:00:01 GMT',
            'SameSite=Lax',
            'Secure',
            'HttpOnly'
          ].join('; ');
          
          document.cookie = `${name}=; ${cookieAttributes}`;
          
          // Clear for all subdomains in production
          if (process.env.NODE_ENV === 'production') {
            const domainAttributes = [
              'Path=/',
              'Expires=Thu, 01 Jan 1970 00:00:01 GMT',
              'Domain=.johnify.com',
              'SameSite=Lax',
              'Secure',
              'HttpOnly'
            ].join('; ');
            
            document.cookie = `${name}=; ${domainAttributes}`;
          }
        };
        
        // Clear all possible auth cookies
        ['access_token', 'refresh_token', 'session', 'auth_token', 'token'].forEach(clearCookie);
      }
      
      // Call the backend to invalidate the session
      try {
        // First try the relative path which will use the same domain
        let response = await fetch('/api/auth/logout', {
          method: 'POST',
          credentials: 'include',
          headers: {
            'Accept': 'application/json',
          },
        });
        
        // If that fails, try the full backend URL
        if (!response.ok && process.env.NEXT_PUBLIC_BACKEND_URL) {
          response = await fetch(`${process.env.NEXT_PUBLIC_BACKEND_URL}/api/auth/logout`, {
            method: 'POST',
            credentials: 'include',
            headers: {
              'Accept': 'application/json',
            },
          });
        }
        
        if (!response.ok) {
          throw new Error('Logout failed');
        }
      } catch (error) {
        console.error('Error during logout:', error);
        // Continue with redirect even if backend logout fails
      }
      
      // Force a full page reload to ensure all state is cleared
      if (typeof window !== 'undefined') {
        // Clear any remaining cookies that might have been missed
        document.cookie.split(';').forEach(cookie => {
          const [name] = cookie.split('=');
          document.cookie = `${name.trim()}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
          if (process.env.NODE_ENV === 'production') {
            document.cookie = `${name.trim()}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; domain=.johnify.com`;
          }
        });
        
        // Clear session storage and local storage again to be thorough
        sessionStorage.clear();
        localStorage.clear();
        
        // Redirect to signin page with a full page reload
        window.location.href = '/auth/signin?loggedOut=true';
      }
    } catch (error) {
      console.error('Error during sign out:', error);
      // Still redirect even if there was an error
      if (typeof window !== 'undefined') {
        window.location.href = '/auth/signin?error=logout_failed';
      }
    } finally {
      setLoading(false);
    }
  }, [router]);

  // Refresh user data
  const refreshUser = useCallback(async () => {
    await fetchCurrentUser();
  }, [fetchCurrentUser]);

  return (
    <AuthContext.Provider value={{
      user,
      loading,
      signIn: handleSignIn,
      signOut: handleSignOut,
      refreshUser,
      setUser,
      handleSignOut,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
