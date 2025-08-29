'use client';

import { useEffect, useState, useRef } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';

export default function Header() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, loading, handleSignOut } = useAuth();
  const [isClient, setIsClient] = useState(false);
  const [isSigningOut, setIsSigningOut] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const avatarButtonRef = useRef<HTMLButtonElement | null>(null);
  
  // Set client state to avoid hydration issues
  useEffect(() => {
    setIsClient(true);
  }, []);
  
  // Reset signing out state when auth state changes
  useEffect(() => {
    if (!loading) {
      setIsSigningOut(false);
    }
  }, [loading]);

  // Close menu on outside click or Escape
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      const target = e.target as Node;
      if (
        menuOpen &&
        menuRef.current &&
        !menuRef.current.contains(target) &&
        avatarButtonRef.current &&
        !avatarButtonRef.current.contains(target)
      ) {
        setMenuOpen(false);
      }
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setMenuOpen(false);
    }
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKey);
    };
  }, [menuOpen]);

  const handleSignOutClick = async () => {
    if (isSigningOut) return;
    
    try {
      setIsSigningOut(true);
      await handleSignOut();
      // The handleSignOut will handle the redirect
    } catch (error) {
      console.error('Error during sign out:', error);
      setIsSigningOut(false);
      // Force a full page reload to ensure clean state
      window.location.href = '/';
    }
  };

  const isAuthenticated = !!user;
  const handleLearnClick = (e: React.MouseEvent<HTMLAnchorElement>) => {
    if (pathname === '/learn') {
      e.preventDefault();
      // Force a full page reload to reset state and data
      window.location.reload();
    }
  };
  
  return (
    <header className="w-full border-b border-gray-800 bg-gray-900">
      <div className="container mx-auto px-4 py-4 flex justify-between items-center">
        <Link href="/" className="text-2xl font-bold text-white hover:text-indigo-300">
          Johnify
        </Link>
        
        <nav className="flex items-center space-x-4">
          {!isClient || loading || isSigningOut ? (
            <div className="h-8 w-24 bg-gray-700 rounded animate-pulse"></div>
          ) : isAuthenticated ? (
            <div className="flex items-center space-x-4 relative">
              {/* My learning link (authenticated) */}
              <Link 
                href="/my-learning" 
                className="px-3 py-2 text-sm font-bold text-gray-100 hover:text-indigo-300"
              >
                My learning
              </Link>
              {/* My Feed link (authenticated) */}
              <Link 
                href="/feed" 
                className="px-3 py-2 text-sm font-bold text-gray-100 hover:text-indigo-300"
              >
                My Feed
              </Link>
              {/* My Tutor link (authenticated) */}
              <Link 
                href="/learn" 
                onClick={handleLearnClick}
                className="px-4 py-2 text-sm font-bold text-white bg-indigo-600 rounded-md hover:bg-indigo-700"
              >
                Learn
              </Link>
              {/* User initial avatar */}
              <button
                ref={avatarButtonRef}
                type="button"
                onClick={() => setMenuOpen((v) => !v)}
                className="h-8 w-8 rounded-full bg-indigo-600 text-white flex items-center justify-center text-sm font-semibold focus:outline-none focus:ring-2 focus:ring-indigo-500"
                aria-haspopup="menu"
                aria-expanded={menuOpen}
                title={user?.user_name || user?.user_email || 'User'}
              >
                {((user?.user_name || user?.user_email || 'U').trim().charAt(0) || 'U').toUpperCase()}
              </button>
              {menuOpen && (
                <div
                  ref={menuRef}
                  className="absolute right-0 top-12 w-40 bg-white border border-gray-200 rounded-md shadow-lg py-1 z-50"
                  role="menu"
                >
                  {/* Read-only user email */}
                  <div className="px-4 py-2 text-xs text-gray-500 border-b border-gray-100 select-text break-words">
                    {user?.user_email || '—'}
                  </div>
                  <Link
                    href="/my-profile"
                    className="block w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
                    role="menuitem"
                    onClick={() => setMenuOpen(false)}
                  >
                    My Profile
                  </Link>
                  <button
                    onClick={handleSignOutClick}
                    disabled={isSigningOut}
                    className={`w-full text-left px-4 py-2 text-sm ${
                      isSigningOut ? 'text-gray-400 cursor-not-allowed' : 'text-gray-700 hover:bg-gray-50'
                    }`}
                    role="menuitem"
                  >
                    {isSigningOut ? 'Signing out…' : 'Sign Out'}
                  </button>
                </div>
              )}
            </div>
          ) : (
            <>
              {/* My learning link (unauthenticated) */}
              <Link 
                href="/my-learning" 
                className="px-3 py-2 text-sm font-bold text-gray-100 hover:text-indigo-300"
              >
                My learning
              </Link>
              {/* My Feed link (unauthenticated) */}
              <Link 
                href="/feed" 
                className="px-3 py-2 text-sm font-bold text-gray-100 hover:text-indigo-300"
              >
                My Feed
              </Link>
              {/* My Tutor link (unauthenticated) */}
              <Link 
                href="/learn" 
                onClick={handleLearnClick}
                className="px-4 py-2 text-sm font-bold text-white bg-indigo-600 rounded-md hover:bg-indigo-700"
              >
                Learn
              </Link>
              {!pathname.startsWith('/auth/signin') && (
                <Link 
                  href="/auth/signin" 
                  className="px-4 py-2 text-sm font-bold text-gray-100 hover:text-indigo-300"
                >
                  Sign In
                </Link>
              )}
              {!pathname.startsWith('/auth/register') && (
                <Link 
                  href="/auth/register" 
                  className="px-4 py-2 text-sm font-bold text-white bg-indigo-600 rounded-md hover:bg-indigo-700"
                >
                  Sign Up
                </Link>
              )}
            </>
          )}
        </nav>
      </div>
    </header>
  );
}
