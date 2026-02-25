import Link from 'next/link';
export default function Footer() {
  const year = new Date().getFullYear();
  return (
    <footer className="border-t border-gray-200 bg-[var(--color-surface)] text-[var(--color-primary)]">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex flex-col md:flex-row items-center md:items-start justify-between gap-6">
          {/* Brand */}
          <div className="text-center md:text-left">
            <span className="text-lg font-semibold text-[var(--color-primary)]">johnify</span>
            <p className="text-sm text-[var(--color-primary)] mt-1">World&apos;s first Social learning app. Casual learning every day.</p>
            <div className="mt-2 flex items-center justify-center md:justify-start gap-2 text-[var(--color-primary)]">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4" aria-hidden="true">
                <path d="M12 2C8.685 2 6 4.686 6 8c0 4.418 6 12 6 12s6-7.582 6-12c0-3.314-2.686-6-6-6zm0 8.5A2.5 2.5 0 1 1 12 5.5a2.5 2.5 0 0 1 0 5z" />
              </svg>
              <span className="text-xs">London, UK</span>
            </div>
          </div>

          {/* Nav (two lines) */}
          <nav className="w-full md:w-auto text-sm">
            <div className="flex flex-wrap items-center justify-center md:justify-start gap-x-6 gap-y-2">
              <Link href="/" className="text-[var(--color-primary)] hover:opacity-80 transition-colors">Home</Link>
              <Link href="/mlites" className="text-[var(--color-primary)] hover:opacity-80 transition-colors">Learn Now</Link>
            </div>
            <div className="mt-2 flex flex-wrap items-center justify-center md:justify-start gap-x-6 gap-y-2">
              <Link href="/about" className="text-[var(--color-primary)] hover:opacity-80 transition-colors">About Us</Link>
              <Link href="/contact" className="text-[var(--color-primary)] hover:opacity-80 transition-colors">Contact Us</Link>
            </div>
          </nav>
        </div>

        <div className="mt-6 pt-6 border-t border-[color:var(--color-primary)]/30 flex flex-col md:flex-row items-center justify-between gap-4">
          <div className="text-center md:text-left">
            <p className="text-xs text-[var(--color-primary)]"> {year} johnify. All rights reserved.</p>
            <p className="text-xs text-[var(--color-primary)] mt-1">
              Images are powered by{' '}
              <a
                href="https://pollinations.ai"
                target="_blank"
                rel="noopener noreferrer"
                className="underline hover:opacity-80"
                title="Pollinations.ai"
              >
                pollinations.ai
              </a>
            </p>
          </div>
          <div className="flex items-center gap-4">
            {/* Social icons */}
            <a
              href="https://x.com/johnifyAI"
              target="_blank"
              rel="noopener noreferrer"
              aria-label="Twitter"
              className="text-[var(--color-primary)] hover:opacity-80 transition-colors"
              title="Twitter"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-5 w-5">
                <path d="M20.945 7.54c.014.2.014.401.014.602 0 6.13-4.665 13.2-13.2 13.2-2.624 0-5.06-.766-7.107-2.083.365.042.716.056 1.095.056a9.33 9.33 0 0 0 5.783-1.988 4.66 4.66 0 0 1-4.347-3.224c.287.043.574.071.875.071.417 0 .833-.057 1.221-.157a4.653 4.653 0 0 1-3.73-4.566v-.057c.616.344 1.33.559 2.087.587A4.65 4.65 0 0 1 1.94 5.3c0-.86.23-1.65.63-2.338a13.23 13.23 0 0 0 9.603 4.87 4.64 4.64 0  0 1-.115-1.063 4.652 4.652 0  0 1 8.049-3.18 9.16 9.16 0 0 0 2.95-1.124 4.66 4.66 0 0 1-2.045 2.567 9.32 9.32 0 0 0 2.679-.73 9.986 9.986 0 0 1-2.36 2.159z" />
              </svg>
            </a>
            <a
              href="https://www.linkedin.com/company/johnify/"
              target="_blank"
              rel="noopener noreferrer"
              aria-label="LinkedIn"
              className="text-[#2e4d4b] hover:opacity-80 transition-colors"
              title="LinkedIn"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-5 w-5">
                <path d="M4.98 3.5C4.98 4.88 3.86 6 2.5 6S0 4.88 0 3.5 1.12 1 2.5 1s2.48 1.12 2.48 2.5zM.5 8h4V24h-4V8zm7.5 0h3.8v2.2h.05c.53-1 1.83-2.2 3.77-2.2 4.03 0  4.78 2.65 4.78 6.1V24h-4v-8.2c0-1.95-.03-4.45-2.71-4.45-2.71 0-3.13 2.12-3.13 4.31V24h-4V8z" />
              </svg>
            </a>
            <a
              href="https://www.youtube.com/@JohnifyAI"
              target="_blank"
              rel="noopener noreferrer"
              aria-label="YouTube"
              className="text-[#2e4d4b] hover:opacity-80 transition-colors"
              title="YouTube"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-5 w-5">
                <path d="M23.498 6.186a2.999 2.999 0 0 0-2.113-2.12C19.6 3.5 12 3.5 12 3.5s-7.6 0-9.385.566A3 3 0 0 0 .502 6.186C0 7.974 0 12 0 12s0 4.026.502 5.814a2.999 2.999 0 0 0 2.113 2.12C4.4 20.5 12 20.5 12 20.5s7.6 0 9.385-.566a2.999 2.999 0 0 0 2.113-2.12C24 16.026 24 12 24 12s0-4.026-.502-5.814ZM9.75 15.5v-7l6 3.5-6 3.5Z" />
              </svg>
            </a>
            {/* Legal */}
            <div className="flex items-center flex-wrap gap-4 text-xs">
              <Link href="/terms" className="text-[var(--color-primary)] hover:opacity-80">Terms</Link>
              <span className="text-[color:var(--color-primary)]/50">•</span>
              <Link href="/privacy" className="text-[var(--color-primary)] hover:opacity-80">Privacy</Link>
            </div>
          </div>
        </div>
      </div>
    </footer>
  );
}
