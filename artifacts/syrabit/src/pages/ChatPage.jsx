/**
 * ChatPage — /chat
 * Full spec rebuild: 5-element animated empty state, typed bubbles,
 * actions bar (copy / regenerate / timestamp / credit badge),
 * credit progress bar, sync indicator, RAG source badge.
 */
import { useState, useEffect, useRef, useCallback, memo, useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Send, Loader2, BookOpen, Zap, RefreshCw, Copy, Check,
  AlertTriangle, Globe, Database, WifiOff, FileText, Sparkles, ChevronDown, ExternalLink, Square, Plus,
} from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import { getConversation, getSubject, getChapters, API_BASE, apiClient } from '@/utils/api';
import { AppLayout } from '@/components/layout/AppLayout';
import { toast } from 'sonner';
import { Toaster } from '@/components/ui/sonner';
import '@/styles/perplexity-chat.css';

// ── Models ────────────────────────────────────────────────────────────────────
const MODELS = [
  { value: 'openai/gpt-oss-20b',  label: 'Syrabit SLM', badge: '⚡ Fast'         },
  { value: 'openai/gpt-oss-120b', label: 'Syrabit MLM', badge: '🔜 Coming Soon', disabled: true },
];

// ── Thinking indicator — rotating messages while sarvam-m reasons ─────────────
const THINKING_STEPS = [
  'Searching in AssamBoard Syllabus…',
  'Reading relevant chapters…',
  'Cross-referencing chapter content…',
  'Verifying accuracy for board exams…',
  'Composing your answer…',
];

function ThinkingIndicator() {
  const [stepIdx, setStepIdx]   = useState(0);
  const [elapsed, setElapsed]   = useState(0);
  const [dots, setDots]         = useState('');

  useEffect(() => {
    const stepTimer  = setInterval(() => setStepIdx((i) => (i + 1) % THINKING_STEPS.length), 2200);
    const secTimer   = setInterval(() => setElapsed((s) => s + 1), 1000);
    const dotTimer   = setInterval(() => setDots((d) => (d.length >= 3 ? '' : d + '.')), 400);
    return () => { clearInterval(stepTimer); clearInterval(secTimer); clearInterval(dotTimer); };
  }, []);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: '10px 0' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        {/* animated dots */}
        <div style={{ display: 'flex', gap: 4 }}>
          {[0, 1, 2].map((i) => (
            <motion.span
              key={i}
              style={{ width: 6, height: 6, borderRadius: '50%', background: '#7c3aed', display: 'block' }}
              animate={{ y: [0, -5, 0], opacity: [0.4, 1, 0.4] }}
              transition={{ duration: 0.9, repeat: Infinity, delay: i * 0.18, ease: 'easeInOut' }}
            />
          ))}
        </div>
        <AnimatePresence mode="wait">
          <motion.span
            key={stepIdx}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.3 }}
            style={{ fontSize: 13, color: 'var(--muted-foreground)', fontStyle: 'italic' }}
          >
            {THINKING_STEPS[stepIdx]}{dots}
          </motion.span>
        </AnimatePresence>
      </div>
      {elapsed > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, paddingLeft: 2 }}>
          <div style={{ height: 2, flex: 1, maxWidth: 140, borderRadius: 4, background: 'rgba(124,58,237,0.12)', overflow: 'hidden' }}>
            <motion.div
              style={{ height: '100%', borderRadius: 4, background: 'linear-gradient(90deg,#7c3aed,#a78bfa)' }}
              animate={{ x: ['-100%', '200%'] }}
              transition={{ duration: 1.6, repeat: Infinity, ease: 'easeInOut' }}
            />
          </div>
          <span style={{ fontSize: 11, color: 'var(--muted-foreground)', opacity: 0.55 }}>
            {elapsed}s
          </span>
        </div>
      )}
    </div>
  );
}

// ── Bubble animation variants ─────────────────────────────────────────────────
const bubbleVariants = {
  hidden:  { opacity: 0, y: 14, scale: 0.97 },
  visible: { opacity: 1, y: 0,  scale: 1,
    transition: { duration: 0.22, ease: [0.25, 0.1, 0.25, 1] } },
};

