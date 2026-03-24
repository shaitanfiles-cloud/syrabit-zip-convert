import { PublicLayout } from '@/components/layout/PublicLayout';

export default function PrivacyPage() {
  return (
    <PublicLayout>
      <div className="min-h-screen bg-[#06060e] py-24 px-4">
        <div className="max-w-3xl mx-auto">
          <h1 className="text-3xl font-semibold text-white mb-2">Privacy Policy</h1>
          <p className="text-white/50 text-sm mb-10">Last updated: January 2025</p>
          <div className="space-y-8 text-white/70 leading-relaxed">
            {[
              { title: '1. Information We Collect', body: 'We collect: account information (name, email), usage data (subjects accessed, questions asked), and technical information (device type, browser). We do not collect payment card details directly.' },
              { title: '2. How We Use Your Data', body: 'Your data is used to provide personalized educational assistance, track your learning progress, improve our AI responses, and maintain your account.' },
              { title: '3. Data Storage', body: 'Your account data and chat conversations are securely stored in our database. AI conversations are stored server-side to provide continuity across devices.' },
              { title: '4. Data Sharing', body: 'We do not sell your personal data. We may share anonymized, aggregated data for research purposes. We use third-party AI providers (Groq) to power responses, governed by their privacy policies.' },
              { title: '5. Data Security', body: 'We use industry-standard encryption and security practices to protect your data. Passwords are stored using bcrypt hashing.' },
              { title: '6. Your Rights', body: 'You have the right to access, correct, or delete your personal data. You can delete your account from the Profile page. Deletion is completed within 72 hours.' },
              { title: '7. Cookies', body: 'We use local storage (not cookies) to maintain your session. No tracking cookies are used.' },
              { title: '8. Children\'s Privacy', body: 'Our service is intended for students aged 16 and above. We do not knowingly collect data from children under 13.' },
              { title: '9. Contact', body: 'For privacy concerns, contact us at privacy@syrabit.ai' },
            ].map(({ title, body }) => (
              <div key={title}>
                <h2 className="text-white font-semibold mb-2">{title}</h2>
                <p>{body}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </PublicLayout>
  );
}
