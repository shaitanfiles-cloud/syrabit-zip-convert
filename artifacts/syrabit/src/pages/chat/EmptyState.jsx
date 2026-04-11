import { useNavigate } from 'react-router-dom';
import { BookOpen } from 'lucide-react';

export function EmptyState({ subject, documentId, defaultPrompts, setInput, textareaRef }) {
  const navigate = useNavigate();

  return (
    <div className="flex flex-col items-center justify-center text-center space-y-5 py-8">
      <div>
        <div
          className="w-16 h-16 rounded-2xl flex items-center justify-center"
          style={{
            background: 'linear-gradient(135deg,rgba(124,58,237,0.20),rgba(139,92,246,0.15))',
            border: '1px solid rgba(139,92,246,0.25)',
          }}
        >
          <BookOpen size={36} className="text-violet-400" />
        </div>
      </div>

      <div>
        <h2
          className="text-foreground mb-1.5 shimmer-text"
          style={{ fontSize: '1.2rem', fontWeight: 700 }}
        >
          {subject ? `Ask me about ${subject.name}` : <>Hi! I'm Syra — Educational Browser<br />For Assam Board Students</>}
        </h2>
        <p className="text-muted-foreground text-sm max-w-sm mx-auto">
          {documentId
            ? 'Document loaded as primary source. Ask any question.'
            : subject
            ? 'Syllabus-first answers powered by web search.'
            : ''
          }
        </p>
      </div>

      {!subject && (
        <button
          onClick={() => navigate('/library')}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold transition-all duration-200 hover:opacity-90 active:scale-95"
          style={{
            background: 'linear-gradient(135deg,rgba(124,58,237,0.15),rgba(139,92,246,0.15))',
            border: '1px solid rgba(139,92,246,0.25)',
            color: 'hsl(var(--primary))',
          }}
        >
          <BookOpen size={15} />
          Browse Syllabus →
        </button>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 w-full max-w-lg">
        {defaultPrompts.map((prompt) => (
          <button
            key={prompt}
            onClick={() => { setInput(prompt); textareaRef.current?.focus(); }}
            className="p-3 rounded-xl text-left text-sm text-muted-foreground hover:text-foreground transition-all duration-200"
            style={{ border: '1px solid rgba(139,92,246,0.12)', background: 'rgba(124,58,237,0.03)' }}
          >
            {prompt}
          </button>
        ))}
      </div>
    </div>
  );
}
