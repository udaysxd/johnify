import HeroVideo from '@/components/HeroVideo';
import PromptDemo from '@/components/PromptDemo';
import SignupCTA from '@/components/SignupCTA';

export default function OldHome() {
  return (
    <div className="min-h-screen">
      {/* Hero Section */}
      <section className="pt-10 pb-20 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto section-warm">
        <div className="grid grid-cols-1 gap-8 items-stretch">
          {/* Left Hero - JohnifyCREATE */}
          <div className="text-center card-surface p-8 h-full">
            <p className="text-sm font-semibold tracking-wide text-blue-600 mb-3">
              johnifyLEARN
              <span className="ml-2 inline-flex items-center rounded-full border border-blue-200 bg-blue-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-blue-700 dark:border-blue-900/40 dark:bg-blue-900/20 dark:text-blue-300">Beta</span>
            </p>
            <h1 className="text-4xl md:text-5xl font-bold text-gray-900 dark:text-white mb-6">
              Ready to Learn Something New? 
            </h1>
            <p className="text-lg md:text-xl text-gray-600 dark:text-gray-300 mb-8 md:mb-10 max-w-2xl mx-auto">
              Join thousands of students who are using Johnify to learn anything free of cost.
            </p>
            <div className="flex justify-center">
              <a
                href="/mlites"
                className="btn-primary text-lg"
              >
                Learn Now
              </a>
            </div>
          </div>

          {/* Right Hero - JohnifyTutor (temporarily hidden) */}
          {/**
          <div className="text-center md:text-left bg-gray-50 dark:bg-gray-800/60 rounded-2xl p-8 border border-gray-100 dark:border-gray-700 shadow-sm h-full">
            <p className="text-sm font-semibold tracking-wide text-purple-600 mb-3">
              johnifyTUTOR
              <span className="ml-2 inline-flex items-center rounded-full border border-purple-200 bg-purple-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-purple-700 dark:border-purple-900/40 dark:bg-purple-900/20 dark:text-purple-300">Beta</span>
            </p>
            <h2 className="text-4xl md:text-5xl font-bold text-gray-900 dark:text-white mb-6">
              Get your personalised AI tutor
            </h2>
            <p className="text-lg md:text-xl text-gray-600 dark:text-gray-300 mb-8 max-w-2xl mx-auto md:mx-0">
              Learn anything anywhere 24x7 with your own tutor in your own language. No need to pay for expensive tutors.
            </p>
            <div className="flex justify-center md:justify-start">
              <a
                href="/tutor"
                className="bg-purple-600 hover:bg-purple-700 text-white font-medium py-3 px-8 rounded-lg text-lg transition-colors inline-block"
              >
                Create Tutor
              </a>
            </div>
          </div>
          **/}
        </div>

        {/* Hero Video */}
        <div className="mt-16 rounded-xl overflow-hidden shadow-2xl">
          <HeroVideo src="https://storage.googleapis.com/assets-johnify/homepage/hero.mp4" />
        </div>
      </section>

      {/* Prompt-to-Video Section */}
      <section className="relative py-20 px-4 sm:px-6 lg:px-8 overflow-hidden section-warm">
        {/* decorative background */}
        <div className="pointer-events-none absolute inset-0" />
        <div className="max-w-7xl mx-auto relative">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-12 items-start">
            {/* Copy */}
            <div>
              <h3 className="text-sm font-semibold tracking-wide text-blue-600 mb-3">
                johnifyLEARN
                <span className="ml-2 inline-flex items-center rounded-full border border-blue-200 bg-blue-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-blue-700 dark:border-blue-900/40 dark:bg-blue-900/30 dark:text-blue-300">Beta</span>
              </h3>
              <h2 className="text-4xl md:text-5xl font-bold text-gray-900 dark:text-white mb-4">From question to video answer in seconds.</h2>
              <p className="text-lg md:text-xl text-gray-600 dark:text-gray-300 mb-8 max-w-2xl">
                Learn instantly and effortlessly with our generative AI video maker. Go from the state &#39;I don&#39;t know&#39; to &#39;I know it&#39; in minutes.
              </p>
              {/* CTA moved below input as 'Learn with Video' */}
            </div>

            {/* Demo input */}
            <div className="bg-white/80 dark:bg-gray-900/70 backdrop-blur rounded-2xl border border-gray-200/80 dark:border-gray-800/80 shadow-lg p-6 ring-1 ring-gray-200/60 dark:ring-gray-700/50 hover:shadow-xl transition-shadow">
              <PromptDemo />
            </div>
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section className="py-16 bg-gray-50 dark:bg-gray-800">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <h2 className="text-3xl font-bold text-center text-gray-900 dark:text-white mb-12">
            Why Choose Our Personalised AI Tutor?
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {[
              {
                title: "Lightning Fast",
                description: "Learn anything in minutes, not hours. Our AI handles the heavy lifting so you don't have to.",
                icon: "⚡",
                iconBg: "bg-blue-50 dark:bg-blue-900/30",
                iconText: "text-blue-700 dark:text-blue-300",
                ring: "ring-blue-100 dark:ring-blue-900/30",
              },
              {
                title: "Easy to Use",
                description: "No special skills needed. Learn anything with just a few clicks.",
                icon: "🎯",
                iconBg: "bg-fuchsia-50 dark:bg-fuchsia-900/30",
                iconText: "text-fuchsia-700 dark:text-fuchsia-300",
                ring: "ring-fuchsia-100 dark:ring-fuchsia-900/30",
              },
              {
                title: "High Quality",
                description: "Get high-quality content videos with our advanced AI technology.",
                icon: "✨",
                iconBg: "bg-amber-50 dark:bg-amber-900/30",
                iconText: "text-amber-700 dark:text-amber-300",
                ring: "ring-amber-100 dark:ring-amber-900/30",
              }
            ].map((feature, index) => (
              <div
                key={index}
                className="group relative bg-white dark:bg-gray-700/80 backdrop-blur-sm p-6 rounded-xl border border-gray-200/70 dark:border-gray-600 shadow-sm hover:shadow-lg transition-all duration-200 hover:-translate-y-0.5"
              >
                <div className={`w-12 h-12 rounded-xl flex items-center justify-center mb-4 ${feature.iconBg} ${feature.ring} ring-1`}>
                  <span className={`text-2xl ${feature.iconText}`}>{feature.icon}</span>
                </div>
                <h3 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">
                  {feature.title}
                </h3>
                <p className="text-gray-600 dark:text-gray-300">
                  {feature.description}
                </p>
                <div className="pointer-events-none absolute inset-x-0 bottom-0 h-px bg-gradient-to-r from-transparent via-gray-200/70 to-transparent dark:via-gray-600" />
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Removed separate CTA section — integrated into right hero column */}
      <SignupCTA />
    </div>
  );
}
