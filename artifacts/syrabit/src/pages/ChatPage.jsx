/**
 * ChatPage — /chat
 * Full spec rebuild: 5-element animated empty state, typed bubbles,
 * actions bar (copy / regenerate / timestamp / credit badge),
 * credit progress bar, sync indicator, source badge.
 */
import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { AlertTriangle } from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import { useContentLang } from '@/context/LanguageContext';
import { getConversation, getAnonConversation, getSubject, getChapters, API_BASE, apiClient, getAnonId } from '@/utils/api';
import { AppLayout } from '@/components/layout/AppLayout';
import { toast } from 'sonner';

import { MessageBubble } from './chat/MessageBubble';
import { InputBar } from './chat/InputBar';
import { ModelSelector, MODELS } from './chat/ModelSelector';
import { useTurnstile } from '@/hooks/useTurnstile';
import { Analytics } from '@/utils/analytics';
// React 19 hoists <title>/<meta>/<link> to <head> from anywhere in the
// tree without the SSR/client mismatch react-helmet-async causes. Use
// native tags directly. (Removes React error #418 on prerendered /chat.)

// EmptyState is imported eagerly so its h2 ("Hi! I'm Syra…") — the LCP
// element on /chat — renders in the SSR snapshot and on the very first
// client paint, instead of waiting for an async chunk. (Task #387)
import { EmptyState } from './chat/EmptyState';

// ─────────────────────────────────────────────────────────────────────────────
// AD POLICY: /chat is intentionally AD-FREE. Do NOT import <AdSlot /> or any
// ad-network script here. The ad stack (Task #526) only runs on PYQ and Learn
// pages. Chat must stay distraction-free for the AI tutor experience.
// ─────────────────────────────────────────────────────────────────────────────

