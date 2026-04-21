/**
 * BrowserPage — /browse  (Task #577 Phase 2)
 *
 * Real browser-like surface for Syrabit's curated educational web:
 *   - Tab strip (open / close / switch / reorder by drag-DnD-free swap)
 *   - Smart address bar: detects URL vs. natural-language question
 *   - Reader-mode pane fed by /api/edu/reader/fetch (server proxy +
 *     Readability-lite extraction + 24 h Redis cache + robots.txt + SSRF)
 *   - Per-tab back / forward history
 *   - Bookmarks drawer
 *   - Recent history list
 *   - "Ask Syra" side panel that streams a grounded answer over SSE
 *     and reads the current page as context (Summarize / Explain
 *     simply / Translate to Assamese quick actions).
 *   - State persisted to Mongo via /api/edu/state (logged-in user OR
 *     anon-id), with localStorage as the synchronous fallback.
 *   - Curated educational allow-list with a "Request this site"
 *     escape hatch when the user asks for a blocked domain.
 *   - Mobile responsive (tab sheet + drawer side panel).
 *   - Bilingual labels (EN / AS) via useContentLang().
 */
import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowLeft, ArrowRight, RotateCw, X, Plus, Star, Search, Globe,
  Sparkles, BookmarkPlus, Clock, ShieldAlert, ExternalLink,
  PanelRightClose, PanelRightOpen, Menu, Loader2, Languages,
  StickyNote, Square, HelpCircle, GraduationCap, CheckCircle2,
  AlertTriangle,
} from 'lucide-react';
import ModalOverlay from '@/components/ui/ModalOverlay';
import { AppLayout } from '@/components/layout/AppLayout';
import { ReadAloudButton } from '@/components/study/ReadAloudButton';
import { QuizModal } from '@/components/study/QuizModal';
import { HighlightSavePopover } from '@/components/study/HighlightSavePopover';
import { useAuth } from '@/context/AuthContext';
import { useContentLang } from '@/context/LanguageContext';
import {
  eduFetchReader, eduGetAllowlist, eduRequestSite, eduCheckUrl,
  eduLoadState, eduSaveState, eduGroundedAnswerUrl, getAnonId,
  eduEducatorSubmitSite,
} from '@/utils/api';
import { toast } from 'sonner';

// ── i18n -----------------------------------------------------------------
const T = {
  en: {
    title: 'Syra Browser',
    addressPh: 'Type a URL or ask a question',
    go: 'Go',
    newTab: 'New tab',
    blank: 'New tab',
    home: 'Start',
    back: 'Back',
    forward: 'Forward',
    reload: 'Reload',
    bookmarks: 'Bookmarks',
    history: 'History',
    ask: 'Ask Syra',
    summarize: 'Summarize this page',
    explain: 'Explain simply',
    translate: 'Translate to Assamese',
    bookmark: 'Bookmark',
    bookmarked: 'Saved',
    open: 'Open',
    blocked: 'This site isn\u2019t in the educational list',
    blockedSub: 'Syra Browser only loads vetted educational sources for kids and students.',
    requestSite: 'Request this site',
    requested: 'Request received \u2014 we\u2019ll review it.',
    loading: 'Loading reader\u2026',
    failed: 'Couldn\u2019t load this page',
    suggested: 'Try one of these',
    askPh: 'Ask anything about this page',
    panel: 'Side panel',
    closePanel: 'Close panel',
    openPanel: 'Open panel',
    typing: 'Syra is typing\u2026',
    citations: 'Sources',
    stop: 'Stop',
    empty: 'Open a tab to start exploring.',
    confirmClose: 'Close this tab?',
    by: 'by',
    on: 'on',
    minRead: 'min read',
    educatorSubmit: 'Suggest a site',
    educatorSubmitTitle: 'Suggest a site for the educational web',
    educatorSubmitSub: 'As an educator, you can add a domain directly. We run a quick kid-safe + robots.txt probe before auto-approving it for all students.',
    educatorDomain: 'Domain',
    educatorDomainPh: 'e.g. example.org',
    educatorNote: 'Note (optional)',
    educatorNotePh: 'Why is this site useful for students?',
    educatorSubmitBtn: 'Submit for review',
    educatorSubmitting: 'Probing site…',
    educatorAutoApproved: 'Auto-approved! Students can now open this site.',
    educatorAlreadyAllowed: 'This site is already on the educational allowlist.',
    educatorRejected: 'Site was not auto-approved.',
    educatorReason: 'Reason',
    educatorOpenNow: 'Open in browser',
    educatorClose: 'Close',
  },
  as: {
    title: 'চিৰা ব্ৰাউজাৰ',
    addressPh: 'URL দিয়ক বা প্ৰশ্ন সোধক',
    go: 'যাওক',
    newTab: 'নতুন টেব',
    blank: 'নতুন টেব',
    home: 'আৰম্ভ',
    back: 'পিছলৈ',
    forward: 'আগলৈ',
    reload: 'পুনৰ লোড',
    bookmarks: 'বুকমাৰ্ক',
    history: 'ইতিহাস',
    ask: 'চিৰাক সোধক',
    summarize: 'এই পৃষ্ঠাৰ সাৰাংশ',
    explain: 'সৰল ভাষাত বুজাই দিয়ক',
    translate: 'অসমীয়ালৈ অনুবাদ',
    bookmark: 'বুকমাৰ্ক',
    bookmarked: 'সংৰক্ষিত',
    open: 'খোলক',
    blocked: 'এই ছাইট শিক্ষাগত তালিকাত নাই',
    blockedSub: 'চিৰা ব্ৰাউজাৰে কেৱল ছাত্ৰ-ছাত্ৰীৰ বাবে অনুমোদিত শিক্ষাগত উৎসহে দেখুৱাই।',
    requestSite: 'এই ছাইটৰ অনুৰোধ পঠাওক',
    requested: 'আপোনাৰ অনুৰোধ গ্ৰহণ কৰা হৈছে।',
    loading: 'লোড হৈ আছে…',
    failed: 'এই পৃষ্ঠা লোড নহল',
    suggested: 'এইবোৰ চেষ্টা কৰক',
    askPh: 'এই পৃষ্ঠাৰ বিষয়ে যিকোনো প্ৰশ্ন সোধক',
    panel: 'চাইড পেনেল',
    closePanel: 'পেনেল বন্ধ',
    openPanel: 'পেনেল খোলক',
    typing: 'চিৰাই লিখি আছে…',
    citations: 'উৎসসমূহ',
    stop: 'বন্ধ',
    empty: 'অন্বেষণ আৰম্ভ কৰিবলৈ এটা টেব খোলক।',
    confirmClose: 'এই টেব বন্ধ কৰিবনে?',
    by: 'লিখক',
    on: 'প্ৰকাশক',
    minRead: 'মিনিট পঢ়া',
    educatorSubmit: 'ছাইট পৰামৰ্শ',
    educatorSubmitTitle: 'শিক্ষাগত ৱেবলৈ এটা ছাইট পৰামৰ্শ দিয়ক',
    educatorSubmitSub: 'শিক্ষক হিচাপে আপুনি প্ৰত্যক্ষভাৱে এটা ডোমেইন যোগ কৰিব পাৰে। আমি প্ৰথমে কিড-ছেফ আৰু robots.txt পৰীক্ষা কৰোঁ।',
    educatorDomain: 'ডোমেইন',
    educatorDomainPh: 'উদাহৰণ: example.org',
    educatorNote: 'মন্তব্য (ঐচ্ছিক)',
    educatorNotePh: 'এই ছাইট ছাত্ৰ-ছাত্ৰীৰ বাবে কিয় উপযোগী?',
    educatorSubmitBtn: 'পৰীক্ষাৰ বাবে পঠাওক',
    educatorSubmitting: 'ছাইট পৰীক্ষা চলিছে…',
    educatorAutoApproved: 'অনুমোদিত! এতিয়া ছাত্ৰ-ছাত্ৰীয়ে এই ছাইট খোলিব পাৰিব।',
    educatorAlreadyAllowed: 'এই ছাইট ইতিমধ্যে অনুমোদিত তালিকাত আছে।',
    educatorRejected: 'ছাইটটো স্বয়ংক্ৰিয়ভাৱে অনুমোদিত নহল।',
    educatorReason: 'কাৰণ',
    educatorOpenNow: 'ব্ৰাউজাৰত খোলক',
    educatorClose: 'বন্ধ',
  },
};

