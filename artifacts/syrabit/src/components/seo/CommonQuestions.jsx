import { useState } from 'react';
import { ChevronDown, ChevronUp, HelpCircle, ArrowRight } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

function QaItem({ question, answer, index }) {
  const [open, setOpen] = useState(index === 0);

  return (
    <div className="border border-white/8 rounded-xl overflow-hidden" itemScope itemProp="mainEntity" itemType="https://schema.org/Question">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between gap-3 px-4 py-3.5 text-left hover:bg-white/3 transition-colors group"
        aria-expanded={open}
      >
        <span className="text-sm font-medium text-white group-hover:text-violet-200 transition-colors" itemProp="name">
          {question}
        </span>
        {open
          ? <ChevronUp size={15} className="text-white/30 shrink-0" />
          : <ChevronDown size={15} className="text-white/30 shrink-0" />
        }
      </button>
      {open && (
        <div
          className="border-t border-white/6 px-4 py-3.5 text-sm text-white/60 leading-relaxed whitespace-pre-wrap"
          itemScope itemProp="acceptedAnswer" itemType="https://schema.org/Answer"
        >
          <span itemProp="text">{answer}</span>
        </div>
      )}
    </div>
  );
}

export default function CommonQuestions({ qaPairs = [], board, classSlug, subjectSlug, topicSlug }) {
  const navigate = useNavigate();

  if (!qaPairs || qaPairs.length === 0) return null;

  const displayed = qaPairs.slice(0, 10);
  const hasMore   = qaPairs.length > 10;

  return (
    <section
      className="mt-10 space-y-3"
      itemScope itemType="https://schema.org/FAQPage"
      aria-label="Frequently asked questions"
    >
      {/* Section header */}
      <div className="flex items-center gap-2 mb-4">
        <HelpCircle size={17} className="text-violet-400" />
        <h2 className="text-base font-semibold text-white">Common Questions</h2>
        <span className="text-[11px] text-white/25 bg-white/5 border border-white/8 px-2 py-0.5 rounded-full">
          {qaPairs.length} answered
        </span>
      </div>

      {/* QA accordion */}
      <div className="space-y-2">
        {displayed.map((pair, i) => (
          <QaItem
            key={pair.id || i}
            question={pair.question}
            answer={pair.answer}
            index={i}
          />
        ))}
      </div>

      {/* "View more" link */}
      {hasMore && (
        <button
          onClick={() => navigate(`/${board}/${classSlug}/${subjectSlug}/${topicSlug}/qa`)}
          className="flex items-center gap-1.5 text-sm text-violet-400 hover:text-violet-300 transition-colors mt-1"
        >
          View all {qaPairs.length} questions
          <ArrowRight size={14} />
        </button>
      )}
    </section>
  );
}
