import { useState, useMemo, memo, lazy, Suspense } from 'react';
import { useNavigate } from 'react-router-dom';
import { RefreshCw, Copy, Check, FileText, Globe, BookOpen, ThumbsUp, ThumbsDown, MessageSquare, Share2, Send } from 'lucide-react';
import { useShare } from '@/hooks/useShare';
import { postChatFeedback } from '@/utils/api';
import { log } from '@/utils/logger';
import { toast } from 'sonner';
import { ThinkingIndicator } from './ThinkingIndicator';

const MarkdownContent = lazy(() => import('./MarkdownContent').then(m => ({ default: m.MarkdownContent })));

export const MessageBubble = memo(function MessageBubble({ msg, onCopy, onRegenerate, isLast, messageIndex, conversationId }) {
  const [copied, setCopied] = useState(false);
  const [reaction, setReaction] = useState(null);
  const [showComment, setShowComment] = useState(false);
  const [comment, setComment] = useState('');
  const [commentSent, setCommentSent] = useState(false);
  const { share } = useShare();
  const navigate = useNavigate();
  const isUser = msg.role === 'user';



  const sendFeedback = async (type, value) => {
    try {
      await postChatFeedback({
        conversation_id: conversationId || null,
        message_index: messageIndex ?? null,
        message_preview: (msg.content || '').slice(0, 300),
        reaction: type === 'reaction' ? value : (reaction || undefined),
        comment: type === 'comment' ? value : undefined,
      });
    } catch (e) {
      log('feedback-error', e);
    }
  };

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(msg.content || '');
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
      if (onCopy) onCopy(msg.id);
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
        if (onCopy) onCopy(msg.id);
      } catch (e) {
        log.error('Clipboard copy failed', { error: e.message });
      }
      document.body.removeChild(textArea);
    }
  };

  const timeStr = msg.timestamp
    ? new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : '';

  const { cleanContent, sourceLine } = useMemo(() => {
    if (!msg.content) return { cleanContent: msg.content, sourceLine: '' };
    let extracted = '';
    const cleaned = msg.content
      .replace(/\n*\n?Sources?:\s*((\[(PAGE|CHAPTER):[^\]]+\][,\s]*)+\.?\s*)$/gi, '')
      .replace(/\n*\n?SOURCE\s*:\s*(.+)$/i, (_, match) => { extracted = match.trim(); return ''; })
      .trim();
    return { cleanContent: cleaned, sourceLine: extracted };
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
              maxWidth: 'min(70%, calc(100vw - 5rem))',
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
                className="w-11 h-11 rounded-lg flex items-center justify-center hover:bg-primary/10 text-muted-foreground hover:text-primary transition-colors"
                title="Copy"
                aria-label={copied ? 'Copied' : 'Copy'}
              >
                {copied ? <Check size={14} style={{ color: '#34d399' }} /> : <Copy size={14} />}
              </button>
            </div>
          )}
        </>
      )}

      {!isUser && (
        <div className="w-full">
          <div className="flex items-center gap-2 mb-1">
            <div className="w-5 h-5 rounded-full overflow-hidden flex-shrink-0">
              <img src="/logo.webp" alt="Syrabit.ai" width="20" height="20" className="w-full h-full object-cover" />
            </div>
            <span className="text-xs font-semibold text-foreground/70">Syrabit AI</span>
          </div>
          <div className="w-full" style={msg.streaming ? { willChange: 'contents', contain: 'layout style' } : undefined}>
            {msg.streaming && !msg.content && !msg.translating && <ThinkingIndicator />}
            {msg.translating && !msg.content && (
              <div className="flex items-center gap-2 py-2 text-sm text-muted-foreground animate-pulse">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m5 8 6 6"/><path d="m4 14 6-6 2-3"/><path d="M2 5h12"/><path d="M7 2h1"/><path d="m22 22-5-10-5 10"/><path d="M14 18h6"/></svg>
                Translating to Assamese…
              </div>
            )}

            {msg.content && (
              <Suspense fallback={<div className="md-content-light" style={{ fontSize: '0.9375rem' }}>{cleanContent}</div>}>
                <MarkdownContent content={cleanContent} streaming={!!msg.streaming} sources={msg.sources} />
              </Suspense>
            )}

            {!msg.streaming && msg.content && (() => {
              const subjectLabel = msg.rag_subject_name || msg.ctx_subject_name || null;
              const courseLabel = msg.rag_stream_name || null;
              const boardLabel = msg.rag_board_name || null;
              const classLabel = msg.rag_class_name || null;
              const chapterLabel = msg.rag_chapter_name || null;
              const chapterSlug = msg.rag_chapter_slug || null;
              const basePath = (msg.rag_board_slug && msg.rag_class_slug && msg.rag_subject_slug)
                ? `/${msg.rag_board_slug}/${msg.rag_class_slug}/${msg.rag_subject_slug}` : null;
              const chapterUrl = (basePath && chapterSlug) ? `${basePath}/${chapterSlug}` : null;
              const subjectUrl = chapterUrl || basePath || (msg.rag_subject_id ? `/subject/${msg.rag_subject_id}` : null);
              const isDocument = msg.rag_source === 'document';
              const isLibrary = msg.rag_source === 'library';
              const isWeb = msg.rag_source === 'web';
              const hasContext = boardLabel || subjectLabel || courseLabel || (msg.rag_source && msg.rag_source !== 'none');

              const hasAnything = hasContext || sourceLine;
              if (!hasAnything) return null;

              const sourceIcon = isDocument ? FileText : isWeb ? Globe : BookOpen;
              const SourceIcon = sourceIcon;

              const lessonLabel = chapterLabel || null;

              return (
                <>
                  {(isLibrary || (!isDocument && !isWeb)) && subjectLabel && (
                    <div
                      onClick={subjectUrl ? () => {
                        if (chapterUrl) {
                          const topicText = msg.rag_topic_name || chapterLabel || '';
                          const params = new URLSearchParams();
                          params.set('topic', topicText);
                          const ragSnippet = (msg.rag_chunk_snippet || '').slice(0, 300);
                          if (ragSnippet) {
                            params.set('chunk', ragSnippet);
                          }
                          const rawContent = (msg.content || '').replace(/[#*_`>\[\]()]/g, '').replace(/\s+/g, ' ').trim();
                          const sentences = rawContent.split(/(?<=[.!?])\s+/).filter(s => s.length > 20);
                          const coreSnippet = sentences.length > 1 ? sentences.slice(1, 4).join(' ') : rawContent;
                          const responseSnippet = coreSnippet.slice(0, 300);
                          if (responseSnippet) {
                            params.set('rchunk', responseSnippet);
                          }
                          navigate(`${chapterUrl}?${params.toString()}`);
                        } else {
                          navigate(subjectUrl);
                        }
                      } : undefined}
                      className={`source-card-container mt-3 rounded-xl overflow-hidden ${subjectUrl ? 'cursor-pointer active:scale-[0.98]' : ''}`}
                      role={subjectUrl ? 'button' : undefined}
                      tabIndex={subjectUrl ? 0 : undefined}
                      onKeyDown={subjectUrl ? (e) => { if (e.key === 'Enter' || e.key === ' ') e.currentTarget.click(); } : undefined}
                      aria-label={subjectUrl ? `Open ${lessonLabel || subjectLabel} in Syrabit Browser` : undefined}
                    >
                      <div className="px-3 py-2.5">
                        <div className="flex items-center gap-1.5 mb-1">
                          <BookOpen size={11} className="source-card-icon" />
                          <span className="source-card-label text-[10px] font-semibold uppercase tracking-wider">Source</span>
                          <span className="text-[10px] text-muted-foreground/30">·</span>
                          <span className="source-card-browser text-[10.5px] font-medium">Syrabit Browser</span>
                        </div>
                        {lessonLabel && (
                          <h4 className="source-card-title font-semibold leading-tight truncate" style={{ fontSize: '0.85rem', letterSpacing: '0.01em' }}>
                            {lessonLabel}
                          </h4>
                        )}
                        <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 mt-1.5">
                          {boardLabel && (
                            <>
                              <span className="source-card-badge text-[11px] font-medium px-1.5 py-0.5 rounded">
                                {boardLabel}
                              </span>
                              <span className="text-[11px] text-muted-foreground/40">·</span>
                            </>
                          )}
                          {classLabel && (
                            <>
                              <span className="source-card-badge text-[11px] font-medium px-1.5 py-0.5 rounded">
                                {classLabel}
                              </span>
                              <span className="text-[11px] text-muted-foreground/40">·</span>
                            </>
                          )}
                          {courseLabel && (
                            <>
                              <span className="source-card-badge text-[11px] font-medium px-1.5 py-0.5 rounded">
                                {courseLabel}
                              </span>
                              <span className="text-[11px] text-muted-foreground/40">·</span>
                            </>
                          )}
                          <span className="source-card-badge text-[11px] font-medium px-1.5 py-0.5 rounded">
                            {subjectLabel}
                          </span>
                        </div>
                      </div>
                    </div>
                  )}
                  {isDocument && (
                    <div className="flex items-center gap-2.5 mt-3 px-3 py-2 rounded-xl" style={{ background: 'rgba(139,92,246,0.08)', border: '1px solid rgba(139,92,246,0.18)', maxWidth: 'fit-content' }}>
                      <div className="flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center" style={{ background: 'rgba(167,139,250,0.15)' }}>
                        <FileText size={16} style={{ color: '#a78bfa' }} />
                      </div>
                      <span className="text-[13px] font-bold text-foreground" style={{ textTransform: 'uppercase', letterSpacing: '0.03em' }}>Uploaded Document</span>
                    </div>
                  )}
                  {isWeb && (
                    <div className="flex items-center gap-2.5 mt-3 px-3 py-2 rounded-xl" style={{ background: 'rgba(56,189,248,0.08)', border: '1px solid rgba(56,189,248,0.18)', maxWidth: 'fit-content' }}>
                      <div className="flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center" style={{ background: 'rgba(56,189,248,0.15)' }}>
                        <Globe size={16} style={{ color: '#38bdf8' }} />
                      </div>
                      <span className="text-[13px] font-bold text-foreground" style={{ textTransform: 'uppercase', letterSpacing: '0.03em' }}>Web Search</span>
                    </div>
                  )}
                  <div className="flex items-center gap-1.5 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    {timeStr && (
                      <span className="text-[11px] text-muted-foreground">{timeStr}</span>
                    )}
                    <button
                      onClick={handleCopy}
                      className="w-11 h-11 rounded-lg flex items-center justify-center hover:bg-primary/10 text-muted-foreground hover:text-primary transition-colors"
                      title="Copy"
                      aria-label={copied ? 'Copied' : 'Copy'}
                    >
                      {copied ? <Check size={16} style={{ color: '#34d399' }} /> : <Copy size={16} />}
                    </button>
                    {isLast && onRegenerate && (
                      <button
                        onClick={onRegenerate}
                        className="w-11 h-11 rounded-lg flex items-center justify-center hover:bg-primary/10 text-muted-foreground hover:text-primary transition-colors"
                        title="Regenerate"
                        aria-label="Regenerate"
                      >
                        <RefreshCw size={16} />
                      </button>
                    )}
                    <button
                      onClick={() => {
                        const next = reaction === 'like' ? null : 'like';
                        setReaction(next);
                        if (next) sendFeedback('reaction', next);
                      }}
                      className={`w-11 h-11 rounded-lg flex items-center justify-center transition-colors ${reaction === 'like' ? 'bg-green-500/15 text-green-400' : 'hover:bg-primary/10 text-muted-foreground hover:text-primary'}`}
                      title="Like"
                      aria-label="Like"
                    >
                      <ThumbsUp size={15} fill={reaction === 'like' ? 'currentColor' : 'none'} />
                    </button>
                    <button
                      onClick={() => {
                        const next = reaction === 'dislike' ? null : 'dislike';
                        setReaction(next);
                        if (next) sendFeedback('reaction', next);
                      }}
                      className={`w-11 h-11 rounded-lg flex items-center justify-center transition-colors ${reaction === 'dislike' ? 'bg-red-500/15 text-red-400' : 'hover:bg-primary/10 text-muted-foreground hover:text-primary'}`}
                      title="Dislike"
                      aria-label="Dislike"
                    >
                      <ThumbsDown size={15} fill={reaction === 'dislike' ? 'currentColor' : 'none'} />
                    </button>
                    <button
                      onClick={() => setShowComment(v => !v)}
                      className={`w-11 h-11 rounded-lg flex items-center justify-center transition-colors ${showComment ? 'bg-primary/15 text-primary' : 'hover:bg-primary/10 text-muted-foreground hover:text-primary'}`}
                      title="Comment"
                      aria-label="Comment"
                    >
                      <MessageSquare size={15} />
                    </button>
                    <button
                      onClick={() => {
                        const title = (msg.content || '').slice(0, 80) + ((msg.content || '').length > 80 ? '…' : '');
                        share(title || 'Syrabit Chat', window.location.pathname);
                      }}
                      className="w-11 h-11 rounded-lg flex items-center justify-center hover:bg-primary/10 text-muted-foreground hover:text-primary transition-colors"
                      title="Share"
                      aria-label="Share"
                    >
                      <Share2 size={15} />
                    </button>
                  </div>
                  {showComment && (
                    <div className="mt-1.5 flex items-center gap-2">
                      <input
                        type="text"
                        value={comment}
                        onChange={e => setComment(e.target.value)}
                        placeholder={commentSent ? 'Feedback sent!' : 'Add feedback...'}
                        disabled={commentSent}
                        className="flex-1 text-[12px] px-3 py-1.5 rounded-lg bg-muted/50 border border-border/50 text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:border-primary/40 disabled:opacity-50"
                        onKeyDown={e => {
                          if (e.key === 'Enter' && comment.trim() && !commentSent) {
                            sendFeedback('comment', comment.trim());
                            setCommentSent(true);
                            setComment('');
                            toast.success('Feedback sent!');
                          }
                        }}
                      />
                      {!commentSent && (
                        <button
                          onClick={() => {
                            if (!comment.trim()) return;
                            sendFeedback('comment', comment.trim());
                            setCommentSent(true);
                            setComment('');
                            toast.success('Feedback sent!');
                          }}
                          disabled={!comment.trim()}
                          className="w-8 h-8 rounded-lg flex items-center justify-center bg-primary/15 text-primary hover:bg-primary/25 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                          title="Send feedback"
                        >
                          <Send size={14} />
                        </button>
                      )}
                      {commentSent && (
                        <Check size={16} style={{ color: '#34d399' }} />
                      )}
                    </div>
                  )}
                </>
              );
            })()}
          </div>
        </div>
      )}
    </div>
  );
});
