import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/contexts/AuthContext";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import ServiceWorker from "@/components/ServiceWorker";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Johnify - Interactive Social Learning",
  description: "Interactive social learning platform AI-powered",
  metadataBase: new URL(process.env.NEXT_PUBLIC_APP_URL || 'http://localhost:3000'),
  manifest: "/manifest.json",
  themeColor: "#0f172a", // slate-900
  icons: {
    icon: [
      { url: "/favicon.ico" },
      { url: "/favicon-32x32.png", sizes: "32x32", type: "image/png" },
      { url: "/favicon-16x16.png", sizes: "16x16", type: "image/png" },
   ],
    apple: [
      { url: "/logo192.png" },
    ],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
        <AuthProvider>
          <div className="min-h-screen bg-gray-50">
            <Header />
            <main className="container mx-auto px-4 py-8">
              {children}
            </main>
            <Footer />
          </div>
          {/* Register service worker for PWA */}
          <ServiceWorker />
        </AuthProvider>
      </body>
    </html>
  );
}