// ── Unified source card — watermark + all page links + footer stats ───────────
function SourcesCard({ sources, ragSource, ragChunks, ragSubjectId, ragSubjectName }) {
  const navigate = useNavigate();

  const hasSrc = sources && sources.length > 0;
  const hasRag = ragSource && ragSource !== 'none';

  if (!hasSrc && !hasRag) return null;

  const boardLabel = (() => {
    if (ragSource === 'document')                       return 'Document';
    if (ragSource === 'rag' || ragSource === 'rag+web') return 'AssamBoard Curriculum';
    if (ragSource === 'web')                            return 'Web Search';
    return 'Syrabit Library';
  })();

  const handleNav = (url) => {
    if (!url) return;
    if (url.startsWith('http')) window.open(url, '_blank', 'noopener,noreferrer');
    else navigate(url);
  };

  const visibleSources = hasSrc ? sources.filter(s => s.url || s.slug) : [];
  const subjectUrl     = ragSubjectId ? `/subject/${ragSubjectId}` : null;
  const fallbackUrl    = subjectUrl || '/library';
  const displayTitle   = ragSubjectName || 'Syrabit Library';

  const footerText = [
    ragChunks > 0 ? `${ragChunks} chunks` : null,
    (ragSource === 'rag' || ragSource === 'rag+web') ? 'AssamBoard Curriculum' : null,
    ragSource === 'web' ? 'Web search' : null,
    ragSource === 'document' ? 'Uploaded document' : null,
  ].filter(Boolean).join(' · ');

  // No individual page sources — make entire card a single clickable link
  if (visibleSources.length === 0) {
    return (
      <button
        onClick={() => handleNav(fallbackUrl)}
        className="source-card source-card-clickable w-full text-left"
        title={`View ${displayTitle}`}
      >
        <div className="source-watermark">
          <BookOpen size={13} className="shrink-0" style={{ color: '#60a5fa' }} />
          <span>Syrabit.ai · {boardLabel}</span>
          {ragChunks > 0 && <span className="source-chunk-badge">{ragChunks} blocks</span>}
          <ExternalLink size={10} className="ml-auto shrink-0 opacity-40" style={{ color: '#60a5fa' }} />
        </div>
        <div className="source-pages">
          <div className="source-link" style={{ pointerEvents: 'none' }}>
            <span className="source-link-icon">📖</span>
            <span className="truncate">{displayTitle}</span>
          </div>
        </div>
        {footerText && <div className="source-stats">{footerText}</div>}
      </button>
    );
  }

  // Individual source pages — watermark header links to subject, each page is its own link
  return (
    <div className="source-card">
      {/* Watermark header — always links to subject */}
      <button
        onClick={() => handleNav(fallbackUrl)}
        className="source-watermark source-watermark-btn w-full text-left"
        title={`View ${displayTitle}`}
      >
        <BookOpen size={13} className="shrink-0" style={{ color: '#60a5fa' }} />
        <span>Syrabit.ai · {boardLabel}</span>
        {ragChunks > 0 && <span className="source-chunk-badge">{ragChunks} blocks</span>}
        <ExternalLink size={10} className="ml-auto shrink-0 opacity-40" style={{ color: '#60a5fa' }} />
      </button>

      {/* Subject label */}
      {displayTitle && (
        <div className="flex items-center gap-1.5 mb-2 px-1 mt-1">
          <span className="text-[10px] font-semibold text-white/25 uppercase tracking-widest">From</span>
          <span
            className="text-[11px] font-semibold px-2 py-0.5 rounded-md"
            style={{ background: 'rgba(139,92,246,0.10)', color: '#a78bfa' }}
          >
            {displayTitle}
          </span>
        </div>
      )}

      {/* Individual page links */}
      <div className="source-pages">
        {visibleSources.map((src, i) => (
          <button
            key={i}
            onClick={() => handleNav(src.url || '')}
            className="source-link"
            title={src.url || src.title}
            disabled={!src.url}
          >
            <span className="source-link-icon">📖</span>
            <span className="truncate">{src.title || src.slug}</span>
            {src.url && <ExternalLink size={9} className="shrink-0 ml-auto opacity-40" />}
          </button>
        ))}
      </div>

      {footerText && <div className="source-stats">{footerText}</div>}
    </div>
  );
}

// ── Markdown renderer for AI answers ─────────────────────────────────────────
// Stable link renderer — no hooks, defined once at module level
const MD_LINK_COMPONENTS = {
  a: ({ href, children }) => {
    if (!href) return <span>{children}</span>;
    if (href.startsWith('http')) {
      return <a href={href} target="_blank" rel="noopener noreferrer" className="inline-source-link">{children}</a>;
    }
    return (
      <button onClick={() => { window.location.href = href; }} className="inline-source-link">
        {children}
      </button>
    );
  },
};

