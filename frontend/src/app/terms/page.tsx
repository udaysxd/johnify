export default function TermsPage() {
  return (
    <div className="min-h-screen bg-white dark:bg-gray-900">
      <section className="py-16 px-4 sm:px-6 lg:px-8 max-w-3xl mx-auto">
        <h1 className="text-3xl md:text-4xl font-bold text-gray-900 dark:text-white mb-4">Terms of Service</h1>
        <p className="text-gray-700 dark:text-gray-300 mb-6">
          Welcome to Johnify. By accessing or using our personalised tutor AI app, you agree to the following terms.
        </p>
        <div className="prose dark:prose-invert max-w-none">
          <h2>Use of Service</h2>
          <p>
            Johnify provides tools to generate educational videos and interact with an AI tutor. You agree to use the
            service responsibly and comply with all applicable laws.
          </p>
          <h2>Accounts</h2>
          <p>
            You are responsible for safeguarding your account credentials and for activities that occur under your account.
          </p>
          <h2>Content</h2>
          <p>
            You retain rights to content you provide. By using our service, you grant us a limited license to process
            and display your content for the purpose of providing the service.
          </p>
          <h2>Disclaimer</h2>
          <p>
            The service is provided “as is” without warranties of any kind. We do not guarantee accuracy or fitness for
            a particular purpose.
          </p>
          <h2>Changes</h2>
          <p>
            We may update these terms from time to time. Continued use of the service indicates acceptance of the updated terms.
          </p>
        </div>
      </section>
    </div>
  );
}
