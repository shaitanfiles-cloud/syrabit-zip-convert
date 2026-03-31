import { useState, useMemo, memo } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { BookOpen, RefreshCw, Copy, Check, ExternalLink } from 'lucide-react';
import { log } from '@/utils/logger';
import { ThinkingIndicator } from './ThinkingIndicator';
import { MarkdownContent } from './MarkdownContent';

const bubbleVariants = {
  hidden:  { opacity: 0, y: 14, scale: 0.97 },
  visible: { opacity: 1, y: 0,  scale: 1,
    transition: { duration: 0.22, ease: [0.25, 0.1, 0.25, 1] } },
};

export const MessageBubble = memo(function MessageBubble({ msg, onCopy, onRegenerate, isLast }) {
  const [copied, setCopied] = useState(false);
  const navigate = useNavigate();
  const isUser = msg.role === 'user';

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(msg.content || '');
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
      if (onCopy) onCopy();
    } catch (err) {
      // Fallback for clipboard restrictions
      const textArea = document.createElement('textarea');
      textArea.value = msg.content || '';
      textArea.style.position = 'fixed';
      textArea.style.opacity = '0';
      document.body.appendChild(textArea);
      textArea.select();
      try {
        document.execCommand('copy');
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
        if (onCopy) onCopy();
      } catch (e) {
        log.error('Clipboard copy failed', { error: e.message });
      }
      document.body.removeChild(textArea);
    }
  };

  const timeStr = msg.timestamp
    ? new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : '';

  const cleanContent = useMemo(() => {
    if (!msg.content) return msg.content;
    return msg.content
      .replace(/\n*\n?Sources?:\s*((\[(PAGE|CHAPTER):[^\]]+\][,\s]*)+\.?\s*)$/gi, '')
      .replace(/\n*\n?SOURCE\s*:\s*.+$/i, '')
      .trim();
  }, [msg.content]);

  return (
    <motion.div
      variants={bubbleVariants}
      initial="hidden"
      animate="visible"
      className={`group ${isUser ? 'flex flex-col items-end mb-2' : 'mb-3'}`}
      data-testid="chat-message-bubble"
    >
      {isUser && (
        <>
          <div
            className="whitespace-pre-wrap"
            style={{
              padding: '10px 16px',
              background: '#7c3aed',
              borderRadius: '18px 18px 4px 18px',
              fontSize: '15px',
              lineHeight: '1.6',
              color: '#fff',
              maxWidth: '70%',
              wordWrap: 'break-word',
            }}
          >
            {msg.content}
          </div>
          {!msg.streaming && (
            <div className="flex items-center gap-1 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
              {timeStr && <span className="text-[11px] text-muted-foreground">{timeStr}</span>}
              <button
                onClick={handleCopy}
                className="w-6 h-6 rounded-lg flex items-center justify-center hover:bg-primary/10 text-muted-foreground hover:text-primary transition-colors"
                title="Copy"
              >
                {copied ? <Check size={12} style={{ color: '#34d399' }} /> : <Copy size={12} />}
              </button>
            </div>
          )}
        </>
      )}

      {!isUser && (
        <div className="w-full">
          <div className="flex items-center gap-2 mb-1">
            <div className="w-5 h-5 rounded-full overflow-hidden flex-shrink-0">
              <img src="/logo.png" alt="Syrabit.ai" className="w-full h-full object-cover" />
            </div>
            <span className="text-xs font-semibold text-foreground/70">Syrabit AI</span>
          </div>
          <div className="w-full">
            {msg.streaming && !msg.content && <ThinkingIndicator />}

            {msg.streaming && msg.content && (
              <MarkdownContent content={cleanContent} streaming={true} sources={msg.sources} />
            )}

            {!msg.streaming && msg.content && (
              <MarkdownContent content={cleanContent} streaming={false} sources={msg.sources} />
            )}

            {!msg.streaming && msg.content && (() => {
              const chapterLabel = msg.rag_chapter_name || null;
              const subjectLabel = msg.rag_subject_name || msg.ctx_subject_name || null;
              const courseLabel = msg.rag_stream_name || null;
              const boardLabel = msg.rag_board_name || null;
              const subjectUrl = msg.rag_subject_id ? `/subject/${msg.rag_subject_id}` : null;
              const handlePillNav = (url) => {
                if (!url) return;
                if (url.startsWith('http')) window.open(url, '_blank', 'noopener,noreferrer');
                else navigate(url);
              };
              const isDocument = msg.rag_source === 'document';
              const isWeb = msg.rag_source === 'web';
              const hasContext = boardLabel || subjectLabel || chapterLabel || courseLabel || (msg.rag_source && msg.rag_source !== 'none');

              const crumbs = [];
              if (isDocument) {
                crumbs.push({ label: 'Uploaded Document', color: '#a78bfa', bg: 'rgba(139,92,246,0.10)' });
              } else if (isWeb) {
                crumbs.push({ label: 'Web Search', color: '#60a5fa', bg: 'rgba(59,130,246,0.08)' });
              } else {
                if (chapterLabel) crumbs.push({ label: chapterLabel, color: '#93c5fd', bg: 'rgba(96,165,250,0.08)', url: subjectUrl });
                if (subjectLabel) crumbs.push({ label: subjectLabel, color: '#7dd3fc', bg: 'rgba(59,130,246,0.07)', url: subjectUrl });
                if (courseLabel) crumbs.push({ label: courseLabel, color: '#fde68a', bg: 'rgba(234,179,8,0.07)' });
                if (boardLabel) crumbs.push({ label: boardLabel, color: '#86efac', bg: 'rgba(34,197,94,0.07)' });
              }

              return (
                <>
                  {hasContext && crumbs.length > 0 && (
                    <div className="flex items-center gap-1 mt-2 flex-wrap">
                      <span className="text-[11px] font-semibold mr-0.5" style={{ color: 'rgba(255,255,255,0.40)' }}>SOURCE</span>
                      {crumbs.map((c, i) => (
                        <span key={i} className="flex items-center gap-1">
                          {i > 0 && <span className="text-[9px]" style={{ color: 'rgba(255,255,255,0.20)' }}>·</span>}
                          {c.url ? (
                            <button
                              onClick={() => handlePillNav(c.url)}
                              className="text-[11px] font-medium px-1.5 py-0.5 rounded-md hover:opacity-80 transition-opacity cursor-pointer flex items-center gap-0.5"
                              style={{ background: c.bg, color: c.color }}
                            >
                              {c.label}
                              <ExternalLink size={9} />
                            </button>
                          ) : (
                            <span className="text-[11px] font-medium px-1.5 py-0.5 rounded-md" style={{ background: c.bg, color: c.color }}>
                              {c.label}
                            </span>
                          )}
                        </span>
                      ))}
                    </div>
                  )}
                  <div className="flex items-center gap-1.5 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    {timeStr && (
                      <span className="text-[11px] text-muted-foreground">{timeStr}</span>
                    )}
                    <button
                      onClick={handleCopy}
                      className="w-7 h-7 rounded-lg flex items-center justify-center hover:bg-primary/10 text-muted-foreground hover:text-primary transition-colors"
                      title="Copy"
                      aria-label={copied ? 'Copied' : 'Copy'}
                    >
                      {copied ? <Check size={14} style={{ color: '#34d399' }} /> : <Copy size={14} />}
                    </button>
                    {isLast && onRegenerate && (
                      <button
                        onClick={onRegenerate}
                        className="w-7 h-7 rounded-lg flex items-center justify-center hover:bg-primary/10 text-muted-foreground hover:text-primary transition-colors"
                        title="Regenerate"
                        aria-label="Regenerate"
                      >
                        <RefreshCw size={14} />
                      </button>
                    )}
                  </div>
                </>
              );
            })()}
          </div>
        </div>
      )}
    </motion.div>
  );
});
