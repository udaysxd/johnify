export default function AboutPage() {
  return (
    <div className="min-h-screen bg-white dark:bg-gray-900">
      <section className="py-16 px-4 sm:px-6 lg:px-8 max-w-3xl mx-auto">
        <h1 className="text-3xl md:text-4xl font-bold text-gray-900 dark:text-white mb-4">About Us</h1>
        <p className="text-gray-700 dark:text-gray-300 text-lg leading-relaxed">
          Johnify is a personalised tutor AI app that helps you learn anything, anytime. We generate
          clear, high-quality explainer videos from your questions and pair them with an always-on AI tutor
          that adapts to your level, language, and pace. Our mission is to take you from “I don’t know” to
          “I know it” in minutes—no expensive lessons or complicated tools required.
        </p>
        <p className="mt-4 text-gray-700 dark:text-gray-300 text-lg leading-relaxed">
          With Johnify, you can create learning videos on demand, ask follow-up questions, and practice with
          interactive guidance. It’s fast, simple, and designed to make high-quality learning accessible to everyone.
        </p>
      </section>
    </div>
  );
}