// ── ChatPage ──────────────────────────────────────────────────────────────────
export default function ChatPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const convId     = searchParams.get('id');
  const subjectId  = searchParams.get('subject');
  const documentId = searchParams.get('document_id');

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
  // IMPORTANT: initialize to a deterministic constant ('en') and rehydrate
  // from localStorage in useEffect. Reading localStorage during render makes
  // the SSR snapshot (always 'en') drift from the client first render
  // (potentially 'as'), breaking hydration on the language toggle.
  // (Task #387 — architect review.)
  const [responseLang, setResponseLang] = useState('en');
  useEffect(() => {
    try {
      const stored = localStorage.getItem('syrabit_response_lang');
      if (stored && stored !== 'en') setResponseLang(stored);
    } catch {}
  }, []);
  // Skip Turnstile entirely for authenticated users — backend never verifies a
  // captcha for them, so loading the CF script + invisible widget is pure
  // overhead. (Task #282 T001)
  // Wait until the auth check has resolved before deciding whether to load
  // the Cloudflare script. Otherwise a logged-in user briefly sees `user=null`
  // during initial /me hydration and we'd inject the script anyway, defeating
  // the optimization. (Task #282 T001)
  const { authChecked } = useAuth();
  const skipTurnstile = !authChecked || !!user;
  const { getToken: getTurnstileToken, ready: turnstileReady, enabled: turnstileEnabled } = useTurnstile({ skip: skipTurnstile });
  const handleCopy = useCallback((msgId) => setCopiedMsgId(msgId), []);


  const messagesEndRef    = useRef(null);
  const lastUserMsgRef    = useRef(null);
  const textareaRef       = useRef(null);
  const abortControllerRef = useRef(null);
  const modelMenuRef      = useRef(null);
  const scrollTimeoutRef  = useRef(null);
  const pendingSendScroll = useRef(false);
  // Conversation IDs created locally during this session — we already
  // have their messages in state, so the URL→DB loader effect must
  // skip them (otherwise it overwrites the in-flight streaming AI
  // message with the not-yet-persisted DB snapshot, leaving the chat
  // visually empty until refresh).
  const ownedConvIds = useRef(new Set());

  useEffect(() => {
    return () => { if (abortControllerRef.current) abortControllerRef.current.abort(); };
  }, []);

  const lastMsgLenRef = useRef(0);
  useEffect(() => {
    const lastMsg = messages[messages.length - 1];
    const isStreaming = lastMsg?.streaming;
    const contentLen = (lastMsg?.content || '').length;
    if (isStreaming && contentLen - lastMsgLenRef.current < 80 && lastMsgLenRef.current > 0) return;
    lastMsgLenRef.current = contentLen;
    if (scrollTimeoutRef.current) clearTimeout(scrollTimeoutRef.current);
    scrollTimeoutRef.current = setTimeout(() => {
      if (pendingSendScroll.current && lastUserMsgRef.current) {
        pendingSendScroll.current = false;
        lastUserMsgRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
        return;
      }
      const container = messagesEndRef.current?.closest('.overflow-y-auto');
      if (container) {
        const atBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 150;
        if (atBottom) {
          messagesEndRef.current?.scrollIntoView({ behavior: isStreaming ? 'auto' : 'smooth', block: 'end' });
        }
      }
    }, isStreaming ? 120 : 40);
    return () => { if (scrollTimeoutRef.current) clearTimeout(scrollTimeoutRef.current); };
  }, [messages]);

  useEffect(() => {
    if (!user) return;
    apiClient().get('/user/credits')
      .then((res) => {
        const c = res.data;
        setCredits({ used: c.used ?? 0, limit: c.limit ?? null });
      })
      .catch(() => {});
  }, [user]);

  useEffect(() => {
    if (!subjectId) return;
    setSyncState('syncing');
    Promise.all([getSubject(subjectId), getChapters(subjectId)])
      .then(([subRes, chRes]) => { setSubject(subRes.data); setScopedChapters(chRes.data || []); setSyncState('idle'); })
      .catch(() => setSyncState('idle'));
  }, [subjectId]);

  useEffect(() => {
    if (!convId) return;
    // Skip server reload for conversations we just created locally —
    // their messages are already in state and the DB copy may be
    // missing the in-flight assistant message.
    if (ownedConvIds.current.has(convId)) return;
    setSyncState('syncing');
    const fetcher = user ? getConversation(convId) : getAnonConversation(convId);
    fetcher
      .then((r) => { const conv = r.data; setConversationId(conv.id); setMessages(conv.messages || []); setSyncState('idle'); })
      .catch(() => setSyncState('offline'));
  }, [convId, user]);

  useEffect(() => {
    const check = () => {
      if (document.visibilityState === 'visible') {
        fetch(`${API_BASE}/health`).then(() => setSyncState('idle')).catch(() => setSyncState('offline'));
      }
    };
    const goOffline = () => setSyncState('offline');
    const goOnline = () => {
      fetch(`${API_BASE}/health`).then(() => setSyncState('idle')).catch(() => setSyncState('offline'));
    };
    document.addEventListener('visibilitychange', check);
    window.addEventListener('offline', goOffline);
    window.addEventListener('online', goOnline);
    return () => {
      document.removeEventListener('visibilitychange', check);
      window.removeEventListener('offline', goOffline);
      window.removeEventListener('online', goOnline);
    };
  }, []);

  useEffect(() => {
    if (!showModelMenu) return;
    const handler = (e) => {
      if (modelMenuRef.current && !modelMenuRef.current.contains(e.target)) setShowModelMenu(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [showModelMenu]);

  const adjustTextarea = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, []);

  useEffect(() => { adjustTextarea(); }, [input, adjustTextarea]);

  const cardContext = useMemo(() => {
    if (!subjectId || !subject) return null;
    const lines = [];
    lines.push(`Subject: ${subject.name}`);
    if (subject.description) lines.push(`Description: ${subject.description}`);
    if (Array.isArray(subject.tags) && subject.tags.length)
      lines.push(`Topics covered: ${subject.tags.join(', ')}`);
    const rawBoard = (user?.board_name || '').trim();
    const boardLabel = rawBoard ? `${rawBoard}` : null;
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
          if (ch.content) entry += `\n${ch.content.slice(0, 400)}`;
          lines.push(entry);
        });
    }
    return lines.join('\n').slice(0, 4000);
  }, [subjectId, subject, scopedChapters, user]);

  const effectiveLimit = credits.limit ?? user?.credits_limit ?? null;
  const remaining    = effectiveLimit !== null ? Math.max(0, effectiveLimit - credits.used) : null;
  const creditPercent = effectiveLimit != null && effectiveLimit > 0 ? Math.min(100, (credits.used / effectiveLimit) * 100) : 0;
  const isOutOfCredits = effectiveLimit !== null && effectiveLimit !== undefined && remaining !== null && remaining <= 0;
  const isLow = effectiveLimit !== null && effectiveLimit > 0 && remaining !== null && remaining > 0 && remaining <= 5;

  const handleNewChat = useCallback(() => {
    setMessages([]);
    setConversationId(null);
    setInput('');
    navigate('/chat', { replace: true });
  }, [navigate]);

  const handleStop = useCallback(() => {
    if (abortControllerRef.current) abortControllerRef.current.abort();
    setIsLoading(false);
    setMessages((prev) =>
      prev.map((m, i) =>
        i === prev.length - 1 && m.role === 'assistant' ? { ...m, streaming: false } : m
      )
    );
  }, []);

  const sendMsg = async (text) => {
    if (!text.trim() || isLoading || isOutOfCredits || (!user && turnstileEnabled && !turnstileReady)) return;
    const msgId = Date.now().toString();
    const userMsg = { id: msgId + '_u', role: 'user', content: text, timestamp: new Date().toISOString() };
    const aiMsgId = msgId + '_a';
    const aiMsg   = { id: aiMsgId, role: 'assistant', content: '', streaming: true, timestamp: new Date().toISOString() };
    setMessages((prev) => [...prev, userMsg, aiMsg]);
    setInput('');
    setIsLoading(true);
    pendingSendScroll.current = true;
    setSyncState('syncing');
    if (abortControllerRef.current) abortControllerRef.current.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;
    const payload = {
      message: text, conversation_id: conversationId,
      subject_id: subjectId || null, subject_name: subject?.name || null,
      board_id: user?.board_id || null, board_name: user?.board_name || null,
      class_id: user?.class_id || null, class_name: user?.class_name || null,
      stream_name: user?.stream_name || null, model,
      card_context: cardContext || null, document_id: documentId || null,
      response_lang: responseLang !== 'en' ? responseLang : undefined,
    };
    try {
      const fetchHeaders = { 'Content-Type': 'application/json' };
      if (!user) {
        fetchHeaders['x-anon-id'] = getAnonId();
        const _tsToken = await getTurnstileToken();
        if (_tsToken) fetchHeaders['x-turnstile-token'] = _tsToken;
      }
      const response = await fetch(`${API_BASE}/ai/chat/stream`, {
        method: 'POST', headers: fetchHeaders,
        credentials: 'include', body: JSON.stringify(payload), signal: controller.signal,
        keepalive: false,
        priority: 'high',
      });
      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        if (response.status === 402) {
          toast.error('Credits exhausted — upgrade to continue.', { action: { label: 'Upgrade', onClick: () => navigate('/profile') } });
          setMessages((prev) => prev.filter((m) => m.id !== aiMsgId));
          return;
        }
        throw new Error(errData.detail || 'Stream failed');
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let fullContent = '';
      const meta = {
        convId: conversationId, ragSource: 'none', ragChunks: 0,
        ragSubjectId: null, ragSubjectName: null, ragSubjectIcon: null,
        ragSubjectGradient: null, ragChapterName: null, ragChapterSlug: null,
        ragBoardName: null, ragClassName: null, ragTopicName: null,
        ragChunkSnippet: null, ragStreamName: null, ragBoardSlug: null,
        ragClassSlug: null, ragSubjectSlug: null, libSources: [], hasError: false,
      };

      let pendingChunk = '';
      let flushTimer = null;
      const FLUSH_INTERVAL = 5;
      const flushPending = () => {
        if (!pendingChunk) return;
        fullContent += pendingChunk; pendingChunk = '';
        flushTimer = null;
        const snapshot = fullContent;
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last && last.id === aiMsgId) {
            const updated = prev.slice();
            updated[updated.length - 1] = { ...last, content: snapshot, translating: false };
            return updated;
          }
          return prev;
        });
      };
      let sseBuffer = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        sseBuffer += decoder.decode(value, { stream: true });
        const lines = sseBuffer.split('\n');
        sseBuffer = lines.pop() || '';
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const raw = line.slice(6);
          if (raw === '[DONE]') break;
          let parsed;
          try { parsed = JSON.parse(raw); } catch { continue; }
          if (parsed.conversation_id) meta.convId = parsed.conversation_id;
          if (parsed.rag_source) meta.ragSource = parsed.rag_source;
          if (parsed.rag_chunks !== undefined) meta.ragChunks = parsed.rag_chunks;
          if (parsed.rag_subject_id) meta.ragSubjectId = parsed.rag_subject_id;
          if (parsed.rag_subject_name) meta.ragSubjectName = parsed.rag_subject_name;
          if (parsed.rag_subject_icon) meta.ragSubjectIcon = parsed.rag_subject_icon;
          if (parsed.rag_subject_gradient) meta.ragSubjectGradient = parsed.rag_subject_gradient;
          if (parsed.rag_chapter_name) meta.ragChapterName = parsed.rag_chapter_name;
          if (parsed.rag_chapter_slug) meta.ragChapterSlug = parsed.rag_chapter_slug;
          if (parsed.ctx_board_name) meta.ragBoardName = parsed.ctx_board_name;
          if (parsed.ctx_class_name) meta.ragClassName = parsed.ctx_class_name;
          if (parsed.ctx_stream_name) meta.ragStreamName = parsed.ctx_stream_name;
          if (parsed.ctx_board_slug) meta.ragBoardSlug = parsed.ctx_board_slug;
          if (parsed.ctx_class_slug) meta.ragClassSlug = parsed.ctx_class_slug;
          if (parsed.ctx_subject_slug) meta.ragSubjectSlug = parsed.ctx_subject_slug;
          if (parsed.rag_topic_name) meta.ragTopicName = parsed.rag_topic_name;
          if (parsed.rag_chunk_snippet) meta.ragChunkSnippet = parsed.rag_chunk_snippet;
          if (parsed.content_card_name && !meta.ragTopicName) meta.ragTopicName = parsed.content_card_name;
          if (parsed.content_card_board && !meta.ragBoardName) meta.ragBoardName = parsed.content_card_board;
          if (parsed.content_card_class && !meta.ragClassName) meta.ragClassName = parsed.content_card_class;
          if (parsed.content_card_subject && !meta.ragSubjectName) meta.ragSubjectName = parsed.content_card_subject;
          if (parsed.translating) {
            setMessages((prev) => prev.map((m) => m.id === aiMsgId ? { ...m, content: '', translating: true } : m));
            continue;
          }
          if (parsed.error) {
            meta.hasError = true;
            toast.error(parsed.error || 'AI service error — please try again.');
            setMessages((prev) => prev.map((m) => m.id === aiMsgId ? { ...m, content: 'Sorry, something went wrong. Please try again.', streaming: false } : m));
            continue;
          }
          if (meta.hasError) continue;
          if (parsed.content) {
            pendingChunk += parsed.content;
            if (!fullContent) flushPending();
            else if (!flushTimer) flushTimer = setTimeout(flushPending, FLUSH_INTERVAL);
          }
          if (parsed.event === 'syrabit_done') {
            if (parsed.sources) meta.libSources = parsed.sources;
            if (parsed.credits_used_total != null) {
              setCredits((c) => ({ ...c, used: parsed.credits_used_total }));
            }
            const remaining = parsed.remaining_credits ?? 0;
            try {
              Analytics.chatMessage(meta.ragSource, remaining, model);
              if (remaining <= 0) Analytics.chatCreditsExhausted();
            } catch {}
          }
        }
      }
      if (flushTimer) { clearTimeout(flushTimer); flushTimer = null; }
      if (pendingChunk) { fullContent += pendingChunk; pendingChunk = ''; }
      if (meta.convId && meta.convId !== conversationId) {
        ownedConvIds.current.add(meta.convId);
        setConversationId(meta.convId);
        setSearchParams((prev) => { const next = new URLSearchParams(prev); next.set('id', meta.convId); return next; }, { replace: true });
      } else { setConversationId(meta.convId); }
      setMessages((prev) => prev.map((m) =>
        m.id === aiMsgId
          ? { ...m, content: fullContent, streaming: false, rag_source: meta.ragSource, rag_chunks: meta.ragChunks, rag_subject_id: meta.ragSubjectId, rag_subject_name: meta.ragSubjectName, rag_chapter_name: meta.ragChapterName, rag_chapter_slug: meta.ragChapterSlug, rag_board_name: meta.ragBoardName, rag_class_name: meta.ragClassName, rag_stream_name: meta.ragStreamName, rag_board_slug: meta.ragBoardSlug, rag_class_slug: meta.ragClassSlug, rag_subject_slug: meta.ragSubjectSlug, rag_topic_name: meta.ragTopicName, rag_chunk_snippet: meta.ragChunkSnippet, ctx_subject_name: subject?.name || null, ctx_subject_icon: meta.ragSubjectIcon || subject?.icon || null, ctx_subject_gradient: meta.ragSubjectGradient || subject?.gradient || null, sources: meta.libSources }
          : m
      ));
      setSyncState('idle');
    } catch (err) {
      if (err.name === 'AbortError') return;
      toast.error(err.message || 'Failed to get AI response');
      setMessages((prev) => prev.filter((m) => m.id !== aiMsgId));
      setSyncState('offline');
    } finally { setIsLoading(false); }
  };

  const handleRegenerate = useCallback(() => {
    const lastUser = [...messages].reverse().find((m) => m.role === 'user');
    if (lastUser) { setMessages((prev) => prev.slice(0, -1)); sendMsg(lastUser.content); }
  }, [messages]); // eslint-disable-line

  const { contentLang } = useContentLang();
  const defaultPrompts = (() => {
    if (subject) {
      return contentLang === 'as'
        ? [
            `${subject.name}ৰ মূল ধাৰণাবোৰ বুজাই দিয়ক`,
            `পৰীক্ষাৰ বাবে ${subject.name}ৰ আটাইতকৈ গুৰুত্বপূৰ্ণ বিষয়বোৰ কি?`,
            `${subject.name}ৰ এটা সমাধান কৰা উদাহৰণ দিয়ক`,
            `${subject.name}ত ছাত্ৰ-ছাত্ৰীয়ে কৰা সাধাৰণ ভুলবোৰ কি?`,
          ]
        : [
            `Explain the key concepts of ${subject.name}`,
            `What are the most important topics in ${subject.name} for exams?`,
            `Give me a solved example from ${subject.name}`,
            `What are common mistakes students make in ${subject.name}?`,
          ];
    }
    return contentLang === 'as'
      ? [
          'এই ধাৰণাটো ধাপে ধাপে বুজাই দিয়ক',
          'পৰীক্ষাৰ বাবে সাজু এটা উত্তৰ দিয়ক',
          'এটা সমাধান কৰা উদাহৰণ দেখুৱাওক',
          'মনত ৰাখিবলগীয়া মুখ্য কথাবোৰ কি?',
        ]
      : [
          'Explain this concept step by step',
          'Give me an exam-ready answer',
          'Show me a solved example',
          'What are the key points to remember?',
        ];
  })();

  return (
    <>
      <title>Syrabit AI Chat — Ask Anything About Your Syllabus</title>
      <meta
        name="description"
        content="Ask Syrabit's AI tutor anything about AHSEC, SEBA and Degree subjects. Get instant explanations, MCQs, definitions and exam-ready answers in English or Assamese."
      />
      <link rel="canonical" href="https://syrabit.ai/chat" />
      {/* /chat is auth-gated and personalized — keep it out of the index. */}
      <meta name="robots" content="noindex, follow" />
      <meta property="og:title" content="Syrabit AI Chat — Ask Anything About Your Syllabus" />
      <meta
        property="og:description"
        content="AI-powered tutor for Assam Board (AHSEC, SEBA) and Degree students. Free to start, no card needed."
      />
      <meta property="og:url" content="https://syrabit.ai/chat" />
      <meta name="twitter:title" content="Syrabit AI Chat — Ask Anything About Your Syllabus" />
      <meta
        name="twitter:description"
        content="AI-powered tutor for Assam Board (AHSEC, SEBA) and Degree students. Free to start, no card needed."
      />
      <AppLayout pageTitle={
        <ModelSelector
          model={model} setModel={setModel}
          showModelMenu={showModelMenu} setShowModelMenu={setShowModelMenu}
          modelMenuRef={modelMenuRef} handleNewChat={handleNewChat}
          responseLang={responseLang} setResponseLang={setResponseLang}
        />
      }>
      <div className="flex flex-col chat-viewport-height">
        {isOutOfCredits && (
          <div
            className="flex items-center justify-between px-4 py-2.5 text-sm flex-shrink-0"
            style={{ background: 'rgba(239,68,68,0.08)', borderBottom: '1px solid rgba(239,68,68,0.15)' }}
            role="alert"
          >
            <div className="flex items-center gap-2 text-red-400">
              <AlertTriangle size={14} aria-hidden="true" />
              <span>{credits.limit === 0 ? 'Free plan has no credits — upgrade to start chatting' : 'Credits exhausted — upgrade to continue'}</span>
            </div>
            <button onClick={() => navigate('/profile')} className="text-xs font-semibold text-red-300 hover:text-red-200 transition-colors underline" aria-label="Go to profile to upgrade plan">Upgrade →</button>
          </div>
        )}
        <div className="flex-1 overflow-y-auto min-h-0 pb-[calc(8rem+68px+env(safe-area-inset-bottom,0px))] md:pb-32" onClick={() => setShowModelMenu(false)} role="log" aria-label="Chat messages" aria-live="polite">
          <div className="max-w-3xl mx-auto px-4 md:px-6 py-4">
            {messages.length === 0 && (
              <div style={{ minHeight: '420px' }}>
                <EmptyState subject={subject} documentId={documentId} defaultPrompts={defaultPrompts} setInput={setInput} textareaRef={textareaRef} />
              </div>
            )}
              {(() => {
                let lastUIdx = -1;
                for (let j = messages.length - 1; j >= 0; j--) { if (messages[j].role === 'user') { lastUIdx = j; break; } }
                const out = [];
                messages.forEach((msg, i) => {
                  out.push(
                    <div key={msg.id || i} ref={i === lastUIdx ? lastUserMsgRef : undefined}>
                      <MessageBubble msg={msg} isLast={i === messages.length - 1} onCopy={handleCopy} onRegenerate={msg.role === 'assistant' && i === messages.length - 1 ? handleRegenerate : null} messageIndex={i} conversationId={conversationId} responseLang={responseLang} />
                    </div>
                  );
                });
                return out;
              })()}
            <div ref={messagesEndRef} />
          </div>
        </div>
        <InputBar
          subject={subject} messages={messages} scopedChapters={scopedChapters}
          input={input} setInput={setInput} isLoading={isLoading}
          isOutOfCredits={isOutOfCredits} isLow={isLow} credits={credits}
          effectiveLimit={effectiveLimit} remaining={remaining} creditPercent={creditPercent}
          textareaRef={textareaRef} adjustTextarea={adjustTextarea} sendMsg={sendMsg} handleStop={handleStop}
        />
      </div>
      </AppLayout>
    </>
  );
}
