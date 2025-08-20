export default function ContactPage() {
  return (
    <div className="min-h-screen bg-white dark:bg-gray-900">
      <section className="py-16 px-4 sm:px-6 lg:px-8 max-w-3xl mx-auto">
        <h1 className="text-3xl md:text-4xl font-bold text-gray-900 dark:text-white mb-4">Contact Us</h1>
        <p className="text-gray-700 dark:text-gray-300 mb-8">
          Have questions, feedback, or partnership ideas? We’d love to hear from you.
        </p>
        <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-6 shadow-sm">
          <ul className="space-y-3 text-gray-700 dark:text-gray-300">
            <li><span className="font-medium">Email:</span> hello@johnify.com</li>
            <li><span className="font-medium">Twitter:</span> <a href="https://x.com/johnifyAI" className="text-blue-600 dark:text-blue-400 hover:underline">@johnify</a></li>
            <li><span className="font-medium">LinkedIn:</span> <a href="https://www.linkedin.com/" className="text-blue-600 dark:text-blue-400 hover:underline">johnify</a></li>
          </ul>
        </div>
      </section>
    </div>
  );
}
