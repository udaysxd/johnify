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
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const avatarButtonRef = useRef<HTMLButtonElement | null>(null);
  const mobileMenuRef = useRef<HTMLDivElement | null>(null);
  const mobileButtonRef = useRef<HTMLButtonElement | null>(null);
  
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

  // Close menus on outside click or Escape
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
      if (
        mobileMenuOpen &&
        mobileMenuRef.current &&
        !mobileMenuRef.current.contains(target) &&
        mobileButtonRef.current &&
        !mobileButtonRef.current.contains(target)
      ) {
        setMobileMenuOpen(false);
      }
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        setMenuOpen(false);
        setMobileMenuOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKey);
    };
  }, [menuOpen, mobileMenuOpen]);

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
    if (pathname === '/mlites') {
      e.preventDefault();
      // Force a full page reload to reset state and data
      window.location.reload();
    }
  };
  // Removed Lites link (hidden)
  
  // Hide global header on the new homepage; the page renders its own header/CTAs
  if (pathname === '/') {
    return null;
  }

  return (
    <header className="w-full border-b border-gray-800 bg-[var(--color-surface)] text-[var(--color-primary)]">
      <div className="container mx-auto px-4 py-4 flex justify-between items-center">
        <Link href="/" className="text-2xl font-bold text-[var(--color-primary)] hover:opacity-80">
          Johnify
        </Link>
        {/* Desktop nav */}
        <nav className="hidden md:flex items-center space-x-4">
          {!isClient || loading || isSigningOut ? (
            <div className="h-8 w-24 bg-[#2e4d4b]/20 rounded animate-pulse"></div>
          ) : isAuthenticated ? (
            <div className="flex items-center space-x-4 relative">
              {/* My learning link (authenticated) */}
              <Link 
                href="/my-learning" 
                className="px-3 py-2 text-sm font-bold text-[var(--color-primary)] hover:opacity-80"
              >
                My learning
              </Link>
              {/* My Feed link (authenticated) */}
              <Link 
                href="/feed" 
                className="px-3 py-2 text-sm font-bold text-[#2e4d4b] hover:opacity-80"
              >
                My Feed
              </Link>
              {/* My Tutor link (authenticated) */}
              <Link 
                href="/mlites" 
                onClick={handleLearnClick}
                className="px-4 py-2 text-sm font-bold text-white bg-[var(--color-primary)] rounded-md hover:opacity-90"
              >
                Learn
              </Link>
              {/* User initial avatar */}
              <button
                ref={avatarButtonRef}
                type="button"
                onClick={() => setMenuOpen((v) => !v)}
                className="h-8 w-8 rounded-full bg-[var(--color-primary)] text-white flex items-center justify-center text-sm font-semibold focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]"
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
              {/* Hide My learning, Lites, and Learn for unauthenticated users */}
              {/* Optional: Keep My Feed public if desired */}
              <Link 
                href="/feed" 
                className="px-3 py-2 text-sm font-bold text-gray-100 hover:text-indigo-300"
              >
                My Feed
              </Link>
              {!pathname.startsWith('/auth/signin') && (
                <Link 
                  href="/auth/signin" 
                  className="px-4 py-2 text-sm font-bold text-[var(--color-primary)] hover:opacity-80"
                >
                  Sign In
                </Link>
              )}
              {!pathname.startsWith('/auth/register') && (
                <Link 
                  href="/auth/register" 
                  className="px-4 py-2 text-sm font-bold text-[#2e4d4b] bg-white rounded-md hover:opacity-90"
                >
                  Sign Up
                </Link>
              )}
            </>
          )}
        </nav>

        {/* Mobile actions: show My learning + Learn inline; others under hamburger */}
        <div className="md:hidden flex items-center gap-2">
          {!isClient || loading || isSigningOut ? (
            <div className="h-8 w-40 bg-[color:var(--color-primary)]/20 rounded animate-pulse" />
          ) : isAuthenticated ? (
            <>
              <Link 
                href="/my-learning" 
                className="px-2 py-2 text-sm font-bold text-[var(--color-primary)] hover:opacity-80"
              >
                My learning
              </Link>
              <Link 
                href="/mlites" 
                className="px-3 py-2 text-sm font-bold text-white bg-[var(--color-primary)] rounded-md hover:opacity-90"
              >
                Learn
              </Link>
              <button
                ref={mobileButtonRef}
                type="button"
                onClick={() => setMobileMenuOpen((v) => !v)}
                className="p-2 text-[var(--color-primary)] hover:opacity-80 focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]"
                aria-label="Open menu"
                aria-expanded={mobileMenuOpen}
              >
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-7 h-7">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
                </svg>
              </button>
            </>
          ) : (
            // unauthenticated: keep simple links
            <div className="flex items-center gap-2">
              <Link href="/feed" className="px-3 py-2 text-sm font-bold text-[var(--color-primary)] hover:opacity-80">My Feed</Link>
              {!pathname.startsWith('/auth/signin') && (
                <Link href="/auth/signin" className="px-3 py-2 text-sm font-bold text-[var(--color-primary)] hover:opacity-80">Sign In</Link>
              )}
              {!pathname.startsWith('/auth/register') && (
                <Link href="/auth/register" className="px-3 py-2 text-sm font-bold text-[var(--color-primary)] bg-white rounded-md hover:opacity-90">Sign Up</Link>
              )}
            </div>
          )}
        </div>
      </div>
      {/* Mobile dropdown menu */}
      {mobileMenuOpen && isAuthenticated && (
        <div ref={mobileMenuRef} className="md:hidden border-t border-gray-800 bg-[var(--color-surface)] text-[var(--color-primary)]">
          <div className="px-4 py-3 flex flex-col gap-2">
            {/* Exclude My learning and Learn from the dropdown since they're shown inline */}
            <Link href="/feed" onClick={() => setMobileMenuOpen(false)} className="block px-2 py-2 text-[var(--color-primary)] hover:opacity-80">My Feed</Link>
            {/* Lites option hidden */}
            <div className="h-px bg-[color:var(--color-primary)]/30 my-2" />
            <Link href="/my-profile" onClick={() => setMobileMenuOpen(false)} className="block px-2 py-2 text-[var(--color-primary)] hover:opacity-80">My Profile</Link>
            <button
              onClick={() => { setMobileMenuOpen(false); handleSignOutClick(); }}
              disabled={isSigningOut}
              className={`block w-full text-left px-2 py-2 ${isSigningOut ? 'text-[color:var(--color-primary)]/50' : 'text-[var(--color-primary)] hover:opacity-80'}`}
            >
              {isSigningOut ? 'Signing out…' : 'Sign Out'}
            </button>
          </div>
        </div>
      )}
    </header>
  );
}
