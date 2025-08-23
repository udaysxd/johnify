export default function PrivacyPage() {
  return (
    <div className="min-h-screen bg-white dark:bg-gray-900">
      <section className="py-16 px-4 sm:px-6 lg:px-8 max-w-3xl mx-auto">
        <h1 className="text-3xl md:text-4xl font-bold text-gray-900 dark:text-white mb-2">Privacy Policy</h1>
        <p className="text-sm text-gray-600 dark:text-gray-400 mb-6">
          Effective Date: 01 Aug 2025 · Last Updated: 23 Aug 2025
        </p>
        <div className="prose dark:prose-invert max-w-none">
          <p>
            Johnify (“we,” “our,” or “us”) values your privacy. This Privacy Policy explains how we collect, use, disclose,
            and protect your information when you use our website, app, and services (collectively, the “Services”). By
            using Johnify, you agree to this Privacy Policy. If you do not agree, please discontinue use of our Services.
          </p>

          <h2>1. Information We Collect</h2>
          <p>We collect the following categories of information:</p>
          <h3>(a) Information You Provide</h3>
          <ul>
            <li>Name, email address, and login details when you register.</li>
            <li>Information about your learning goals, quiz answers, or preferences that help us personalize your lessons.</li>
            <li>Payment information (processed securely via third-party providers).</li>
          </ul>
          <h3>(b) Automatically Collected Information</h3>
          <ul>
            <li>Device information (IP address, browser type, operating system).</li>
            <li>Usage data (pages visited, time spent, interactions).</li>
            <li>Cookies and similar technologies (see Section 9).</li>
          </ul>
          <h3>(c) Information from Third Parties</h3>
          <p>
            If you connect Johnify with third-party services (e.g., Google, social logins), we may receive profile data,
            consistent with your privacy settings on those platforms.
          </p>

          <h2>2. How We Use Your Information</h2>
          <ul>
            <li>Provide and improve our Services.</li>
            <li>Personalize your learning experience and generate adaptive content.</li>
            <li>Communicate with you about updates, support, and offers.</li>
            <li>Process payments and subscriptions.</li>
            <li>Ensure security, prevent fraud, and comply with legal obligations.</li>
          </ul>

          <h2>3. Legal Basis for Processing (GDPR)</h2>
          <p>If you are located in the European Economic Area (EEA) or UK, we process your personal data under the following legal bases:</p>
          <ul>
            <li><strong>Contractual necessity</strong> – to deliver our Services.</li>
            <li><strong>Legitimate interests</strong> – to improve learning outcomes and prevent misuse.</li>
            <li><strong>Consent</strong> – for personalized content, analytics, or marketing (you may withdraw at any time).</li>
            <li><strong>Legal obligation</strong> – where processing is required by law.</li>
          </ul>

          <h2>4. How We Share Your Information</h2>
          <p>We do not sell your personal data. We may share information only with:</p>
          <ul>
            <li>Service providers (cloud hosting, analytics, payment processors).</li>
            <li>Business transfers (e.g., merger, acquisition).</li>
            <li>Legal requirements (when required by law or to protect rights and safety).</li>
          </ul>
          <p>All partners are bound by confidentiality and data protection agreements.</p>

          <h2>5. International Data Transfers</h2>
          <p>
            Your data may be processed outside your country, including the United States and EU. We use safeguards such as
            Standard Contractual Clauses (SCCs) approved by the European Commission to ensure adequate protection under GDPR.
          </p>

          <h2>6. Data Retention</h2>
          <p>
            We keep personal data only as long as necessary to provide our Services, comply with legal obligations, and
            resolve disputes. You may request deletion at any time (see Section 8).
          </p>

          <h2>7. Security</h2>
          <p>
            We implement industry-standard measures (encryption, secure storage, access controls) to protect your data.
            However, no method of transmission is 100% secure, and we cannot guarantee absolute security.
          </p>

          <h2>8. Your Rights (GDPR &amp; CCPA)</h2>
          <p>Depending on your location, you have the right to:</p>
          <ul>
            <li>Access your personal data.</li>
            <li>Correct inaccurate or incomplete data.</li>
            <li>Request deletion (“right to be forgotten”).</li>
            <li>Restrict or object to processing.</li>
            <li>Data portability (request a copy in a machine-readable format).</li>
            <li>Withdraw consent at any time (without affecting prior lawful processing).</li>
            <li>File a complaint with your local Data Protection Authority (DPA).</li>
          </ul>
          <p>
            To exercise your rights, contact us at [Insert contact email].
          </p>

          <h2>9. Cookies &amp; Tracking</h2>
          <p>We use cookies to:</p>
          <ul>
            <li>Remember login sessions.</li>
            <li>Analyze performance and usage.</li>
            <li>Deliver personalized content.</li>
          </ul>
          <p>You can control cookies via your browser settings or opt-out of non-essential cookies.</p>

          <h2>10. Children’s Privacy</h2>
          <p>
            Johnify is not intended for children under 13 (or 16 in the EU). We do not knowingly collect data from children.
            If you believe a child has provided us with personal data, please contact us immediately.
          </p>

          <h2>11. Changes to This Policy</h2>
          <p>
            We may update this Privacy Policy from time to time. We will notify you of significant changes via email or
            through our app.
          </p>

          <h2>12. Contact Us</h2>
          <p>
            If you have any questions about this Privacy Policy or how we process your data, please contact us at:
          </p>
          <p>
            <strong>Johnify Privacy Team</strong><br />
            Email: hello@johnify.com
          </p>
          <p>
            If you are in the EU/UK, you may also contact our Data Protection Officer (DPO) at:<br />
            uday@johnify.com
          </p>
        </div>
      </section>
    </div>
  );
}
