/**
 * Gets the backend URL based on the current environment
 * @returns {string} The backend URL
 */
export function getBackendUrl(): string {
  // In development, use localhost with the backend port
  if (process.env.NODE_ENV === 'development') {
    return process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';
  }
  
  // In production, use the production backend URL
  return process.env.NEXT_PUBLIC_BACKEND_URL || 'https://api.johnify.com';
}
