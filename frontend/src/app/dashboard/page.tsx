'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useSession } from 'next-auth/react';
import Link from 'next/link';

export default function DashboardPage() {
  const { data: session, status } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (status === 'unauthenticated') {
      router.push('/auth/login');
    }
  }, [status, router]);

  if (status === 'loading') {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-indigo-500"></div>
      </div>
    );
  }

  if (status === 'unauthenticated') {
    return null; // Will be redirected by the useEffect
  }

  return (
    <div className="py-12">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-center">
          <h1 className="text-3xl font-bold text-gray-900 mb-6">
            Welcome back, {session?.user?.name || 'User'}!
          </h1>
          <p className="text-lg text-gray-600 mb-8">
            What would you like to do today?
          </p>
          
          <div className="mt-10 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
            <DashboardCard 
              title="Start Learning" 
              description="Explore new topics and expand your knowledge."
              href="/learn"
              buttonText="Start Learning"
            />
            <DashboardCard 
              title="Your Progress" 
              description="Track your learning journey and achievements."
              href="/progress"
              buttonText="View Progress"
            />
            <DashboardCard 
              title="Saved Content" 
              description="Access your saved lessons and bookmarks."
              href="/saved"
              buttonText="View Saved"
            />
          </div>
        </div>
      </div>
    </div>
  );
}

function DashboardCard({ 
  title, 
  description, 
  href, 
  buttonText 
}: { 
  title: string; 
  description: string; 
  href: string; 
  buttonText: string 
}) {
  return (
    <div className="bg-white overflow-hidden shadow rounded-lg">
      <div className="px-4 py-5 sm:p-6">
        <h3 className="text-lg leading-6 font-medium text-gray-900">
          {title}
        </h3>
        <div className="mt-2 max-w-xl text-sm text-gray-500">
          <p>{description}</p>
        </div>
        <div className="mt-5">
          <Link
            href={href}
            className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500"
          >
            {buttonText}
          </Link>
        </div>
      </div>
    </div>
  );
}
