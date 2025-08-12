'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useAuth } from '@/providers/AuthProvider';

interface NavigationProps {
  children?: React.ReactNode;
}

export default function Navigation({ children }: NavigationProps) {
  const { user, isAuthenticated, isLoading, logout } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const [isClient, setIsClient] = useState(false);

  useEffect(() => {
    setIsClient(true);
  }, []);

  if (!isClient || isLoading) {
    return null;
  }

  return (
    <nav className="bg-white shadow-sm">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between h-16">
          <div className="flex items-center">
            <Link href="/" className="text-xl font-bold text-indigo-600">
              Johnify
            </Link>
            <div className="hidden md:ml-6 md:flex md:space-x-8">
              <NavLink href="/" current={pathname === '/'}>
                Home
              </NavLink>
              <NavLink href="/learn" current={pathname === '/learn'}>
                Learn
              </NavLink>
            </div>
          </div>
          
          <div className="flex items-center">
            {isAuthenticated ? (
              <div className="flex items-center space-x-4">
                <span className="text-gray-700">
                  Hello, {user?.name || 'User'}
                </span>
                <button
                  onClick={logout}
                  className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 transition-colors"
                >
                  Sign out
                </button>
              </div>
            ) : (
              <div className="flex space-x-4">
                <Link
                  href="/auth/signin"
                  className="px-4 py-2 text-sm font-medium text-gray-700 hover:text-indigo-600 transition-colors"
                >
                  Sign in
                </Link>
                <Link
                  href="/auth/register"
                  className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 transition-colors"
                >
                  Sign up
                </Link>
              </div>
            )}
          </div>
        </div>
      </div>
    </nav>
  );
}

function NavLink({ 
  href, 
  current, 
  children 
}: { 
  href: string; 
  current: boolean; 
  children: React.ReactNode 
}) {
  return (
    <Link
      href={href}
      className={`inline-flex items-center px-1 pt-1 border-b-2 text-sm font-medium ${
        current
          ? 'border-indigo-500 text-gray-900'
          : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
      }`}
    >
      {children}
    </Link>
  );
}
