export default function PrivacyPage() {
  return (
    <div className="min-h-screen bg-white dark:bg-gray-900">
      <section className="py-16 px-4 sm:px-6 lg:px-8 max-w-3xl mx-auto">
        <h1 className="text-3xl md:text-4xl font-bold text-gray-900 dark:text-white mb-4">Privacy Policy</h1>
        <p className="text-gray-700 dark:text-gray-300 mb-6">
          Your privacy matters to us. This policy explains what information Johnify collects and how we use it.
        </p>
        <div className="prose dark:prose-invert max-w-none">
          <h2>Information We Collect</h2>
          <p>
            We may collect account details (like email), usage data, and content you submit to generate videos or interact
            with the AI tutor. We use cookies or similar technologies to improve the service.
          </p>
          <h2>How We Use Information</h2>
          <p>
            We use your information to operate and improve the service, personalize your learning experience, provide
            support, and maintain security.
          </p>
          <h2>Data Sharing</h2>
          <p>
            We do not sell your personal data. We may share limited information with service providers who help us run
            Johnify, under appropriate confidentiality and security obligations.
          </p>
          <h2>Data Retention</h2>
          <p>
            We retain information as long as necessary to provide the service and comply with legal obligations. You may
            request deletion of your account subject to applicable laws.
          </p>
          <h2>Your Choices</h2>
          <p>
            You can update account information, manage cookies via your browser, and contact us for privacy-related
            requests.
          </p>
          <h2>Changes</h2>
          <p>
            We may update this policy from time to time. We will indicate the date of the latest revision at the top of
            the page.
          </p>
        </div>
      </section>
    </div>
  );
}
