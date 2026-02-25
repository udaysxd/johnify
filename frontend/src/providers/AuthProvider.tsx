'use client';

import { ReactNode, createContext, useContext, useEffect, useState } from 'react';

interface User {
  id: string;
  name: string | null;
  email: string | null;
}

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<{ success: boolean; error?: string }>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

// Debug component to log auth changes
function AuthDebugger() {
  const { user, isAuthenticated, isLoading } = useAuth();
  const [isMounted, setIsMounted] = useState(false);
  
  useEffect(() => {
    setIsMounted(true);
    
    if (isMounted) {
      console.group('AuthDebugger - Auth State Update');
      console.log('Auth loading:', isLoading);
      console.log('Is authenticated:', isAuthenticated);
      console.log('User:', user);
      
      // Only access sessionStorage on the client side
      if (typeof window !== 'undefined') {
        console.log('sessionStorage access_token:', sessionStorage.getItem('access_token'));
        console.log('sessionStorage user:', sessionStorage.getItem('user'));
      }
      
      console.groupEnd();
    }
  }, [user, isAuthenticated, isLoading, isMounted]);
  
  return null;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Load user from session storage on mount
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const userData = sessionStorage.getItem('user');
      if (userData) {
        setUser(JSON.parse(userData));
      }
      setIsLoading(false);
    }
  }, []);

  const login = async (username: string, password: string) => {
    try {
      const formData = new URLSearchParams();
      formData.append('username', username);
      formData.append('password', password);
      
      // For production, we'll use the production backend URL directly
      // since environment variables might not be available at runtime in Cloud Run
      const isProduction = process.env.NODE_ENV === 'production';
      const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';
        
      console.log(`AuthProvider - Running in ${isProduction ? 'production' : 'development'} mode`);
      console.log('AuthProvider - Using backend URL:', backendUrl);
      
      if (!backendUrl) {
        console.error('Backend URL is not configured');
        throw new Error('Backend URL is not configured');
      }
      
      const response = await fetch(`${backendUrl}/api/auth/login`, {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/x-www-form-urlencoded',
          'Accept': 'application/json',
        },
        body: formData.toString(),
        credentials: 'include',
      });

      const data = await response.json();
      
      if (!response.ok) {
        return { success: false, error: data.detail || 'Login failed' };
      }

      const userInfo = {
        id: '1', // You might want to get this from the response
        name: username,
        email: username,
      };

      // Store user info and token in session storage
      sessionStorage.setItem('user', JSON.stringify(userInfo));
      sessionStorage.setItem('access_token', data.access_token);
      
      setUser(userInfo);
      return { success: true };
    } catch (error) {
      console.error('Login error:', error);
      return { 
        success: false, 
        error: error instanceof Error ? error.message : 'An unknown error occurred' 
      };
    }
  };

  const logout = () => {
    sessionStorage.removeItem('user');
    sessionStorage.removeItem('access_token');
    setUser(null);
  };

  return (
    <AuthContext.Provider 
      value={{
        user,
        isLoading,
        isAuthenticated: !!user,
        login,
        logout,
      }}
    >
      <AuthDebugger />
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