function MarkdownContent({ content, streaming, sources }) {
  // Build lookup: title/slug → url from RAG sources so [PAGE: X] becomes a link
  const processed = useMemo(() => {
    if (!content) return content;
    // Build map: lowercased title → url, lowercased slug → url
    const urlMap = new Map();
    for (const s of (sources || [])) {
      const url = s.url || '';
      if (s.title) urlMap.set(s.title.trim().toLowerCase(), url);
      if (s.slug)  urlMap.set(s.slug.trim().toLowerCase(),  url || `/learn/${s.slug}`);
    }
    // Replace [PAGE: Title] with [Title](url) markdown links
    return content.replace(/\[PAGE:\s*([^\]]+)\]/g, (_, rawTitle) => {
      const title  = rawTitle.trim();
      const key    = title.toLowerCase();
      // Try exact title match, then slug-style key
      const slugKey = key.replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '');
      const url = urlMap.get(key) || urlMap.get(slugKey) || '';
      return url ? `[${title}](${url})` : `**${title}**`;
    });
  }, [content, sources]);

  return (
    <div className="md-content-light" style={{ fontSize: '0.9375rem' }}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_LINK_COMPONENTS}>
        {processed}
      </ReactMarkdown>
      {streaming && (
        <motion.span
          className="inline-block rounded-full align-middle"
          style={{ width: 2, height: '1em', marginLeft: 2, background: 'hsl(var(--primary))' }}
          animate={{ opacity: [1, 0, 1] }}
          transition={{ duration: 0.65, repeat: Infinity }}
        />
      )}
    </div>
  );
}

// ── Message bubble ────────────────────────────────────────────────────────────
const MessageBubble = memo(function MessageBubble({ msg, onCopy, onRegenerate, isLast }) {
  const [copied, setCopied] = useState(false);
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
        console.error('Copy failed:', e);
      }
      document.body.removeChild(textArea);
    }
  };

  const timeStr = msg.timestamp
    ? new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : '';

  // Strip trailing "Sources: [PAGE/CHAPTER: ...] ..." line the AI appends — shown separately below
  const cleanContent = useMemo(() => {
    if (!msg.content) return msg.content;
    return msg.content
      .replace(/\n*\n?Sources?:\s*((\[(PAGE|CHAPTER):[^\]]+\][,\s]*)+\.?\s*)$/gi, '')
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
              const hasSrc = msg.rag_source && msg.rag_source !== 'none';
              const firstSrc = msg.sources && msg.sources[0];
              const pillName = msg.rag_subject_name
                || firstSrc?.title
                || (msg.rag_source === 'document' ? 'Document' : null)
                || (msg.rag_source === 'web' ? 'Web Search' : null)
                || (hasSrc ? 'AssamBoard Curriculum' : null);
              const pillUrl = msg.rag_subject_id
                ? `/subject/${msg.rag_subject_id}`
                : firstSrc?.url
                || '/library';
              const handlePillNav = (url) => {
                if (!url) return;
                if (url.startsWith('http')) window.open(url, '_blank', 'noopener,noreferrer');
                else navigate(url);
              };
              return (
                <div className="flex items-center gap-1.5 mt-1.5">
                  {pillName && (
                    <button
                      onClick={() => handlePillNav(pillUrl)}
                      className="source-mini-pill"
                      title={`View ${pillName}`}
                    >
                      <BookOpen size={10} className="shrink-0" />
                      <span className="truncate">{pillName}</span>
                      <ExternalLink size={8} className="shrink-0 opacity-50" />
                    </button>
                  )}
                  <div className="flex items-center gap-1.5 ml-auto opacity-0 group-hover:opacity-100 transition-opacity">
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
                </div>
              );
            })()}
          </div>
        </div>
      )}
    </motion.div>
  );
});

