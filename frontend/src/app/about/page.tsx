import Image from 'next/image';

export default function AboutPage() {
  return (
    <div className="min-h-screen bg-white dark:bg-gray-900">
      <section className="py-16 px-4 sm:px-6 lg:px-8 max-w-3xl mx-auto">
        <h1 className="text-3xl md:text-4xl font-bold text-gray-900 dark:text-white mb-4">About Us</h1>
        <p className="text-gray-700 dark:text-gray-300 text-lg leading-relaxed">
          At Johnify, we’re on a mission to transform learning by building the world’s most personalized AI tutor.
          Unlike traditional online courses or static video lessons, Johnify delivers adaptive, one-on-one educational
          experiences that respond to each learner’s unique needs in real time.
        </p>
        <p className="mt-4 text-gray-700 dark:text-gray-300 text-lg leading-relaxed">
          Our AI tutor doesn’t just present pre-recorded content. It actively assesses your knowledge gaps, learning
          style, and pace—then generates custom lessons, explanations, and practice problems designed just for you.
          Imagine having a dedicated tutor who knows exactly where you struggle with calculus or why photosynthesis
          isn’t clicking, and who can instantly create new explanations and exercises until you master the concept.
        </p>

        <h2 className="mt-8 text-2xl font-semibold text-gray-900 dark:text-white">What Makes Johnify Different?</h2>
        <ul className="mt-4 list-disc list-inside space-y-2 text-gray-700 dark:text-gray-300 text-lg">
          <li>Real-time knowledge assessment to identify gaps and misconceptions.</li>
          <li>Dynamic content generation with personalized explanations, examples, and practice problems.</li>
          <li>Adaptive pacing that adjusts speed based on your comprehension.</li>
          <li>Multi-modal teaching (visual, auditory, text) aligned to your learning preferences.</li>
          <li>Continuous feedback loops that refine the teaching approach as you learn.</li>
        </ul>

        <p className="mt-6 text-gray-700 dark:text-gray-300 text-lg leading-relaxed">
          We’re building more than just another edtech tool—we’re creating a true AI-powered tutor that thinks, adapts,
          and creates, replicating the intuition of a great human teacher, but available 24/7, anywhere in the world.
          With Johnify, learning becomes personal, interactive, and limitless.
        </p>

        {/* Team */}
        <div className="mt-12">
          <h2 className="text-2xl font-semibold text-gray-900 dark:text-white">Our Team</h2>
          <div className="mt-6 grid gap-8 sm:grid-cols-2">
            <div className="rounded-lg border border-gray-200 dark:border-gray-800 p-5">
              <div className="mb-4 flex items-center justify-center">
                <Image
                  src="/images/founders/uday.jpg"
                  alt="Uday Singh"
                  width={96}
                  height={96}
                  className="rounded-full object-cover w-24 h-24"
                  priority
                />
              </div>
              <h3 className="text-xl font-medium text-gray-900 dark:text-white">Uday Singh</h3>
              <p className="text-gray-600 dark:text-gray-300">Co-Founder</p>
              <p className="mt-2 text-gray-700 dark:text-gray-300">
                Past: <span className="font-medium">Product Management</span> at <span className="font-medium">Forbes, eBay, Starbucks</span>
              </p>
              <div className="mt-3">
                <a
                  href="https://www.linkedin.com/in/udsingh1/"
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label="Uday Singh on LinkedIn"
                  className="inline-flex items-center gap-2 text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5">
                    <path d="M19 0H5C2.24 0 0 2.24 0 5v14c0 2.76 2.24 5 5 5h14c2.76 0 5-2.24 5-5V5c0-2.76-2.24-5-5-5zM8.34 18.67H5.67V9.33h2.67v9.34zM7 8.13A1.55 1.55 0 1 1 7 5a1.55 1.55 0 0 1 0 3.13zM20 18.67h-2.67v-4.8c0-1.15-.02-2.63-1.6-2.63-1.6 0-1.84 1.25-1.84 2.55v4.88h-2.66V9.33h2.55v1.28h.04c.36-.68 1.26-1.4 2.59-1.4 2.77 0 3.28 1.82 3.28 4.2v5.26z" />
                  </svg>
                  <span className="sr-only">LinkedIn</span>
                </a>
              </div>
            </div>
            <div className="rounded-lg border border-gray-200 dark:border-gray-800 p-5">
              <div className="mb-4 flex items-center justify-center">
                <Image
                  src="/images/founders/prashant.png"
                  alt="Prashant More"
                  width={96}
                  height={96}
                  className="rounded-full object-cover w-24 h-24"
                  priority
                />
              </div>
              <h3 className="text-xl font-medium text-gray-900 dark:text-white">Prashant More</h3>
              <p className="text-gray-600 dark:text-gray-300">Co-Founder</p>
              <p className="mt-2 text-gray-700 dark:text-gray-300">
                Past: <span className="font-medium">Founder</span> at <span className="font-medium">Engg.tv, Vidyanti</span>
              </p>
              <div className="mt-3">
                <a
                  href="https://www.linkedin.com/in/profprashantmore/"
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label="Prashant More on LinkedIn"
                  className="inline-flex items-center gap-2 text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5">
                    <path d="M19 0H5C2.24 0 0 2.24 0 5v14c0 2.76 2.24 5 5 5h14c2.76 0 5-2.24 5-5V5c0-2.76-2.24-5-5-5zM8.34 18.67H5.67V9.33h2.67v9.34zM7 8.13A1.55 1.55 0 1 1 7 5a1.55 1.55 0 0 1 0 3.13zM20 18.67h-2.67v-4.8c0-1.15-.02-2.63-1.6-2.63-1.6 0-1.84 1.25-1.84 2.55v4.88h-2.66V9.33h2.55v1.28h.04c.36-.68 1.26-1.4 2.59-1.4 2.77 0 3.28 1.82 3.28 4.2v5.26z" />
                  </svg>
                  <span className="sr-only">LinkedIn</span>
                </a>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