// ── helpers --------------------------------------------------------------
const STORAGE_KEY = 'syrabit_browser_state_v1';
const MAX_HISTORY_ENTRIES = 200;

const newId = () => 'tab_' + Math.random().toString(36).slice(2, 10);

const blankTab = () => ({
  id: newId(),
  title: '',
  url: '',
  history: [],   // [{ url, title }]
  hIdx: -1,
});

function isLikelyUrl(input) {
  const s = input.trim();
  if (!s) return false;
  if (/^https?:\/\//i.test(s)) return true;
  // domain.tld[/...]
  if (/^[a-z0-9-]+(\.[a-z0-9-]+)+(\/.*)?$/i.test(s) && !s.includes(' ')) return true;
  return false;
}
function normalizeUrl(input) {
  const s = input.trim();
  if (/^https?:\/\//i.test(s)) return s;
  return 'https://' + s;
}
function hostOf(url) {
  try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return ''; }
}
function readingTime(text) {
  if (!text) return 0;
  const words = text.trim().split(/\s+/).length;
  return Math.max(1, Math.round(words / 200));
}

function loadLocalState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch { return null; }
}
function saveLocalState(state) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch {}
}

// Walk the rendered article DOM and wrap matching span text in a
// <mark data-grounding="1"> element so the reader pane visually flags
// the sentences that grounded Syra's answer. Only matches confined to a
// single text node are highlighted (good enough for typical paragraph
// prose and avoids cross-element splice complexity). Returns a Map of
// `citationIndex -> HTMLElement[]` so callers can scroll/flash later.
function _highlightGroundingSpans(root, spans) {
  const map = new Map();
  if (!root || !spans || !spans.length) return map;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(n) {
      if (!n.nodeValue || !n.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
      if (n.parentNode && n.parentNode.closest('mark[data-grounding]')) {
        return NodeFilter.FILTER_REJECT;
      }
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  const textNodes = [];
  let cur;
  while ((cur = walker.nextNode())) textNodes.push(cur);
  // Highlight longer spans first so an enclosing sentence wins over a
  // shorter sub-phrase from the same citation.
  const ordered = [...spans].sort((a, b) => b.text.length - a.text.length);
  // Lookup span in haystack tolerating case + collapsed whitespace.
  // Returns the [start, end) range *in the original haystack*, or null.
  const findFlexible = (haystack, needle) => {
    const direct = haystack.indexOf(needle);
    if (direct >= 0) return [direct, direct + needle.length];
    const ci = haystack.toLowerCase().indexOf(needle.toLowerCase());
    if (ci >= 0) return [ci, ci + needle.length];
    // Whitespace-tolerant fallback: build a regex from the needle that
    // treats each whitespace run as `\s+`. Escape regex metachars first.
    const escaped = needle
      .trim()
      .replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      .replace(/\s+/g, '\\s+');
    try {
      const re = new RegExp(escaped, 'i');
      const m = re.exec(haystack);
      if (m) return [m.index, m.index + m[0].length];
    } catch { /* malformed needle — skip */ }
    return null;
  };
  for (const span of ordered) {
    const needle = (span.text || '').trim();
    if (needle.length < 4) continue;
    for (let i = 0; i < textNodes.length; i++) {
      const node = textNodes[i];
      if (!node.parentNode) continue;
      const haystack = node.nodeValue;
      const range = findFlexible(haystack, needle);
      if (!range) continue;
      const [start, end] = range;
      const before = haystack.slice(0, start);
      const matched = haystack.slice(start, end);
      const after = haystack.slice(end);
      const mark = document.createElement('mark');
      mark.setAttribute('data-grounding', '1');
      mark.setAttribute('data-citation-index', String(span.citationIndex));
      mark.setAttribute('data-span-key', span.key);
      mark.style.cssText =
        'background: rgba(245,158,11,0.16); color: inherit; border-radius: 2px; ' +
        'padding: 0 2px; cursor: pointer; transition: background 220ms ease, box-shadow 220ms ease;';
      mark.textContent = matched;
      const parent = node.parentNode;
      if (after) {
        const afterNode = document.createTextNode(after);
        parent.insertBefore(afterNode, node.nextSibling);
        textNodes.splice(i + 1, 0, afterNode);
      }
      parent.insertBefore(mark, node.nextSibling);
      if (before) {
        node.nodeValue = before;
      } else {
        parent.removeChild(node);
        textNodes.splice(i, 1);
        i--;
      }
      const arr = map.get(span.citationIndex) || [];
      arr.push(mark);
      map.set(span.citationIndex, arr);
      break; // only highlight first occurrence per span
    }
  }
  return map;
}

// Render the safe HTML returned by the reader-proxy. It's already
// sanitized server-side, but we still render via a sandboxed div with
// rel=noopener on links and force target=_blank for outbound clicks.
// `citations` may carry per-citation `spans: [text]` for the page-type
// citation — those sentences are highlighted inline and scrolled into
// view when `flashCite` changes.
function ReaderArticle({ payload, lang, citations, flashCite, onSpanClick }) {
  const ref = useRef(null);
  const highlightMapRef = useRef(new Map());
  const [quizOpen, setQuizOpen] = useState(false);
  // edu_reader.fetch_and_extract returns the cleaned article body
  // under the `html` key (`content_html` is a legacy alias kept for
  // forward-compat — fall back to either).
  const html = payload?.html || payload?.content_html || '';

  // Render HTML manually (instead of dangerouslySetInnerHTML) so that
  // re-running the highlight effect on `citations` change doesn't fight
  // React over the DOM contents.
  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    root.innerHTML = html || '';
    root.querySelectorAll('a[href]').forEach((a) => {
      a.setAttribute('target', '_blank');
      a.setAttribute('rel', 'noopener noreferrer');
    });
    // Strip iframes / scripts defensively (server already does, but
    // belt-and-braces).
    root.querySelectorAll('script,iframe,object,embed').forEach((n) => n.remove());

    const spans = [];
    (citations || []).forEach((c) => {
      if (!Array.isArray(c.spans)) return;
      c.spans.forEach((text, idx) => {
        if (typeof text === 'string' && text.trim().length > 3) {
          spans.push({
            text: text.trim(),
            citationIndex: c.index,
            key: `${c.index}-${idx}`,
          });
        }
      });
    });
    highlightMapRef.current = _highlightGroundingSpans(root, spans);

    if (onSpanClick) {
      root.querySelectorAll('mark[data-grounding]').forEach((m) => {
        m.addEventListener('click', () => {
          const ci = Number(m.getAttribute('data-citation-index'));
          if (Number.isFinite(ci)) onSpanClick(ci);
        });
      });
    }
  }, [html, citations, onSpanClick]);

  // Scroll-into-view + brief flash when a citation [N] is tapped in the
  // side panel. Uses a `nonce` so re-clicking the same citation re-fires
  // the effect.
  useEffect(() => {
    if (!flashCite) return;
    const list = highlightMapRef.current.get(flashCite.citationIndex);
    if (!list || !list.length) return;
    list[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
    list.forEach((m) => {
      m.style.background = 'rgba(245,158,11,0.55)';
      m.style.boxShadow = '0 0 0 3px rgba(245,158,11,0.35)';
    });
    const t = setTimeout(() => {
      list.forEach((m) => {
        m.style.background = 'rgba(245,158,11,0.16)';
        m.style.boxShadow = 'none';
      });
    }, 1600);
    return () => clearTimeout(t);
  }, [flashCite]);

  const domain = payload?.domain || hostOf(payload?.url);
  const minutes = readingTime(payload?.text);
  return (
    <article className="mx-auto max-w-3xl px-4 py-6 sm:px-8 sm:py-10">
      {payload?.title && (
        <h1 className="mb-2 text-2xl font-bold leading-tight text-slate-900 dark:text-slate-50 sm:text-3xl">
          {payload.title}
        </h1>
      )}
      <div className="mb-6 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
        {payload?.byline && <span>{T[lang].by} <strong className="text-slate-700 dark:text-slate-300">{payload.byline}</strong></span>}
        {domain && <span>{T[lang].on} <a href={payload.url} target="_blank" rel="noopener noreferrer" className="font-medium text-violet-600 hover:underline">{domain}</a></span>}
        {minutes > 0 && <span>{minutes} {T[lang].minRead}</span>}
        {payload?.url && (
          <a href={payload.url} target="_blank" rel="noopener noreferrer"
             className="inline-flex items-center gap-1 text-violet-600 hover:underline">
            <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>
      <div className="mb-3 flex items-center gap-2">
        <ReadAloudButton id={`browser-${payload?.url || 'page'}`} text={payload?.text || ''} label="Read aloud" />
        <button
          onClick={() => setQuizOpen(true)}
          className="inline-flex items-center gap-1.5 text-xs px-2 py-1 rounded-md hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
        >
          <HelpCircle className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">Quiz me</span>
        </button>
      </div>
      <div
        ref={ref}
        data-savable="true"
        className="prose prose-slate max-w-none dark:prose-invert prose-headings:scroll-mt-20 prose-img:rounded-lg prose-a:text-violet-600 prose-a:no-underline hover:prose-a:underline"
      />
      <QuizModal
        open={quizOpen} onClose={() => setQuizOpen(false)}
        context={(payload?.text || '').slice(0, 6000)}
        topic={payload?.title || domain || 'this article'}
        count={6}
      />
    </article>
  );
}

// ── BlockedView ----------------------------------------------------------
function BlockedView({ url, suggestions, onOpenSuggestion, lang }) {
  const [reason, setReason] = useState('');
  const [sent, setSent] = useState(false);
  const t = T[lang];
  const domain = hostOf(url) || url;
  const submit = async () => {
    try {
      await eduRequestSite(domain, reason);
      setSent(true);
      toast.success(t.requested);
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Failed to send request');
    }
  };
  return (
    <div className="mx-auto max-w-xl px-6 py-12 text-center">
      <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
        <ShieldAlert className="h-7 w-7" />
      </div>
      <h2 className="mb-2 text-xl font-bold">{t.blocked}</h2>
      <p className="mb-1 text-sm text-slate-600 dark:text-slate-400">{t.blockedSub}</p>
      <p className="mb-6 break-all text-xs text-slate-500">{domain}</p>

      {!sent ? (
        <div className="mb-8 rounded-xl border border-slate-200 bg-white p-4 text-left dark:border-slate-700 dark:bg-slate-800">
          <label className="mb-2 block text-xs font-medium text-slate-600 dark:text-slate-300">
            {t.requestSite}
          </label>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Why is this site useful?"
            className="mb-3 w-full resize-none rounded-md border border-slate-300 bg-slate-50 p-2 text-sm dark:border-slate-600 dark:bg-slate-900"
            rows={2}
          />
          <button
            onClick={submit}
            className="rounded-md bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-700"
          >
            {t.requestSite}
          </button>
        </div>
      ) : (
        <div className="mb-8 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-700 dark:border-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300">
          {t.requested}
        </div>
      )}

      {suggestions?.length > 0 && (
        <div className="text-left">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            {t.suggested}
          </p>
          <ul className="grid gap-2 sm:grid-cols-2">
            {suggestions.slice(0, 6).map((d) => (
              <li key={d}>
                <button
                  onClick={() => onOpenSuggestion(`https://${d}`)}
                  className="flex w-full items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-left text-sm hover:border-violet-400 hover:bg-violet-50 dark:border-slate-700 dark:bg-slate-800 dark:hover:bg-slate-700"
                >
                  <Globe className="h-4 w-4 text-violet-500" />
                  <span className="truncate">{d}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ── AskSyraPanel ---------------------------------------------------------
function AskSyraPanel({ activeTab, lang, onClose, onCitationsChange, onCitationClick }) {
  const t = T[lang];
  const { user } = useAuth();
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [answer, setAnswer] = useState('');
  const [citations, setCitations] = useState([]);
  const [error, setError] = useState('');
  const ctrlRef = useRef(null);
  const scrollRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [answer]);

  // Mirror the panel's citation list up to BrowserPage so the reader
  // pane can highlight grounding sentences inline.
  useEffect(() => {
    onCitationsChange?.(citations);
  }, [citations, onCitationsChange]);

  const stop = useCallback(() => {
    try { ctrlRef.current?.abort(); } catch {}
    ctrlRef.current = null;
    setStreaming(false);
  }, []);

  // Cancel any in-flight stream when the active tab changes.
  useEffect(() => () => stop(), [activeTab?.id, stop]);

  const ask = useCallback(async (queryOverride) => {
    const query = (queryOverride ?? input).trim();
    if (!query || streaming) return;
    setError('');
    setAnswer('');
    setCitations([]);
    setStreaming(true);
    const ctrl = new AbortController();
    ctrlRef.current = ctrl;
    try {
      const body = {
        query,
        page_url: activeTab?.content?.payload?.url || activeTab?.url || '',
        response_lang: lang,
      };
      const resp = await fetch(eduGroundedAnswerUrl(), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', 'x-anon-id': getAnonId() },
        body: JSON.stringify(body),
        signal: ctrl.signal,
      });
      if (!resp.ok || !resp.body) {
        throw new Error(`HTTP ${resp.status}`);
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      let acc = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split('\n\n');
        buf = parts.pop() || '';
        for (const part of parts) {
          const line = part.split('\n').find((l) => l.startsWith('data:'));
          if (!line) continue;
          const data = line.slice(5).trim();
          if (data === '[DONE]') continue;
          try {
            const j = JSON.parse(data);
            if (j.event === 'meta' && Array.isArray(j.citations)) {
              setCitations(j.citations);
            } else if (j.event === 'cancelled' || j.event === 'safety_break') {
              break;
            } else if (j.event === 'error') {
              setError(j.detail || 'Stream error');
            } else if (typeof j.content === 'string') {
              acc += j.content;
              setAnswer(acc);
            }
          } catch {}
        }
      }
    } catch (e) {
      if (e.name !== 'AbortError') setError(e.message || String(e));
    } finally {
      setStreaming(false);
      ctrlRef.current = null;
    }
  }, [input, streaming, activeTab, lang]);

  const quick = (label) => ({
    summarize: lang === 'as'
      ? 'এই পৃষ্ঠাৰ সাৰাংশ সৰলভাৱে দিয়ক।'
      : 'Summarize this page in 5 short bullets a student can understand.',
    explain: lang === 'as'
      ? 'এই পৃষ্ঠাত উল্লেখ থকা মূল ধাৰণাবোৰ সৰল ভাষাত বুজাই দিয়ক।'
      : 'Explain the key ideas on this page in simple language for a student.',
    translate: 'Translate the key ideas of this page into clear Assamese for a student.',
  })[label];

  const hasPage = !!(activeTab?.content?.payload?.url);

  return (
    <aside className="flex h-full flex-col border-l border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900">
      <header className="flex shrink-0 items-center justify-between border-b border-slate-200 px-3 py-2 dark:border-slate-700">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-violet-600" />
          <h3 className="text-sm font-semibold">{t.ask}</h3>
        </div>
        <button onClick={onClose} aria-label={t.closePanel}
          className="rounded p-1 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800">
          <PanelRightClose className="h-4 w-4" />
        </button>
      </header>

      <div className="flex shrink-0 flex-wrap gap-1.5 border-b border-slate-100 px-3 py-2 dark:border-slate-800">
        <button
          disabled={!hasPage || streaming}
          onClick={() => ask(quick('summarize'))}
          className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-700 hover:border-violet-400 hover:bg-violet-50 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
        >
          <StickyNote className="h-3 w-3" /> {t.summarize}
        </button>
        <button
          disabled={!hasPage || streaming}
          onClick={() => ask(quick('explain'))}
          className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-700 hover:border-violet-400 hover:bg-violet-50 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
        >
          <Sparkles className="h-3 w-3" /> {t.explain}
        </button>
        <button
          disabled={!hasPage || streaming}
          onClick={() => ask(quick('translate'))}
          className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-700 hover:border-violet-400 hover:bg-violet-50 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
        >
          <Languages className="h-3 w-3" /> {t.translate}
        </button>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-3 py-3 text-sm leading-relaxed">
        {!answer && !streaming && !error && (
          <p className="text-xs text-slate-500">
            {hasPage
              ? (lang === 'as'
                  ? 'এই পৃষ্ঠাৰ সম্পৰ্কে যিকোনো প্ৰশ্ন সোধক।'
                  : 'Ask anything about this page or use a quick action above.')
              : (lang === 'as'
                  ? 'এটা পৃষ্ঠা খুলিলে চিৰাই সেইটো পঢ়ি প্ৰশ্নৰ উত্তৰ দিব পাৰিব।'
                  : 'Open a page first — Syra will read it and answer questions about it.')}
          </p>
        )}
        {streaming && !answer && (
          <p className="flex items-center gap-2 text-xs text-slate-500">
            <Loader2 className="h-3 w-3 animate-spin" /> {t.typing}
          </p>
        )}
        {answer && (
          <div className="whitespace-pre-wrap text-slate-800 dark:text-slate-100">{answer}</div>
        )}
        {error && (
          <div className="mt-2 rounded border border-rose-300 bg-rose-50 p-2 text-xs text-rose-700 dark:border-rose-700 dark:bg-rose-900/30 dark:text-rose-300">
            {error}
          </div>
        )}
        {citations.length > 0 && (
          <div className="mt-4 border-t border-slate-200 pt-3 dark:border-slate-700">
            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              {t.citations}
            </p>
            <ol className="space-y-1.5 text-xs">
              {citations.map((c) => {
                const hasSpans = Array.isArray(c.spans) && c.spans.length > 0;
                return (
                  <li key={c.index} className="flex items-start gap-1.5">
                    {hasSpans ? (
                      <button
                        type="button"
                        onClick={() => onCitationClick?.(c)}
                        className="font-mono text-violet-600 hover:text-violet-800 hover:underline dark:text-violet-300"
                        title={lang === 'as' ? 'প্ৰবন্ধত দেখুৱাওক' : 'Highlight in article'}
                      >
                        [{c.index}]
                      </button>
                    ) : (
                      <span className="font-mono text-violet-600 dark:text-violet-300">[{c.index}]</span>
                    )}
                    {c.url ? (
                      <a href={c.url} target="_blank" rel="noopener noreferrer"
                         className="line-clamp-2 text-violet-700 hover:underline dark:text-violet-300">
                        {c.title || c.domain || c.url}
                      </a>
                    ) : (
                      <span className="line-clamp-2 text-slate-700 dark:text-slate-300">{c.title}</span>
                    )}
                  </li>
                );
              })}
            </ol>
          </div>
        )}
      </div>

      <form
        onSubmit={(e) => { e.preventDefault(); ask(); }}
        className="shrink-0 border-t border-slate-200 p-2 dark:border-slate-700"
      >
        <div className="flex items-end gap-1.5">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                ask();
              }
            }}
            placeholder={t.askPh}
            rows={2}
            className="flex-1 resize-none rounded-md border border-slate-300 bg-slate-50 p-2 text-sm focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500 dark:border-slate-600 dark:bg-slate-900"
          />
          {streaming ? (
            <button type="button" onClick={stop}
              className="rounded-md bg-rose-600 p-2 text-white hover:bg-rose-700"
              aria-label={t.stop}>
              <Square className="h-4 w-4" />
            </button>
          ) : (
            <button type="submit" disabled={!input.trim()}
              className="rounded-md bg-violet-600 p-2 text-white hover:bg-violet-700 disabled:opacity-50"
              aria-label={t.ask}>
              <Sparkles className="h-4 w-4" />
            </button>
          )}
        </div>
      </form>
    </aside>
  );
}

// ── BookmarksPane --------------------------------------------------------
function BookmarksPane({ bookmarks, history, onOpen, onRemoveBookmark, onClearHistory, lang }) {
  const t = T[lang];
  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-4 text-sm">
      <section>
        <h4 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          <Star className="h-3 w-3" /> {t.bookmarks}
        </h4>
        {bookmarks.length === 0
          ? <p className="text-xs text-slate-400">—</p>
          : (
            <ul className="space-y-1">
              {bookmarks.map((b) => (
                <li key={b.url} className="group flex items-center gap-1 rounded px-1.5 py-1 hover:bg-slate-100 dark:hover:bg-slate-800">
                  <Globe className="h-3 w-3 shrink-0 text-violet-500" />
                  <button onClick={() => onOpen(b.url)} className="flex-1 truncate text-left">
                    <span className="block truncate font-medium">{b.title || b.url}</span>
                    <span className="block truncate text-[11px] text-slate-500">{hostOf(b.url)}</span>
                  </button>
                  <button onClick={() => onRemoveBookmark(b.url)}
                    className="opacity-0 group-hover:opacity-100"
                    aria-label="Remove">
                    <X className="h-3 w-3 text-slate-400 hover:text-rose-500" />
                  </button>
                </li>
              ))}
            </ul>
          )}
      </section>
      <section>
        <div className="mb-2 flex items-center justify-between">
          <h4 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            <Clock className="h-3 w-3" /> {t.history}
          </h4>
          {history.length > 0 && (
            <button onClick={onClearHistory} className="text-[10px] text-slate-400 hover:text-rose-500">
              clear
            </button>
          )}
        </div>
        {history.length === 0
          ? <p className="text-xs text-slate-400">—</p>
          : (
            <ul className="space-y-1">
              {history.slice(0, 50).map((h, i) => (
                <li key={`${h.url}_${i}`}>
                  <button onClick={() => onOpen(h.url)}
                    className="flex w-full items-center gap-1 rounded px-1.5 py-1 text-left hover:bg-slate-100 dark:hover:bg-slate-800">
                    <Globe className="h-3 w-3 shrink-0 text-slate-400" />
                    <span className="flex-1 truncate">
                      <span className="block truncate">{h.title || h.url}</span>
                      <span className="block truncate text-[11px] text-slate-500">{hostOf(h.url)}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
      </section>
    </div>
  );
}

// ── EducatorSubmitPanel --------------------------------------------------
// Educators get a self-serve panel to add new domains to the curated
// allowlist. Backed by POST /api/edu/educator/submit-site, which runs a
// kid-safe + robots.txt probe and auto-approves on success. Surfaces
// the probe outcome so the educator knows whether the site is live for
// students or got rejected (and why).
function EducatorSubmitPanel({ open, onClose, lang, onOpenDomain }) {
  const t = T[lang];
  const [domain, setDomain] = useState('');
  const [note, setNote] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null); // {ok, status, domain, detail, error, probe}

  // Reset form on open.
  useEffect(() => {
    if (open) {
      setDomain('');
      setNote('');
      setResult(null);
      setSubmitting(false);
    }
  }, [open]);

  const cleanDomain = (raw) => {
    let s = (raw || '').trim().toLowerCase();
    s = s.replace(/^https?:\/\//, '').replace(/^www\./, '');
    s = s.split('/')[0];
    return s;
  };

  const submit = async (e) => {
    e?.preventDefault?.();
    const d = cleanDomain(domain);
    if (!d || !d.includes('.')) {
      toast.error('Please enter a valid domain (e.g. example.org)');
      return;
    }
    setSubmitting(true);
    setResult(null);
    try {
      const res = await eduEducatorSubmitSite(d, note);
      setResult({ ...(res?.data || {}), httpOk: true });
      const status = res?.data?.status;
      if (status === 'auto_approved') toast.success(t.educatorAutoApproved);
      else if (status === 'already_allowed') toast.success(t.educatorAlreadyAllowed);
    } catch (err) {
      const data = err?.response?.data || {};
      setResult({
        ...data,
        httpOk: false,
        httpStatus: err?.response?.status,
        detail: data.detail || err.message || 'Submission failed',
      });
      if (err?.response?.status === 429) {
        toast.error(data.detail || 'Rate limit reached. Try again later.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  // Friendly mapping for common probe failure reasons.
  const friendlyReason = (code) => {
    if (!code) return null;
    const map = {
      unsafe_content: 'The page contained unsafe or non-kid-safe content.',
      robots_disallow: 'The site\u2019s robots.txt disallows our reader.',
      probe_failed: 'Could not probe this site (network or server error).',
      blocked_admin: 'An admin has blocked this domain.',
      blocked_operator: 'This domain is blocked by site policy.',
      http_error: 'The site returned an HTTP error.',
      not_html: 'The site did not return readable HTML.',
      too_short: 'The page didn\u2019t have enough readable text.',
      ssrf_blocked: 'The URL is not reachable from the public internet.',
    };
    return map[code] || code;
  };

  const renderResult = () => {
    if (!result) return null;
    const status = result.status;
    const reasonCode = result.error || result?.probe?.reason;
    if (status === 'auto_approved' || status === 'already_allowed') {
      return (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 dark:border-emerald-800 dark:bg-emerald-900/30">
          <div className="flex items-start gap-2">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
            <div className="text-sm text-emerald-800 dark:text-emerald-200">
              <p className="font-medium">
                {status === 'auto_approved' ? t.educatorAutoApproved : t.educatorAlreadyAllowed}
              </p>
              {result.probe && (
                <ul className="mt-1 space-y-0.5 text-xs text-emerald-700 dark:text-emerald-300">
                  {typeof result.probe.kid_safe_density === 'number' && (
                    <li>kid-safe density: {Math.round(result.probe.kid_safe_density * 100)}%</li>
                  )}
                  {typeof result.probe.robots_ok === 'boolean' && (
                    <li>robots.txt: {result.probe.robots_ok ? 'allowed' : 'disallowed'}</li>
                  )}
                  {typeof result.probe.http_status === 'number' && (
                    <li>HTTP: {result.probe.http_status}</li>
                  )}
                </ul>
              )}
              {result.domain && (
                <button
                  type="button"
                  onClick={() => { onOpenDomain?.(result.domain); onClose?.(); }}
                  className="mt-2 inline-flex items-center gap-1 rounded-md bg-emerald-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-emerald-700"
                >
                  <ExternalLink className="h-3 w-3" /> {t.educatorOpenNow}
                </button>
              )}
            </div>
          </div>
        </div>
      );
    }
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 dark:border-amber-800 dark:bg-amber-900/30">
        <div className="flex items-start gap-2">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
          <div className="text-sm text-amber-800 dark:text-amber-200">
            <p className="font-medium">{t.educatorRejected}</p>
            {result.detail && (
              <p className="mt-1 text-xs">{result.detail}</p>
            )}
            {reasonCode && (
              <p className="mt-1 text-xs">
                <span className="font-semibold">{t.educatorReason}:</span>{' '}
                <span className="font-mono">{reasonCode}</span>
                {friendlyReason(reasonCode) && (
                  <span className="ml-1">— {friendlyReason(reasonCode)}</span>
                )}
              </p>
            )}
            {result.probe && (
              <ul className="mt-1 space-y-0.5 text-xs">
                {typeof result.probe.kid_safe_density === 'number' && (
                  <li>kid-safe density: {Math.round(result.probe.kid_safe_density * 100)}%</li>
                )}
                {typeof result.probe.robots_ok === 'boolean' && (
                  <li>robots.txt: {result.probe.robots_ok ? 'allowed' : 'disallowed'}</li>
                )}
                {typeof result.probe.http_status === 'number' && (
                  <li>HTTP: {result.probe.http_status}</li>
                )}
              </ul>
            )}
          </div>
        </div>
      </div>
    );
  };

  return (
    <ModalOverlay
      open={open}
      onClose={onClose}
      title={t.educatorSubmitTitle}
      description={t.educatorSubmitSub}
      maxWidth="max-w-md"
    >
      <form onSubmit={submit} className="space-y-3">
        <div>
          <label className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-300">
            {t.educatorDomain}
          </label>
          <input
            type="text"
            value={domain}
            onChange={(e) => setDomain(e.target.value)}
            placeholder={t.educatorDomainPh}
            disabled={submitting}
            autoFocus
            className="w-full rounded-md border border-slate-300 bg-slate-50 px-3 py-2 text-sm focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500 disabled:opacity-60 dark:border-slate-600 dark:bg-slate-900"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-300">
            {t.educatorNote}
          </label>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value.slice(0, 280))}
            placeholder={t.educatorNotePh}
            rows={2}
            disabled={submitting}
            className="w-full resize-none rounded-md border border-slate-300 bg-slate-50 px-3 py-2 text-sm focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500 disabled:opacity-60 dark:border-slate-600 dark:bg-slate-900"
          />
          <p className="mt-1 text-right text-[11px] text-slate-400">{note.length}/280</p>
        </div>
        {renderResult()}
        <div className="flex items-center justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="rounded-md px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100 disabled:opacity-60 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            {t.educatorClose}
          </button>
          <button
            type="submit"
            disabled={submitting || !domain.trim()}
            className="inline-flex items-center gap-1.5 rounded-md bg-violet-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-60"
          >
            {submitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            {submitting ? t.educatorSubmitting : t.educatorSubmitBtn}
          </button>
        </div>
      </form>
    </ModalOverlay>
  );
}

// ── BrowserPage ----------------------------------------------------------
export default function BrowserPage() {
  const navigate = useNavigate();
  const { user, authChecked } = useAuth();
  const { contentLang } = useContentLang();
  const lang = contentLang === 'as' ? 'as' : 'en';
  const t = T[lang];

  const [tabs, setTabs] = useState([blankTab()]);
  const [activeId, setActiveId] = useState(null);
  const [bookmarks, setBookmarks] = useState([]);
  const [history, setHistory] = useState([]);
  const [allowDomains, setAllowDomains] = useState([]);
  const [panelOpen, setPanelOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [educatorOpen, setEducatorOpen] = useState(false);
  // Educator/admin can self-serve add new domains via a dedicated panel.
  // Falls back to the shared 'request a site' flow for everyone else.
  const isEducator = !!(user && (user.role === 'educator' || user.role === 'admin' || user.is_admin));
  const [hydrated, setHydrated] = useState(false);
  const [addressInput, setAddressInput] = useState('');
  // Citations + flash request shared between the side panel and the
  // reader pane so the article can highlight grounding sentences and
  // scroll to them when the user taps a [N] link.
  const [askCitations, setAskCitations] = useState([]);
  const [flashCite, setFlashCite] = useState(null);
  const inputRef = useRef(null);
  const lastSavedRef = useRef('');

  // 1️⃣  Hydrate from localStorage immediately, then attempt server sync.
  useEffect(() => {
    const local = loadLocalState();
    if (local) {
      if (Array.isArray(local.tabs) && local.tabs.length) {
        const restored = local.tabs.map((tt) => ({
          ...blankTab(), ...tt, content: null, loading: false, error: null,
        }));
        setTabs(restored);
        setActiveId(local.activeId && restored.find((x) => x.id === local.activeId)
          ? local.activeId : restored[0].id);
      }
      if (Array.isArray(local.bookmarks)) setBookmarks(local.bookmarks);
      if (Array.isArray(local.history)) setHistory(local.history);
    }
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    if (!activeId && tabs.length) setActiveId(tabs[0].id);
  }, [hydrated, activeId, tabs]);

  // 2️⃣  Server-side state hydration (overrides local if newer).
  useEffect(() => {
    if (!hydrated) return;
    if (!authChecked) return;
    let cancelled = false;
    (async () => {
      try {
        const { data } = await eduLoadState();
        if (cancelled || !data?.state) return;
        const s = data.state;
        if (Array.isArray(s.tabs) && s.tabs.length) {
          const restored = s.tabs.map((tt) => ({
            ...blankTab(), ...tt, content: null, loading: false, error: null,
          }));
          setTabs(restored);
          setActiveId(restored[0].id);
        }
        if (Array.isArray(s.bookmarks)) setBookmarks(s.bookmarks);
        if (Array.isArray(s.history)) setHistory(s.history);
      } catch { /* offline / no mongo — that's OK, localStorage already used */ }
    })();
    return () => { cancelled = true; };
  // user.id intentionally included so a fresh login pulls their state.
  }, [hydrated, authChecked, user?.id]);

  // 3️⃣  Load public allowlist (used for blocked-page suggestions).
  useEffect(() => {
    eduGetAllowlist().then(({ data }) => {
      setAllowDomains(data?.domains || []);
    }).catch(() => {});
  }, []);

  // 4️⃣  Persist (debounced) — both localStorage and server.
  useEffect(() => {
    if (!hydrated) return;
    const slimTabs = tabs.map((tab) => ({
      id: tab.id, title: tab.title, url: tab.url,
      history: (tab.history || []).slice(-20), hIdx: tab.hIdx,
    }));
    const payload = { tabs: slimTabs, activeId, bookmarks, history };
    saveLocalState(payload);
    const json = JSON.stringify(payload);
    if (json === lastSavedRef.current) return;
    lastSavedRef.current = json;
    const handle = setTimeout(() => {
      eduSaveState({ tabs: slimTabs, bookmarks, history }).catch(() => {});
    }, 1500);
    return () => clearTimeout(handle);
  }, [tabs, activeId, bookmarks, history, hydrated]);

  // ── tab helpers ----
  const activeTab = useMemo(
    () => tabs.find((tt) => tt.id === activeId) || null,
    [tabs, activeId],
  );

  useEffect(() => {
    setAddressInput(activeTab?.content?.payload?.url || activeTab?.url || '');
  }, [activeId, activeTab?.url, activeTab?.content?.payload?.url]);

  // Drop the previous answer's grounding highlights when the user
  // switches tab or loads a different article — they belong to the old
  // page and are meaningless against the new one.
  const currentReaderUrl = activeTab?.content?.payload?.url || '';
  useEffect(() => {
    setAskCitations([]);
    setFlashCite(null);
  }, [activeId, currentReaderUrl]);

  const handleCitationClick = useCallback((c) => {
    if (!c) return;
    setFlashCite({ citationIndex: c.index, nonce: Date.now() });
  }, []);

  const handleSpanClick = useCallback((ci) => {
    if (!Number.isFinite(ci)) return;
    setFlashCite({ citationIndex: ci, nonce: Date.now() });
  }, []);

  const updateTab = useCallback((id, patch) => {
    setTabs((prev) => prev.map((tt) => tt.id === id ? { ...tt, ...patch } : tt));
  }, []);

  const openNewTab = useCallback((url = '') => {
    const tab = blankTab();
    if (url) tab.url = url;
    setTabs((prev) => [...prev, tab]);
    setActiveId(tab.id);
    return tab.id;
  }, []);

  // Drag-to-reorder tabs (HTML5 DnD). We keep this trivial: no
  // animation lib, just deterministic swap on drop. Works on
  // desktop pointer + keyboard fallback (Ctrl+Shift+Arrows below).
  const moveTab = useCallback((fromIdx, toIdx) => {
    setTabs((prev) => {
      if (fromIdx === toIdx || fromIdx < 0 || toIdx < 0) return prev;
      if (fromIdx >= prev.length || toIdx >= prev.length) return prev;
      const next = prev.slice();
      const [picked] = next.splice(fromIdx, 1);
      next.splice(toIdx, 0, picked);
      return next;
    });
  }, []);

  const closeTab = useCallback((id) => {
    setTabs((prev) => {
      const idx = prev.findIndex((tt) => tt.id === id);
      if (idx < 0) return prev;
      const next = prev.filter((tt) => tt.id !== id);
      const fallback = next[idx] || next[idx - 1] || null;
      if (id === activeId) setActiveId(fallback ? fallback.id : null);
      return next.length ? next : [blankTab()];
    });
  }, [activeId]);

  const pushHistory = useCallback((tabId, entry) => {
    setTabs((prev) => prev.map((tt) => {
      if (tt.id !== tabId) return tt;
      const trimmed = (tt.history || []).slice(0, (tt.hIdx ?? -1) + 1);
      trimmed.push(entry);
      return { ...tt, history: trimmed.slice(-30), hIdx: trimmed.length - 1, url: entry.url, title: entry.title || tt.title };
    }));
    setHistory((prev) => {
      const filtered = [entry, ...prev.filter((h) => h.url !== entry.url)];
      return filtered.slice(0, MAX_HISTORY_ENTRIES);
    });
  }, []);

  // ── core navigation ----
  const loadUrlIntoTab = useCallback(async (tabId, url, { pushHist = true } = {}) => {
    if (!tabId) tabId = openNewTab();
    updateTab(tabId, { loading: true, error: null, url });
    try {
      const { data } = await eduFetchReader(url);
      if (!data?.ok) {
        updateTab(tabId, {
          loading: false,
          content: { kind: 'blocked', url, reason: data?.reason || 'blocked' },
        });
        return;
      }
      const payload = data;
      updateTab(tabId, {
        loading: false,
        content: { kind: 'reader', payload },
        title: payload.title || hostOf(payload.url) || url,
      });
      if (pushHist) {
        pushHistory(tabId, { url: payload.url || url, title: payload.title || hostOf(payload.url) });
      }
    } catch (e) {
      const status = e?.response?.status;
      const detail = e?.response?.data?.detail || e.message || 'load_failed';
      if (status === 451 || status === 403 || /allow|block/.test(String(detail))) {
        updateTab(tabId, {
          loading: false,
          content: { kind: 'blocked', url, reason: detail },
        });
      } else {
        updateTab(tabId, {
          loading: false,
          error: detail,
          content: { kind: 'error', url, reason: detail },
        });
      }
    }
  }, [openNewTab, updateTab, pushHistory]);

  // ── address bar submit ----
  const submitAddress = useCallback(async (raw) => {
    const value = (raw ?? addressInput).trim();
    if (!value) return;
    if (isLikelyUrl(value)) {
      const url = normalizeUrl(value);
      // Pre-check allowlist so we render the blocked screen without
      // burning a reader-proxy round trip.
      try {
        const { data } = await eduCheckUrl(url);
        if (!data?.allowed) {
          updateTab(activeId, {
            loading: false,
            content: { kind: 'blocked', url, reason: data?.reason || 'blocked' },
            url, title: hostOf(url),
          });
          return;
        }
      } catch { /* fall through to fetch */ }
      await loadUrlIntoTab(activeId, url);
    } else {
      // Natural-language question → hand off to /chat with a prefilled
      // query. /chat already supports the ?q= shortcut.
      navigate(`/chat?q=${encodeURIComponent(value)}`);
    }
  }, [addressInput, activeId, loadUrlIntoTab, navigate, updateTab]);

  // ── back / forward / reload ----
  const goBack = useCallback(() => {
    if (!activeTab) return;
    const idx = activeTab.hIdx ?? -1;
    if (idx <= 0) return;
    const entry = activeTab.history[idx - 1];
    updateTab(activeTab.id, { hIdx: idx - 1 });
    loadUrlIntoTab(activeTab.id, entry.url, { pushHist: false });
  }, [activeTab, updateTab, loadUrlIntoTab]);

  const goForward = useCallback(() => {
    if (!activeTab) return;
    const idx = activeTab.hIdx ?? -1;
    if (idx >= (activeTab.history.length - 1)) return;
    const entry = activeTab.history[idx + 1];
    updateTab(activeTab.id, { hIdx: idx + 1 });
    loadUrlIntoTab(activeTab.id, entry.url, { pushHist: false });
  }, [activeTab, updateTab, loadUrlIntoTab]);

  const reload = useCallback(() => {
    if (!activeTab?.url) return;
    loadUrlIntoTab(activeTab.id, activeTab.url, { pushHist: false });
  }, [activeTab, loadUrlIntoTab]);

  // ── bookmarks ----
  const toggleBookmark = useCallback(() => {
    const url = activeTab?.content?.payload?.url || activeTab?.url;
    if (!url) return;
    setBookmarks((prev) => {
      const has = prev.find((b) => b.url === url);
      if (has) return prev.filter((b) => b.url !== url);
      return [{ url, title: activeTab.title || hostOf(url), at: Date.now() }, ...prev].slice(0, 200);
    });
  }, [activeTab]);

  const isBookmarked = useMemo(() => {
    const url = activeTab?.content?.payload?.url || activeTab?.url;
    return !!url && bookmarks.some((b) => b.url === url);
  }, [bookmarks, activeTab]);

  const removeBookmark = useCallback((url) => {
    setBookmarks((prev) => prev.filter((b) => b.url !== url));
  }, []);

  const openFromList = useCallback((url) => {
    setSidebarOpen(false);
    if (activeTab && !activeTab.url) {
      loadUrlIntoTab(activeTab.id, url);
    } else {
      const id = openNewTab(url);
      loadUrlIntoTab(id, url);
    }
  }, [activeTab, loadUrlIntoTab, openNewTab]);

  // suggestions for blocked screen
  const suggestionDomains = useMemo(() => {
    const start = (allowDomains || []).filter((d) => /khanacademy|britannica|nasa|wikipedia|nationalgeographic|ck12|byjus|edx|coursera/.test(d));
    return start.length ? start : (allowDomains || []).slice(0, 6);
  }, [allowDomains]);

  // ── render ----
  return (
    <AppLayout>
      <title>{t.title} — Syrabit</title>
      <meta name="description" content="Curated educational web browser with reader mode and an AI study companion." />

      <div className="flex h-[calc(100vh-4rem)] flex-col bg-slate-50 dark:bg-slate-950">
        {/* Tab strip */}
        <div className="flex shrink-0 items-end gap-1 overflow-x-auto border-b border-slate-200 bg-slate-100 px-2 pt-2 dark:border-slate-800 dark:bg-slate-900">
          <button onClick={() => setSidebarOpen((v) => !v)}
            className="mb-1 mr-1 rounded p-1.5 text-slate-500 hover:bg-slate-200 lg:hidden dark:hover:bg-slate-800"
            aria-label="Toggle bookmarks">
            <Menu className="h-4 w-4" />
          </button>
          {tabs.map((tab, idx) => (
            <div
              key={tab.id}
              draggable
              onClick={() => setActiveId(tab.id)}
              onDragStart={(e) => {
                e.dataTransfer.setData('text/plain', String(idx));
                e.dataTransfer.effectAllowed = 'move';
              }}
              onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; }}
              onDrop={(e) => {
                e.preventDefault();
                const fromIdx = parseInt(e.dataTransfer.getData('text/plain'), 10);
                if (Number.isFinite(fromIdx)) moveTab(fromIdx, idx);
              }}
              onKeyDown={(e) => {
                // Keyboard reorder: Ctrl/Cmd + Shift + Arrow Left/Right
                if ((e.ctrlKey || e.metaKey) && e.shiftKey) {
                  if (e.key === 'ArrowLeft') { e.preventDefault(); moveTab(idx, idx - 1); }
                  if (e.key === 'ArrowRight') { e.preventDefault(); moveTab(idx, idx + 1); }
                }
              }}
              tabIndex={0}
              role="tab"
              aria-selected={tab.id === activeId}
              className={[
                'group flex max-w-[180px] cursor-pointer items-center gap-1.5 rounded-t-md border border-b-0 px-2.5 py-1.5 text-xs',
                tab.id === activeId
                  ? 'border-slate-200 bg-white text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100'
                  : 'border-transparent text-slate-500 hover:bg-white/60 dark:text-slate-400 dark:hover:bg-slate-800',
              ].join(' ')}
            >
              {tab.loading ? <Loader2 className="h-3 w-3 shrink-0 animate-spin" /> : <Globe className="h-3 w-3 shrink-0 text-slate-400" />}
              <span className="truncate">{tab.title || hostOf(tab.url) || t.blank}</span>
              <button
                onClick={(e) => { e.stopPropagation(); closeTab(tab.id); }}
                className="opacity-0 group-hover:opacity-100"
                aria-label="Close tab"
              >
                <X className="h-3 w-3 text-slate-400 hover:text-rose-500" />
              </button>
            </div>
          ))}
          <button
            onClick={() => openNewTab()}
            className="mb-1 ml-0.5 rounded p-1.5 text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-800"
            aria-label={t.newTab}
          >
            <Plus className="h-4 w-4" />
          </button>
        </div>

        {/* Toolbar */}
        <div className="flex shrink-0 items-center gap-1 border-b border-slate-200 bg-white px-2 py-1.5 dark:border-slate-800 dark:bg-slate-900">
          <button onClick={goBack}
            disabled={!activeTab || (activeTab.hIdx ?? -1) <= 0}
            className="rounded p-1.5 text-slate-600 hover:bg-slate-100 disabled:opacity-30 dark:text-slate-300 dark:hover:bg-slate-800"
            aria-label={t.back}><ArrowLeft className="h-4 w-4" /></button>
          <button onClick={goForward}
            disabled={!activeTab || (activeTab.hIdx ?? -1) >= ((activeTab?.history?.length || 0) - 1)}
            className="rounded p-1.5 text-slate-600 hover:bg-slate-100 disabled:opacity-30 dark:text-slate-300 dark:hover:bg-slate-800"
            aria-label={t.forward}><ArrowRight className="h-4 w-4" /></button>
          <button onClick={reload}
            disabled={!activeTab?.url}
            className="rounded p-1.5 text-slate-600 hover:bg-slate-100 disabled:opacity-30 dark:text-slate-300 dark:hover:bg-slate-800"
            aria-label={t.reload}><RotateCw className={`h-4 w-4 ${activeTab?.loading ? 'animate-spin' : ''}`} /></button>

          <form className="flex flex-1 items-center" onSubmit={(e) => { e.preventDefault(); submitAddress(); }}>
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
              <input
                ref={inputRef}
                value={addressInput}
                onChange={(e) => setAddressInput(e.target.value)}
                onFocus={(e) => e.target.select()}
                placeholder={t.addressPh}
                className="w-full rounded-full border border-slate-300 bg-slate-50 py-1.5 pl-8 pr-3 text-sm focus:border-violet-500 focus:bg-white focus:outline-none focus:ring-1 focus:ring-violet-500 dark:border-slate-700 dark:bg-slate-800 dark:focus:bg-slate-900"
                aria-label={t.addressPh}
              />
            </div>
          </form>

          <button onClick={toggleBookmark}
            disabled={!activeTab?.url}
            title={isBookmarked ? t.bookmarked : t.bookmark}
            className={`rounded p-1.5 hover:bg-slate-100 disabled:opacity-30 dark:hover:bg-slate-800
              ${isBookmarked ? 'text-amber-500' : 'text-slate-500 dark:text-slate-400'}`}
            aria-label={t.bookmark}
          >
            <Star className={`h-4 w-4 ${isBookmarked ? 'fill-current' : ''}`} />
          </button>

          {isEducator && (
            <button onClick={() => setEducatorOpen(true)}
              title={t.educatorSubmit}
              aria-label={t.educatorSubmit}
              className="inline-flex items-center gap-1 rounded p-1.5 text-violet-600 hover:bg-violet-50 dark:text-violet-300 dark:hover:bg-violet-900/30"
            >
              <GraduationCap className="h-4 w-4" />
              <span className="hidden text-xs font-medium sm:inline">{t.educatorSubmit}</span>
            </button>
          )}

          <button onClick={() => setPanelOpen((v) => !v)}
            className="rounded p-1.5 text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
            aria-label={panelOpen ? t.closePanel : t.openPanel}>
            {panelOpen ? <PanelRightClose className="h-4 w-4" /> : <PanelRightOpen className="h-4 w-4" />}
          </button>
        </div>

        {/* Body: sidebar + content + side panel */}
        <div className="flex flex-1 overflow-hidden">
          {/* Bookmarks sidebar (lg+ visible, mobile drawer) */}
          <div className={`
            ${sidebarOpen ? 'absolute inset-y-0 left-0 z-30 w-72 shadow-xl' : 'hidden'}
            border-r border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900
            lg:static lg:z-0 lg:flex lg:w-60 lg:shadow-none
          `}>
            <BookmarksPane
              bookmarks={bookmarks}
              history={history}
              onOpen={openFromList}
              onRemoveBookmark={removeBookmark}
              onClearHistory={() => setHistory([])}
              lang={lang}
            />
          </div>
          {sidebarOpen && (
            <div className="absolute inset-0 z-20 bg-black/30 lg:hidden"
              onClick={() => setSidebarOpen(false)} />
          )}

          {/* Reader pane */}
          <main className="relative flex-1 overflow-y-auto bg-white dark:bg-slate-950">
            {!activeTab && (
              <div className="flex h-full items-center justify-center text-slate-400">{t.empty}</div>
            )}
            {activeTab?.loading && !activeTab?.content && (
              <div className="flex h-full items-center justify-center text-slate-500">
                <Loader2 className="mr-2 h-5 w-5 animate-spin" /> {t.loading}
              </div>
            )}
            {activeTab && !activeTab.loading && !activeTab.content && (
              <StartScreen
                allowDomains={allowDomains}
                onOpen={(u) => loadUrlIntoTab(activeTab.id, u)}
                onFocusAddress={() => inputRef.current?.focus()}
                lang={lang}
              />
            )}
            {activeTab?.content?.kind === 'reader' && (
              <ReaderArticle
                payload={activeTab.content.payload}
                lang={lang}
                citations={askCitations}
                flashCite={flashCite}
                onSpanClick={handleSpanClick}
              />
            )}
            {activeTab?.content?.kind === 'blocked' && (
              <BlockedView
                url={activeTab.content.url}
                suggestions={suggestionDomains}
                onOpenSuggestion={(u) => loadUrlIntoTab(activeTab.id, u)}
                lang={lang}
              />
            )}
            {activeTab?.content?.kind === 'error' && (
              <div className="mx-auto max-w-md px-6 py-12 text-center">
                <p className="mb-2 text-lg font-semibold">{t.failed}</p>
                <p className="text-sm text-slate-500">{activeTab.content.reason}</p>
                <button onClick={reload}
                  className="mt-4 rounded-md bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-700">
                  {t.reload}
                </button>
              </div>
            )}
          </main>

          {/* Side panel (Ask Syra) */}
          {panelOpen && (
            <div className="hidden w-[360px] shrink-0 md:block">
              <AskSyraPanel
                activeTab={activeTab}
                lang={lang}
                onClose={() => setPanelOpen(false)}
                onCitationsChange={setAskCitations}
                onCitationClick={handleCitationClick}
              />
            </div>
          )}
          {panelOpen && (
            <div className="absolute inset-y-0 right-0 z-30 w-full max-w-sm bg-white shadow-2xl md:hidden dark:bg-slate-900">
              <AskSyraPanel
                activeTab={activeTab}
                lang={lang}
                onClose={() => setPanelOpen(false)}
                onCitationsChange={setAskCitations}
                onCitationClick={handleCitationClick}
              />
            </div>
          )}
        </div>
      </div>
      <HighlightSavePopover sourceUrl={activeTab?.url || ''} sourceTitle={activeTab?.title || ''} />
      {isEducator && (
        <EducatorSubmitPanel
          open={educatorOpen}
          onClose={() => setEducatorOpen(false)}
          lang={lang}
          onOpenDomain={(d) => {
            const url = `https://${d}`;
            if (activeTab && !activeTab.url) {
              loadUrlIntoTab(activeTab.id, url);
            } else {
              const id = openNewTab(url);
              loadUrlIntoTab(id, url);
            }
          }}
        />
      )}
    </AppLayout>
  );
}

// ── StartScreen ----------------------------------------------------------
function StartScreen({ allowDomains, onOpen, onFocusAddress, lang }) {
  const t = T[lang];
  const featured = useMemo(() => {
    const order = ['khanacademy.org', 'en.wikipedia.org', 'britannica.com',
      'nasa.gov', 'nationalgeographic.com', 'ck12.org', 'edx.org', 'coursera.org',
      'mathigon.org', 'phet.colorado.edu'];
    const set = new Set(allowDomains || []);
    return order.filter((d) => set.has(d) || (allowDomains || []).includes(d));
  }, [allowDomains]);
  return (
    <div className="mx-auto flex max-w-2xl flex-col items-center px-6 py-16 text-center">
      <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-gradient-to-br from-violet-500 to-fuchsia-500 text-white">
        <Sparkles className="h-6 w-6" />
      </div>
      <h2 className="mb-1 text-2xl font-bold text-slate-900 dark:text-slate-50">{t.title}</h2>
      <p className="mb-6 max-w-md text-sm text-slate-500">
        {lang === 'as'
          ? 'কিউৰেট কৰা শিক্ষাগত ছাইটসমূহ পঢ়ক, প্ৰশ্ন সোধক, আৰু সাৰাংশ পাওক।'
          : 'Read curated educational sites in distraction-free mode, then ask Syra anything about what you’re reading.'}
      </p>
      <button
        onClick={onFocusAddress}
        className="mb-8 inline-flex items-center gap-2 rounded-full bg-violet-600 px-5 py-2 text-sm font-medium text-white shadow hover:bg-violet-700"
      >
        <Search className="h-4 w-4" /> {t.addressPh}
      </button>
      {featured.length > 0 && (
        <div className="w-full">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
            {t.suggested}
          </p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {featured.slice(0, 9).map((d) => (
              <button key={d} onClick={() => onOpen(`https://${d}`)}
                className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-left text-sm transition hover:border-violet-400 hover:bg-violet-50 dark:border-slate-700 dark:bg-slate-800 dark:hover:bg-slate-700">
                <Globe className="h-4 w-4 text-violet-500" />
                <span className="truncate">{d}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
