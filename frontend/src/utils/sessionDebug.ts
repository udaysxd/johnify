import React from 'react';

// Debug utility to check session storage
export function logSessionInfo() {
  if (typeof window === 'undefined') {
    console.log('Running on server side');
    return;
  }

  console.group('Session Debug Info');
  
  // Check cookies
  console.log('Cookies:', document.cookie);
  
  // Check localStorage
  console.log('localStorage:');
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (key && key.startsWith('next-auth.')) {
      console.log(`  ${key}:`, localStorage.getItem(key));
    }
  }
  
  // Check sessionStorage
  console.log('sessionStorage:');
  for (let i = 0; i < sessionStorage.length; i++) {
    const key = sessionStorage.key(i);
    if (key && key.startsWith('next-auth.')) {
      console.log(`  ${key}:`, sessionStorage.getItem(key));
    }
  }
  
  console.groupEnd();
}

// Call this function in your components to debug session issues
export function useSessionDebug() {
  React.useEffect(() => {
    logSessionInfo();
  }, []);
}
