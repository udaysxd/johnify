import NextAuth from 'next-auth';
import Credentials from 'next-auth/providers/credentials';

declare module 'next-auth' {
  interface Session {
    user: {
      id: string;
      name?: string | null;
      email?: string | null;
      image?: string | null;
    };
    accessToken?: string;
    expires: Date | string;
  }

  interface User {
    id: string;
    name?: string | null;
    email?: string | null;
    accessToken?: string;
  }
}

// Ensure the secret is available at build time
const secret = process.env.NEXTAUTH_SECRET;
if (!secret) {
  throw new Error('NEXTAUTH_SECRET is not set. Please check your .env.local file and restart the development server.');
}

const authConfig = {
  // Trust the host header in development
  trustHost: process.env.NODE_ENV !== 'production',
  
  // Session configuration
  session: {
    strategy: 'jwt' as const,
    maxAge: 30 * 24 * 60 * 60, // 30 days
  },
  
  // Pages configuration
  pages: {
    signIn: '/auth/signin',
    signOut: '/auth/signout',
    error: '/auth/error',
  },
  
  // Providers configuration
  providers: [
    Credentials({
      name: 'Credentials',
      credentials: {
        username: { label: 'Username', type: 'text' },
        password: { label: 'Password', type: 'password' },
      },
      async authorize(credentials) {
        try {
          if (!credentials?.username || !credentials?.password) {
            throw new Error('Username and password are required');
          }

          // Using OAuth2 password flow as per backend
          const params = new URLSearchParams();
          if (typeof credentials.username !== 'string' || typeof credentials.password !== 'string') {
            throw new Error('Username and password must be strings');
          }
          params.append('username', credentials.username);
          params.append('password', credentials.password);
          
          const loginUrl = `${process.env.NEXT_PUBLIC_API_URL}/api/auth/login`;
          console.log('Sending login request to:', loginUrl);
          
          const response = await fetch(loginUrl, {
            method: 'POST',
            headers: { 
              'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: params.toString(),
          });

          console.log('Login response status:', response.status);
          
          let responseData;
          try {
            responseData = await response.json();
            console.log('Login response data:', responseData);
          } catch (e) {
            console.error('Failed to parse JSON response:', e);
            throw new Error('Invalid response from server');
          }

          if (!response.ok) {
            console.error('Login failed with status:', response.status, 'Data:', responseData);
            throw new Error(responseData.detail || responseData.message || 'Authentication failed');
          }

          // Return user object with access token
          return {
            id: '1', // You might want to get a real user ID from your backend
            name: typeof credentials.username === 'string' ? credentials.username : null,
            email: typeof credentials.username === 'string' ? credentials.username : null, // or get from response if available
            accessToken: typeof responseData.access_token === 'string' ? responseData.access_token : '',
          };
          
        } catch (error) {
          console.error('Authentication error:', error);
          if (error instanceof Error) {
            throw error;
          }
          throw new Error('An error occurred during authentication');
        }
      },
    }),
  ],
  
  // Secret for signing tokens - using the validated secret
  secret: secret,
  
  // Callbacks
  callbacks: {
    async jwt({ token, user, account }: { token: import('next-auth/jwt').JWT; user?: import('next-auth').User; account?: import('next-auth').Account | null }) {
      // Initial sign in
      if (user && account) {
        return {
          ...token,
          accessToken: user.accessToken || account.access_token,
          user: {
            id: user.id,
            name: user.name || null,
            email: user.email || null,
          },
        };
      }
      return token;
    },
    
    async session({ session, token }: { session: import('next-auth').Session; token: import('next-auth/jwt').JWT }) {
      // Send properties to the client
      if (token) {
        session.user = {
          ...session.user,
          id: typeof token.user === 'object' && token.user && 'id' in token.user && typeof (token.user as { id?: unknown }).id === 'string'
            ? (token.user as { id: string }).id
            : (typeof token.sub === 'string' ? token.sub : ''),
          name: typeof token.user === 'object' && token.user && 'name' in token.user && typeof (token.user as { name?: unknown }).name === 'string'
            ? (token.user as { name: string }).name
            : (typeof token.name === 'string' ? token.name : null),
          email: typeof token.user === 'object' && token.user && 'email' in token.user && typeof (token.user as { email?: unknown }).email === 'string'
            ? (token.user as { email: string }).email
            : (typeof token.email === 'string' ? token.email : null),
        }
;
        
        // Make sure to include the accessToken in the session
        if (token.accessToken) {
          session.accessToken = token.accessToken;
        }
        
        // Set session expiration (24 hours from now)
        session.expires = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString();
        
      }
      
      return session;
    },
  },
  
  // Enable debug in development
  debug: process.env.NODE_ENV === 'development',
};

// Initialize NextAuth with our configuration
const { handlers, ...rest } = NextAuth(authConfig);

// Export the auth methods and handlers
export const { auth, signIn, signOut } = rest;
export { handlers };

export default auth;
