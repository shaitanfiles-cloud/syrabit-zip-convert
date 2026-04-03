/**
 * ChatPage — /chat
 * Full spec rebuild: 5-element animated empty state, typed bubbles,
 * actions bar (copy / regenerate / timestamp / credit badge),
 * credit progress bar, sync indicator, RAG source badge.
 */
import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { AlertTriangle } from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import { getConversation, getSubject, getChapters, API_BASE, apiClient } from '@/utils/api';
import { AppLayout } from '@/components/layout/AppLayout';
import { toast } from 'sonner';

import '@/styles/perplexity-chat.css';

import { MessageBubble } from './chat/MessageBubble';
import { EmptyState } from './chat/EmptyState';
import { InputBar } from './chat/InputBar';
import { ModelSelector, MODELS } from './chat/ModelSelector';

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

  const messagesEndRef    = useRef(null);
  const textareaRef       = useRef(null);
  const abortControllerRef = useRef(null);
  const modelMenuRef      = useRef(null);
  const scrollTimeoutRef  = useRef(null);

  useEffect(() => {
    return () => { if (abortControllerRef.current) abortControllerRef.current.abort(); };
  }, []);

  useEffect(() => {
    if (scrollTimeoutRef.current) clearTimeout(scrollTimeoutRef.current);
    scrollTimeoutRef.current = setTimeout(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }, 0);
    return () => { if (scrollTimeoutRef.current) clearTimeout(scrollTimeoutRef.current); };
  }, [messages]);

  useEffect(() => {
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
    getSubject(subjectId)
      .then((r) => { setSubject(r.data); return getChapters(subjectId); })
      .then((r) => { setScopedChapters(r.data || []); setSyncState('idle'); })
      .catch(() => setSyncState('idle'));
  }, [subjectId]);

  useEffect(() => {
    if (!convId) return;
    setSyncState('syncing');
    getConversation(convId)
      .then((r) => { const conv = r.data; setConversationId(conv.id); setMessages(conv.messages || []); setSyncState('idle'); })
      .catch(() => setSyncState('offline'));
  }, [convId, user]);

  useEffect(() => {
    const check = () => {
      if (document.visibilityState === 'visible') {
        fetch(`${API_BASE}/health`).then(() => setSyncState('idle')).catch(() => setSyncState('offline'));
      }
    };
    document.addEventListener('visibilitychange', check);
    return () => document.removeEventListener('visibilitychange', check);
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
          if (ch.content) entry += `\n${ch.content.slice(0, 200)}`;
          lines.push(entry);
        });
    }
    return lines.join('\n').slice(0, 2500);
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
    if (!text.trim() || isLoading || isOutOfCredits) return;
    const msgId = Date.now().toString();
    const userMsg = { id: msgId + '_u', role: 'user', content: text, timestamp: new Date().toISOString() };
    const aiMsgId = msgId + '_a';
    const aiMsg   = { id: aiMsgId, role: 'assistant', content: '', streaming: true, timestamp: new Date().toISOString() };
    setMessages((prev) => [...prev, userMsg, aiMsg]);
    setInput('');
    setIsLoading(true);
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
    };
    try {
      const response = await fetch(`${API_BASE}/ai/chat/stream`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        credentials: 'include', body: JSON.stringify(payload), signal: controller.signal,
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
      let newConvId = conversationId;
      let ragSource = 'none';
      let ragChunks = 0;
      let ragSubjectId = null;
      let ragSubjectName = null;
      let ragSubjectIcon = null;
      let ragSubjectGradient = null;
      let ragChapterName = null;
      let ragBoardName = null;
      let ragClassName = null;
      let ragTopicName = null;
      let ragStreamName = null;
      let libSources = [];
      let hasError = false;

      // RAF-based batching: accumulate chunks between animation frames
      // so React re-renders at most 60×/sec instead of on every token
      let pendingChunk = '';
      let rafId = null;
      const flushPending = () => {
        if (!pendingChunk) return;
        fullContent += pendingChunk; pendingChunk = ''; rafId = null;
        const snapshot = fullContent;
        setMessages((prev) => prev.map((m) => m.id === aiMsgId ? { ...m, content: snapshot } : m));
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
            if (parsed.rag_subject_icon) ragSubjectIcon = parsed.rag_subject_icon;
            if (parsed.rag_subject_gradient) ragSubjectGradient = parsed.rag_subject_gradient;
            if (parsed.rag_chapter_name) ragChapterName = parsed.rag_chapter_name;
            if (parsed.ctx_board_name) ragBoardName = parsed.ctx_board_name;
            if (parsed.ctx_class_name) ragClassName = parsed.ctx_class_name;
            if (parsed.ctx_stream_name) ragStreamName = parsed.ctx_stream_name;
            if (parsed.rag_topic_name) ragTopicName = parsed.rag_topic_name;
            if (parsed.content_card_name && !ragTopicName) ragTopicName = parsed.content_card_name;
            if (parsed.content_card_board && !ragBoardName) ragBoardName = parsed.content_card_board;
            if (parsed.content_card_class && !ragClassName) ragClassName = parsed.content_card_class;
            if (parsed.content_card_subject && !ragSubjectName) ragSubjectName = parsed.content_card_subject;
            if (parsed.error) {
              hasError = true;
              toast.error(parsed.error || 'AI service error — please try again.');
              setMessages((prev) => prev.map((m) => m.id === aiMsgId ? { ...m, content: 'Sorry, something went wrong. Please try again.', streaming: false } : m));
              continue;
            }
            if (hasError) continue;
            if (parsed.content) {
              pendingChunk += parsed.content;
              if (!fullContent && !rafId) flushPending();
              else if (!rafId) rafId = requestAnimationFrame(flushPending);
            }
            if (parsed.event === 'syrabit_done') {
              if (parsed.sources) libSources = parsed.sources;
              if (parsed.credits_used_total != null) {
                setCredits((c) => ({ ...c, used: parsed.credits_used_total }));
              }
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
      if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
      if (pendingChunk) { fullContent += pendingChunk; pendingChunk = ''; }
      if (newConvId && newConvId !== conversationId) {
        setConversationId(newConvId);
        setSearchParams((prev) => { const next = new URLSearchParams(prev); next.set('id', newConvId); return next; }, { replace: true });
      } else { setConversationId(newConvId); }
      setMessages((prev) => prev.map((m) =>
        m.id === aiMsgId
          ? { ...m, content: fullContent, streaming: false, rag_source: ragSource, rag_chunks: ragChunks, rag_subject_id: ragSubjectId, rag_subject_name: ragSubjectName, rag_chapter_name: ragChapterName, rag_board_name: ragBoardName, rag_class_name: ragClassName, rag_stream_name: ragStreamName, rag_topic_name: ragTopicName, ctx_subject_name: subject?.name || null, ctx_subject_icon: ragSubjectIcon || subject?.icon || null, ctx_subject_gradient: ragSubjectGradient || subject?.gradient || null, sources: libSources }
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

  return (
    <AppLayout pageTitle={
      <ModelSelector
        model={model} setModel={setModel}
        showModelMenu={showModelMenu} setShowModelMenu={setShowModelMenu}
        modelMenuRef={modelMenuRef} handleNewChat={handleNewChat}
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
              <EmptyState subject={subject} scopedChapters={scopedChapters} documentId={documentId} defaultPrompts={defaultPrompts} setInput={setInput} textareaRef={textareaRef} />
            )}
              {messages.map((msg, i) => (
                <MessageBubble key={msg.id || i} msg={msg} isLast={i === messages.length - 1} onCopy={() => setCopiedMsgId(msg.id)} onRegenerate={msg.role === 'assistant' && i === messages.length - 1 ? handleRegenerate : null} messageIndex={i} conversationId={conversationId} />
              ))}
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
  );
}
