import HeroVideo from '@/components/HeroVideo';

export default function Home() {
  return (
    <div className="min-h-screen bg-white dark:bg-gray-900">
      {/* Hero Section */}
      <section className="py-20 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto">
        <div className="text-center">
          <h1 className="text-4xl md:text-6xl font-bold text-gray-900 dark:text-white mb-6">
            Get your personalised AI tutor
          </h1>
          <p className="text-xl text-gray-600 dark:text-gray-300 mb-10 max-w-3xl mx-auto">
            Learn anything anywhere 24x7 with your own tutor in your own language. 
            No need to pay for expensive tutors.
          </p>
          <div className="flex justify-center">
            <a 
              href="/learn"
              className="bg-blue-600 hover:bg-blue-700 text-white font-medium py-3 px-8 rounded-lg text-lg transition-colors inline-block"
            >
              Start Learning for Free
            </a>
          </div>
        </div>

        {/* Hero Video */}
        <div className="mt-16 rounded-xl overflow-hidden shadow-2xl">
          <HeroVideo src="https://storage.googleapis.com/assets-johnify/homepage/learn_ancient_rome_1754906885.mp4" />
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
                icon: "⚡"
              },
              {
                title: "Easy to Use",
                description: "No special skills needed. Learn anything with just a few clicks.",
                icon: "🎯"
              },
              {
                title: "High Quality",
                description: "Get high-quality content videos with our advanced AI technology.",
                icon: "✨"
              }
            ].map((feature, index) => (
              <div key={index} className="bg-white dark:bg-gray-700 p-6 rounded-xl shadow-sm">
                <div className="text-4xl mb-4">{feature.icon}</div>
                <h3 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">{feature.title}</h3>
                <p className="text-gray-600 dark:text-gray-300">{feature.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-20 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto text-center">
        <h2 className="text-3xl font-bold text-gray-900 dark:text-white mb-6">
          Ready to Learn Something New?
        </h2>
        <p className="text-xl text-gray-600 dark:text-gray-300 mb-8 max-w-2xl mx-auto">
          Join thousands of students who are already using our personalised AI tutor to bridge the gap between learning and success.
        </p>
        <a 
          href="/quiz"
          className="bg-blue-600 hover:bg-blue-700 text-white font-medium py-3 px-8 rounded-lg text-lg transition-colors inline-block"
        >
          Start Learning for Free
        </a>
      </section>
    </div>
  );
}