// ── ChatPage ──────────────────────────────────────────────────────────────────
export default function ChatPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const convId     = searchParams.get('id');
  const subjectId  = searchParams.get('subject');
  const documentId = searchParams.get('document_id'); // Tier 0 RAG when present

  // ── State ──────────────────────────────────────────────────────────────────
  const [messages, setMessages]           = useState([]);
  const [input, setInput]                 = useState('');
  const [isLoading, setIsLoading]         = useState(false);
  const [conversationId, setConversationId] = useState(convId || null);
  const [model, setModel]                 = useState('openai/gpt-oss-20b');
  const [subject, setSubject]             = useState(null);
  const [scopedChapters, setScopedChapters] = useState([]);
  const [credits, setCredits]             = useState({ used: user?.credits_used || 0, limit: user?.credits_limit ?? null });
  const [syncState, setSyncState]         = useState('idle');
  const [showModelMenu, setShowModelMenu] = useState(false);
  const [copiedMsgId, setCopiedMsgId]     = useState(null);

  // ── Refs (3 useRef) ────────────────────────────────────────────────────────
  const messagesEndRef    = useRef(null);
  const textareaRef       = useRef(null);
  const abortControllerRef = useRef(null);
  const modelMenuRef      = useRef(null);

  // ── Auto-scroll (smooth yet responsive) ──────────────────────────────────
  const scrollTimeoutRef = useRef(null);
  useEffect(() => {
    if (scrollTimeoutRef.current) clearTimeout(scrollTimeoutRef.current);
    scrollTimeoutRef.current = setTimeout(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }, 0);
    return () => { if (scrollTimeoutRef.current) clearTimeout(scrollTimeoutRef.current); };
  }, [messages]);

  // ── Fetch fresh credits on mount / user change ─────────────────────────────
  useEffect(() => {
    if (!user) return;
    apiClient().get('/user/profile')
      .then((res) => {
        const p = res.data;
        setCredits({
          used:  p.credits_used  ?? 0,
          limit: p.credits_limit ?? null,
        });
      })
      .catch(() => {});
  }, [user]);

  // ── Load subject context ───────────────────────────────────────────────────
  useEffect(() => {
    if (!subjectId) return;
    setSyncState('syncing');
    getSubject(subjectId)
      .then((r) => {
        setSubject(r.data);
        return getChapters(subjectId);
      })
      .then((r) => {
        setScopedChapters(r.data || []);
        setSyncState('idle');
      })
      .catch(() => setSyncState('idle'));
  }, [subjectId]);

  // ── Load conversation from URL ─────────────────────────────────────────────
  useEffect(() => {
    if (!convId || !user) return;
    setSyncState('syncing');
    getConversation(convId)
      .then((r) => {
        const conv = r.data;
        setConversationId(conv.id);
        setMessages(conv.messages || []);
        setSyncState('idle');
      })
      .catch(() => setSyncState('offline'));
  }, [convId, user]);

  // ── Sync state probe on focus ──────────────────────────────────────────────
  useEffect(() => {
    const check = () => {
      if (document.visibilityState === 'visible') {
        fetch(`${API_BASE}/health`).then(() => setSyncState('idle')).catch(() => setSyncState('offline'));
      }
    };
    document.addEventListener('visibilitychange', check);
    return () => document.removeEventListener('visibilitychange', check);
  }, []);

  // ── Close model dropdown on outside click ─────────────────────────────────
  useEffect(() => {
    if (!showModelMenu) return;
    const handler = (e) => {
      if (modelMenuRef.current && !modelMenuRef.current.contains(e.target)) {
        setShowModelMenu(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [showModelMenu]);

  // ── Auto-grow textarea ────────────────────────────────────────────────────
  const adjustTextarea = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, []);

  useEffect(() => { adjustTextarea(); }, [input, adjustTextarea]);

  // ── Build card context (scraped from library card) ────────────────────────
  // Mirrors the PDF chat Tier 0 — sent as grounding context with every message
  const cardContext = useMemo(() => {
    if (!subjectId || !subject) return null;
    const lines = [];
    lines.push(`Subject: ${subject.name}`);
    if (subject.description) lines.push(`Description: ${subject.description}`);
    if (Array.isArray(subject.tags) && subject.tags.length)
      lines.push(`Topics covered: ${subject.tags.join(', ')}`);
    const rawBoard = (user?.board_name || '').toUpperCase();
    const CANONICAL_DIVISIONS = new Set(['AHSEC', 'DEGREE', 'SEBA']);
    const boardLabel = rawBoard
      ? `AssamBoard — ${CANONICAL_DIVISIONS.has(rawBoard) ? rawBoard : 'AHSEC'}`
      : null;
    const parts = [boardLabel, user?.class_name, user?.stream_name].filter(Boolean);
    if (parts.length) lines.push(`Board/Class: ${parts.join(' | ')}`);
    if (scopedChapters.length) {
      lines.push('');
      lines.push('Syllabus chapters:');
      scopedChapters
        .slice()
        .sort((a, b) => (a.order_index ?? a.order ?? 0) - (b.order_index ?? b.order ?? 0))
        .forEach((ch, i) => {
          const num = ch.chapter_number ?? ch.order_index ?? i + 1;
          let entry = `Chapter ${num} — ${ch.title}`;
          if (ch.description) entry += `: ${ch.description}`;
          if (ch.content) entry += `\n${ch.content.slice(0, 200)}`;
          lines.push(entry);
        });
    }
    return lines.join('\n').slice(0, 2500);
  }, [subjectId, subject, scopedChapters, user]);

  // ── Derived state ─────────────────────────────────────────────────────────
  // credits.limit is null until the auth context populates it (new users have 30, not 0)
  const effectiveLimit = credits.limit ?? user?.credits_limit ?? null;
  const remaining    = effectiveLimit !== null ? Math.max(0, effectiveLimit - credits.used) : null;
  // NaN guard: only show progress bar once limit is known
  const creditPercent = effectiveLimit != null && effectiveLimit > 0 ? Math.min(100, (credits.used / effectiveLimit) * 100) : 0;
  // Only block if we know the limit AND credits are exhausted; never block while limit is unknown
  const isOutOfCredits = effectiveLimit !== null && effectiveLimit !== undefined && remaining !== null && remaining <= 0;
  const isLow = effectiveLimit !== null && effectiveLimit > 0 && remaining !== null && remaining > 0 && remaining <= 5;

  // ── Sync indicator ────────────────────────────────────────────────────────
  const SyncDot = () => {
    if (syncState === 'syncing') return <Loader2 size={12} className="animate-spin text-muted-foreground" />;
    if (syncState === 'offline') return <WifiOff size={12} className="text-amber-400" />;
    return <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />;
  };

  // ── New Chat — reset state ────────────────────────────────────────────────
  const handleNewChat = useCallback(() => {
    setMessages([]);
    setConversationId(null);
    setInput('');
    navigate('/chat', { replace: true });
  }, [navigate]);

  // ── Stop streaming ─────────────────────────────────────────────────────────
  const handleStop = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    setIsLoading(false);
    // Mark last AI message as non-streaming to keep partial text
    setMessages((prev) =>
      prev.map((m, i) =>
        i === prev.length - 1 && m.role === 'assistant'
          ? { ...m, streaming: false }
          : m
      )
    );
  }, []);

  // ── Send message ──────────────────────────────────────────────────────────
  const sendMsg = async (text) => {
    if (!text.trim() || isLoading || isOutOfCredits) return;

    const msgId = Date.now().toString();
    const userMsg = { id: msgId + '_u', role: 'user', content: text, timestamp: new Date().toISOString() };
    const aiMsgId = msgId + '_a';
    const aiMsg   = { id: aiMsgId, role: 'assistant', content: '', streaming: true, timestamp: new Date().toISOString() };

    setMessages((prev) => [...prev, userMsg, aiMsg]);
    setInput('');
    setIsLoading(true);
    setSyncState('syncing');

    // Abort previous stream if any
    if (abortControllerRef.current) abortControllerRef.current.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;

    const payload = {
      message: text,
      conversation_id: conversationId,
      subject_id:      subjectId    || null,
      subject_name:    subject?.name || null,
      board_id:        user?.board_id   || null,
      board_name:      user?.board_name || null,
      class_id:        user?.class_id   || null,
      class_name:      user?.class_name || null,
      stream_name:     user?.stream_name || null,
      model,
      // Tier 0 RAG: card_context (library card scrape) takes priority over document_id
      card_context: cardContext || null,
      document_id:  documentId || null,
    };

    try {
      const response = await fetch(`${API_BASE}/ai/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(payload),
        signal: controller.signal,
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        if (response.status === 402) {
          toast.error('Credits exhausted — upgrade to continue.', {
            action: { label: 'Upgrade', onClick: () => navigate('/profile') },
          });
          setMessages((prev) => prev.filter((m) => m.id !== aiMsgId));
          return;
        }
        throw new Error(errData.detail || 'Stream failed');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let fullContent = '';
      let newConvId = conversationId;
      let ragSource = 'none';
      let ragChunks = 0;
      let ragSubjectId = null;
      let ragSubjectName = null;
      let libSources = [];
      let hasError = false;

      // RAF-based batching: accumulate chunks between animation frames
      // so React re-renders at most 60×/sec instead of on every token
      let pendingChunk = '';
      let rafId = null;
      const flushPending = () => {
        if (!pendingChunk) return;
        fullContent += pendingChunk;
        pendingChunk = '';
        rafId = null;
        const snapshot = fullContent;
        setMessages((prev) => prev.map((m) =>
          m.id === aiMsgId ? { ...m, content: snapshot } : m
        ));
      };

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        const text = decoder.decode(value, { stream: true });
        for (const line of text.split('\n')) {
          if (!line.startsWith('data: ')) continue;
          const raw = line.slice(6);
          if (raw === '[DONE]') break;
          try {
            const parsed = JSON.parse(raw);
            if (parsed.conversation_id) newConvId = parsed.conversation_id;
            if (parsed.rag_source) ragSource = parsed.rag_source;
            if (parsed.rag_chunks !== undefined) ragChunks = parsed.rag_chunks;
            if (parsed.rag_subject_id) ragSubjectId = parsed.rag_subject_id;
            if (parsed.rag_subject_name) ragSubjectName = parsed.rag_subject_name;
            if (parsed.error) {
              hasError = true;
              toast.error(parsed.error || 'AI service error — please try again.');
              setMessages((prev) => prev.map((m) =>
                m.id === aiMsgId
                  ? { ...m, content: 'Sorry, something went wrong. Please try again.', streaming: false }
                  : m
              ));
              continue;
            }
            if (hasError) continue;
            if (parsed.content) {
              pendingChunk += parsed.content;
              if (!fullContent && !rafId) {
                // First token: flush immediately so TTFT is instant
                flushPending();
              } else if (!rafId) {
                rafId = requestAnimationFrame(flushPending);
              }
            }
            // ── syrabit_done: credits metadata + library sources ───────
            if (parsed.event === 'syrabit_done') {
              if (parsed.sources) libSources = parsed.sources;
              setCredits((c) => ({
                ...c,
                used: parsed.credits_used_total || c.used + 1,
              }));
              const remaining = parsed.remaining_credits ?? 0;
              try {
                const { Analytics } = await import('@/utils/analytics');
                Analytics.chatMessage(ragSource, remaining, model);
                if (remaining <= 0) Analytics.chatCreditsExhausted();
              } catch {}
            }
          } catch {}
        }
      }

      // Flush any remaining buffered content before finalizing
      if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
      if (pendingChunk) { fullContent += pendingChunk; pendingChunk = ''; }

      // Update URL with conversation ID after first message
      if (newConvId && newConvId !== conversationId) {
        setConversationId(newConvId);
        setSearchParams((prev) => {
          const next = new URLSearchParams(prev);
          next.set('id', newConvId);
          return next;
        }, { replace: true });
      } else {
        setConversationId(newConvId);
      }

      // Finalize: remove streaming flag, attach RAG metadata + library sources
      // Note: credits are already updated by syrabit_done event; do not double-increment here
      setMessages((prev) => prev.map((m) =>
        m.id === aiMsgId
          ? { ...m, content: fullContent, streaming: false, rag_source: ragSource, rag_chunks: ragChunks, rag_subject_id: ragSubjectId, rag_subject_name: ragSubjectName, sources: libSources }
          : m
      ));
      setSyncState('idle');

    } catch (err) {
      if (err.name === 'AbortError') return;
      toast.error(err.message || 'Failed to get AI response');
      setMessages((prev) => prev.filter((m) => m.id !== aiMsgId));
      setSyncState('offline');
    } finally {
      setIsLoading(false);
    }
  };

  // ── Regenerate last AI message ─────────────────────────────────────────────
  const handleRegenerate = useCallback(() => {
    const lastUser = [...messages].reverse().find((m) => m.role === 'user');
    if (lastUser) {
      setMessages((prev) => prev.slice(0, -1)); // remove last AI msg
      sendMsg(lastUser.content);
    }
  }, [messages]); // eslint-disable-line

  // ── Default prompts based on subject ──────────────────────────────────────
  const defaultPrompts = subject
    ? [
        `Explain the key concepts of ${subject.name}`,
        `What are the most important topics in ${subject.name} for exams?`,
        `Give me a solved example from ${subject.name}`,
        `What are common mistakes students make in ${subject.name}?`,
      ]
    : [
        'Explain this concept step by step',
        'Give me an exam-ready answer',
        'Show me a solved example',
        'What are the key points to remember?',
      ];

  const modelLabel = MODELS.find((m) => m.value === model) || MODELS[0];

  return (
    <AppLayout pageTitle={
      <div className="relative flex items-center gap-2" ref={modelMenuRef}>
        <button
          onClick={() => setShowModelMenu((v) => !v)}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-semibold text-foreground hover:text-primary transition-all border border-border/50 hover:border-primary/30 hover:shadow-[0_0_12px_rgba(139,92,246,0.1)]"
          data-testid="model-selector-button"
        >
          <img src="/logo.png" alt="" className="w-4 h-4 rounded-sm" />
          <span>{modelLabel.label}</span>
          {!modelLabel.disabled && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-primary/10 text-primary font-medium">
              {modelLabel.badge.replace(/[🧠⚡🔜]\s*/, '')}
            </span>
          )}
          <ChevronDown size={14} className={`text-muted-foreground transition-transform ${showModelMenu ? 'rotate-180' : ''}`} />
        </button>
        {showModelMenu && (
          <div
            className="absolute top-full left-0 mt-2 z-50 rounded-xl border border-border/60 shadow-2xl min-w-[260px] overflow-hidden backdrop-blur-xl"
            style={{ background: 'var(--popover-glass, var(--popover))' }}
          >
            {MODELS.map((m) => (
              <button
                key={m.value}
                onClick={() => { 
                  if (!m.disabled) {
                    setModel(m.value); 
                    setShowModelMenu(false);
                  }
                }}
                disabled={m.disabled}
                className={`w-full flex items-center gap-3 px-4 py-3 text-sm transition-colors ${
                  m.disabled 
                    ? 'opacity-50 cursor-not-allowed bg-muted/20' 
                    : 'hover:bg-accent/40'
                } ${
                  model === m.value ? 'text-primary font-semibold bg-primary/5' : 'text-foreground'
                }`}
              >
                <img src="/logo.png" alt="" className="w-5 h-5 rounded-sm flex-shrink-0" />
                <div className="flex flex-col items-start flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="truncate">{m.label}</span>
                    {m.disabled && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-500/10 text-amber-500 font-medium">
                        Coming Soon
                      </span>
                    )}
                  </div>
                  <span className="text-[10px] text-muted-foreground">
                    {m.disabled 
                      ? 'Advanced model launching soon' 
                      : (m.badge.replace(/[🧠⚡🔜]\s*/, '') === 'Fast' ? 'Best for quick Q&A, fastest responses' : 'Best for complex problems, deep reasoning')
                    }
                  </span>
                </div>
                {model === m.value && !m.disabled && <span className="w-1.5 h-1.5 rounded-full bg-primary flex-shrink-0" />}
              </button>
            ))}
          </div>
        )}

        {/* New Chat button in header */}
        <button
          onClick={handleNewChat}
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium text-muted-foreground hover:text-foreground border border-border/40 hover:border-primary/30 transition-all"
          title="New chat"
          aria-label="Start new chat"
        >
          <Plus size={13} />
          <span className="hidden sm:inline">New Chat</span>
        </button>
      </div>
    }>
      <Toaster richColors position="top-right" />

      <div className="flex flex-col chat-viewport-height">

        {/* ── Out-of-credits / upgrade banner ────────────────────────────── */}
        {isOutOfCredits && (
          <div
            className="flex items-center justify-between px-4 py-2.5 text-sm flex-shrink-0"
            style={{ background: 'rgba(239,68,68,0.08)', borderBottom: '1px solid rgba(239,68,68,0.15)' }}
            role="alert"
          >
            <div className="flex items-center gap-2 text-red-400">
              <AlertTriangle size={14} aria-hidden="true" />
              <span>
                {credits.limit === 0
                  ? 'Free plan has no credits — upgrade to start chatting'
                  : 'Credits exhausted — upgrade to continue'}
              </span>
            </div>
            <button
              onClick={() => navigate('/profile')}
              className="text-xs font-semibold text-red-300 hover:text-red-200 transition-colors underline"
              aria-label="Go to profile to upgrade plan"
            >
              Upgrade →
            </button>
          </div>
        )}

        {/* ── Message area ── */}
        <div
          className="flex-1 overflow-y-auto min-h-0"
          onClick={() => setShowModelMenu(false)}
          role="log"
          aria-label="Chat messages"
          aria-live="polite"
        >
          <div className="max-w-3xl mx-auto px-4 md:px-6 py-4">

            {/* Empty state */}
            {messages.length === 0 && (
              <div className="flex flex-col items-center justify-center text-center space-y-5 py-8">
                <motion.div
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ duration: 0.35 }}
                >
                  <div
                    className="w-16 h-16 rounded-2xl flex items-center justify-center"
                    style={{
                      background: 'linear-gradient(135deg,rgba(124,58,237,0.20),rgba(139,92,246,0.15))',
                      border: '1px solid rgba(139,92,246,0.25)',
                    }}
                  >
                    <BookOpen size={36} className="text-violet-400" />
                  </div>
                </motion.div>

                <motion.div
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.35, delay: 0.08 }}
                >
                  <h2
                    className="text-foreground mb-1.5 shimmer-text"
                    style={{ fontSize: '1.2rem', fontWeight: 700 }}
                  >
                    {subject ? `Ask me about ${subject.name}` : "Hi! I'm Syra — your educational browser"}
                  </h2>
                  <p className="text-muted-foreground text-sm max-w-sm mx-auto">
                    {documentId
                      ? 'Document loaded as primary source. Ask any question.'
                      : subject
                      ? `${scopedChapters.length} chapters loaded — syllabus-first answers.`
                      : 'Ask anything — syllabus database first, web if needed.'
                    }
                  </p>
                </motion.div>

                {!subject && (
                  <motion.button
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.3, delay: 0.14 }}
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
                  </motion.button>
                )}

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 w-full max-w-lg">
                  {defaultPrompts.map((prompt, i) => (
                    <motion.button
                      key={prompt}
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.28, delay: 0.18 + i * 0.06 }}
                      onClick={() => { setInput(prompt); textareaRef.current?.focus(); }}
                      className="p-3 rounded-xl text-left text-sm text-muted-foreground hover:text-foreground transition-all duration-200"
                      style={{ border: '1px solid rgba(139,92,246,0.12)', background: 'rgba(124,58,237,0.03)' }}
                    >
                      {prompt}
                    </motion.button>
                  ))}
                </div>
              </div>
            )}

            {/* Messages */}
            <AnimatePresence initial={false}>
              {messages.map((msg, i) => (
                <MessageBubble
                  key={msg.id || i}
                  msg={msg}
                  isLast={i === messages.length - 1}
                  onCopy={() => setCopiedMsgId(msg.id)}
                  onRegenerate={msg.role === 'assistant' && i === messages.length - 1 ? handleRegenerate : null}
                />
              ))}
            </AnimatePresence>
            <div ref={messagesEndRef} />
          </div>
        </div>

        {/* ── Input area — fixed at bottom ─────────────────────────────── */}
        <div
          className="sticky bottom-0 z-20 flex-shrink-0 border-t border-border/50 px-4 md:px-6 py-3"
          style={{ background: 'var(--card)', backdropFilter: 'blur(12px)', WebkitBackdropFilter: 'blur(12px)' }}
          data-testid="chat-input"
        >
          <div className="max-w-3xl mx-auto">
            {subject && messages.length === 0 && scopedChapters.length > 0 && (
              <div className="flex items-center gap-2 mb-2 px-1 text-xs text-muted-foreground">
                <Database size={12} style={{ color: 'hsl(var(--primary) / 0.6)' }} />
                <span>RAG: {scopedChapters.length} chapters from {subject.name}</span>
              </div>
            )}

            <div
              className="flex items-end gap-3 p-3 rounded-2xl border transition-all duration-200"
              style={
                isOutOfCredits
                  ? { borderColor: 'rgba(239,68,68,0.20)', opacity: 0.6, background: 'rgba(239,68,68,0.02)' }
                  : { borderColor: 'rgba(139,92,246,0.15)', background: 'rgba(124,58,237,0.03)' }
              }
            >
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => { setInput(e.target.value); adjustTextarea(); }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendMsg(input);
                  }
                }}
                placeholder={
                  isOutOfCredits
                    ? 'No credits remaining — upgrade to continue'
                    : subject
                    ? `Ask about ${subject.name}…`
                    : 'Ask anything...'
                }
                disabled={isOutOfCredits}
                rows={1}
                className="flex-1 bg-transparent resize-none outline-none text-sm text-foreground placeholder:text-muted-foreground disabled:cursor-not-allowed"
                style={{ minHeight: 24, maxHeight: 160 }}
                aria-label="Type your message"
              />
              <div className="flex items-center gap-2 flex-shrink-0">
                <span className="text-xs text-muted-foreground hidden sm:inline">↵ Enter</span>
                {isLoading ? (
                  <button
                    onClick={handleStop}
                    className="w-9 h-9 rounded-xl flex items-center justify-center transition-all"
                    style={{
                      background: 'rgba(239,68,68,0.15)',
                      border: '1px solid rgba(239,68,68,0.30)',
                      color: '#f87171',
                    }}
                    aria-label="Stop generating"
                    title="Stop"
                    data-testid="chat-stop-button"
                  >
                    <Square size={14} aria-hidden="true" />
                  </button>
                ) : (
                  <button
                    onClick={() => sendMsg(input)}
                    disabled={!input.trim() || isOutOfCredits}
                    className="w-9 h-9 rounded-xl flex items-center justify-center transition-all disabled:cursor-not-allowed"
                    style={
                      input.trim() && !isOutOfCredits
                        ? {
                            background: 'linear-gradient(135deg,#7c3aed,#8b5cf6)',
                            color: '#fff',
                            boxShadow: '0 4px 15px rgba(139,92,246,0.4)',
                          }
                        : { background: 'hsl(var(--muted))', color: 'hsl(var(--muted-foreground))' }
                    }
                    data-testid="chat-send-button"
                    aria-label="Send message"
                  >
                    <Send size={16} aria-hidden="true" />
                  </button>
                )}
              </div>
            </div>

            {/* ── Credit progress bar ────────────────────────────────────── */}
            {effectiveLimit !== null && effectiveLimit > 0 && (
              <div className="mt-2 px-1 flex items-center gap-2">
                <div
                  className="flex-1 h-1 rounded-full overflow-hidden"
                  style={{ background: 'rgba(139,92,246,0.10)' }}
                  role="progressbar"
                  aria-valuenow={creditPercent}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label="Credit usage"
                >
                  <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{
                      width: `${creditPercent}%`,
                      background: isLow || isOutOfCredits
                        ? 'linear-gradient(90deg,#ef4444,#f87171)'
                        : 'linear-gradient(90deg,#7c3aed,#a78bfa)',
                    }}
                  />
                </div>
                <span
                  className="text-[10px] font-medium shrink-0"
                  style={{ color: isLow || isOutOfCredits ? '#f87171' : 'hsl(var(--muted-foreground))' }}
                >
                  {remaining !== null ? `${remaining} left` : ''}
                </span>
              </div>
            )}
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
