import { PublicLayout } from '@/components/layout/PublicLayout';
import PageMeta from '@/components/seo/PageMeta';

export default function AboutPage() {
  return (
    <PublicLayout>
      <PageMeta
        title="About Syrabit.ai"
        description="Syrabit.ai is the AI-powered educational browser for AHSEC, SEBA and Degree students in Assam. Learn about our mission, platform, and how we help students succeed."
        url="https://syrabit.ai/about"
      />
      <div className="min-h-screen bg-[#06060e] pt-8 pb-24 px-4">
        <div className="max-w-3xl mx-auto">
          <h1 className="text-3xl font-semibold text-white mb-2">About Syrabit.ai</h1>
          <p className="text-white/50 text-sm mb-10">The Educational Browser for Assam Board Students</p>

          <div className="space-y-8 text-white/70 leading-relaxed">
            <div>
              <h2 className="text-white font-semibold mb-2">Our Mission</h2>
              <p>
                Syrabit.ai is built for students of Assam — covering AHSEC (Class 11–12), SEBA, and Degree
                (B.Com, B.A, B.Sc) syllabi. We provide syllabus-aligned study notes, previous year questions,
                MCQs, important questions, and an AI tutor that answers only within your syllabus.
              </p>
            </div>

            <div>
              <h2 className="text-white font-semibold mb-2">What We Offer</h2>
              <ul className="list-disc list-inside space-y-2">
                <li>Chapter-wise notes aligned to official AHSEC and Degree syllabi</li>
                <li>Previous Year Questions (PYQs) with solutions</li>
                <li>MCQs and important questions for exam preparation</li>
                <li>AI tutor (Syra) that stays within your syllabus — no hallucination, no off-topic answers</li>
                <li>Support for multiple subjects across Science, Commerce, and Arts streams</li>
              </ul>
            </div>

            <div>
              <h2 className="text-white font-semibold mb-2">How Syra Works</h2>
              <p>
                Syra is our AI study assistant. Unlike generic chatbots, Syra uses a multi-stage retrieval
                pipeline specifically designed to keep answers grounded in your actual chapter content.
                If Syra cannot find relevant material with high confidence, it explicitly tells you rather
                than making something up. Every answer cites the source chapter and subject.
              </p>
            </div>

            <div>
              <h2 className="text-white font-semibold mb-2">Who We Serve</h2>
              <p>
                We serve students across Assam preparing for board exams and university exams under
                AHSEC, SEBA, Gauhati University, and Dibrugarh University curricula. Our content covers
                Class 11, Class 12, and undergraduate degree programmes.
              </p>
            </div>

            <div>
              <h2 className="text-white font-semibold mb-2">Contact</h2>
              <p>
                For questions, feedback, or partnerships, reach us at{' '}
                <a href="mailto:support@syrabit.ai" className="text-violet-400 hover:underline">
                  support@syrabit.ai
                </a>
              </p>
            </div>
          </div>
        </div>
      </div>
    </PublicLayout>
  );
}
