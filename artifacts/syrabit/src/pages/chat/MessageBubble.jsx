import { useState, useMemo, memo } from 'react';
import { useNavigate } from 'react-router-dom';
import { RefreshCw, Copy, Check, ExternalLink, BookOpen, FileText, Globe } from 'lucide-react';
import { log } from '@/utils/logger';
import { ThinkingIndicator } from './ThinkingIndicator';
import { MarkdownContent } from './MarkdownContent';

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
    <div
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
              const subjectLabel = msg.rag_subject_name || msg.ctx_subject_name || null;
              const courseLabel = msg.rag_stream_name || null;
              const boardLabel = msg.rag_board_name || null;
              const classLabel = msg.rag_class_name || null;
              const subjectUrl = msg.rag_subject_id ? `/subject/${msg.rag_subject_id}` : null;
              const handleCardNav = () => {
                if (!subjectUrl) return;
                navigate(subjectUrl);
              };
              const isDocument = msg.rag_source === 'document';
              const isWeb = msg.rag_source === 'web';
              const hasContext = boardLabel || subjectLabel || courseLabel || (msg.rag_source && msg.rag_source !== 'none');

              const pills = [];
              if (boardLabel) pills.push(boardLabel);
              if (classLabel) pills.push(classLabel);
              if (courseLabel) pills.push(courseLabel);

              let sourceIcon = <BookOpen size={16} style={{ color: '#4ade80' }} />;
              let sourceTitle = subjectLabel;
              let sourceBg = 'rgba(34,197,94,0.08)';
              let sourceBorder = 'rgba(34,197,94,0.18)';
              let sourceColor = '#4ade80';
              let clickable = !!subjectUrl;

              if (isDocument) {
                sourceIcon = <FileText size={16} style={{ color: '#a78bfa' }} />;
                sourceTitle = 'Uploaded Document';
                sourceBg = 'rgba(139,92,246,0.08)';
                sourceBorder = 'rgba(139,92,246,0.18)';
                sourceColor = '#a78bfa';
                clickable = false;
              } else if (isWeb) {
                sourceIcon = <Globe size={16} style={{ color: '#60a5fa' }} />;
                sourceTitle = 'Web Search';
                sourceBg = 'rgba(59,130,246,0.08)';
                sourceBorder = 'rgba(59,130,246,0.18)';
                sourceColor = '#60a5fa';
                clickable = false;
              }

              return (
                <>
                  {hasContext && sourceTitle && (
                    <div
                      onClick={clickable ? handleCardNav : undefined}
                      className={`flex items-center gap-2.5 mt-3 px-3 py-2 rounded-xl ${clickable ? 'cursor-pointer hover:opacity-85 transition-opacity' : ''}`}
                      style={{
                        background: sourceBg,
                        border: `1px solid ${sourceBorder}`,
                        maxWidth: 'fit-content',
                      }}
                      role={clickable ? 'link' : undefined}
                      aria-label={clickable ? `View ${sourceTitle}` : undefined}
                    >
                      <div className="flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center" style={{ background: `${sourceColor}18` }}>
                        {sourceIcon}
                      </div>
                      <div className="flex flex-col gap-0.5 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className="text-[13px] font-bold text-foreground truncate" style={{ textTransform: 'uppercase', letterSpacing: '0.03em' }}>
                            {sourceTitle}
                          </span>
                          {clickable && <ExternalLink size={11} style={{ color: sourceColor, flexShrink: 0 }} />}
                        </div>
                        {pills.length > 0 && (
                          <div className="flex items-center gap-1 flex-wrap">
                            {pills.map((p, i) => (
                              <span key={i} className="flex items-center gap-1">
                                {i > 0 && <span className="text-[9px]" style={{ color: 'rgba(255,255,255,0.25)' }}>·</span>}
                                <span className="text-[11px] font-medium px-1.5 py-0.5 rounded-md" style={{ background: 'rgba(255,255,255,0.06)', color: 'rgba(255,255,255,0.55)' }}>
                                  {p}
                                </span>
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
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
    </div>
  );
});
