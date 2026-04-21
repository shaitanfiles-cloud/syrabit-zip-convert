/**
 * NotebookPage — saved highlights from chapters, reader, and chat,
 * plus NotebookLM-style AI-generated notes (Task #641).
 *
 * Lets the learner search, filter by tag, edit, delete, export their
 * notes (markdown / CSV), and generate structured study notes with
 * citations from a chat conversation, a chapter, or saved highlights.
 */
import { useEffect, useMemo, useState, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import {
  Search, Tag as TagIcon, Trash2, Download, ExternalLink,
  Loader2, NotebookPen, Pencil, Check, X, Sparkles, Wand2,
  BookOpen, MessageSquare, ListChecks, AlertCircle,
} from 'lucide-react';
import { AppLayout } from '@/components/layout/AppLayout';
import { PageTitle } from '@/components/PageTitle';
import { studyApi } from '@/utils/studyApi';
import PinResetBanner from '@/components/PinResetBanner';
import { getClaimSeenAt, markClaimSeen, isRecentlyClaimed } from '@/utils/claimSeen';
import { toast } from 'sonner';

/* ─────────────── URL safety ───────────────
 * Only allow http(s) absolute URLs or app-internal paths starting with "/".
 * Blocks javascript:/data:/vbscript: schemes that could fire on click. */
function safeHref(url) {
  if (!url || typeof url !== 'string') return '';
  const u = url.trim();
  if (!u) return '';
  if (u.startsWith('/') && !u.startsWith('//')) return u;
  if (/^https?:\/\//i.test(u)) return u;
  return '';
}

/* ─────────────── Citation chip ─────────────── */

function CitationChip({ id, citationsMap }) {
  const c = citationsMap[id];
  const label = c?.label || id;
  const url = safeHref(c?.url);
  const isInternal = url && url.startsWith('/');
  const className =
    'inline-flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded ' +
    'bg-primary/10 text-primary border border-primary/20 hover:bg-primary/20 transition';
  if (!url) {
    return <span className={className} title={label}>[{id}]</span>;
  }
  if (isInternal) {
    return (
      <Link to={url} className={className} title={label}>[{id}]</Link>
    );
  }
  return (
    <a href={url} target="_blank" rel="noreferrer" className={className} title={label}>
      [{id}]
    </a>
  );
}

function CitationList({ ids, citationsMap }) {
  if (!ids?.length) return null;
  return (
    <span className="ml-1 inline-flex flex-wrap gap-1 align-middle">
      {ids.map((cid) => (
        <CitationChip key={cid} id={cid} citationsMap={citationsMap} />
      ))}
    </span>
  );
}

/* ─────────────── Structured AI note body ─────────────── */

function StructuredNoteBody({ structured, citations }) {
  const cmap = useMemo(() => {
    const m = {};
    (citations || []).forEach((c) => { if (c?.id) m[c.id] = c; });
    return m;
  }, [citations]);

  if (!structured) return null;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <span className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full bg-violet-500/10 text-violet-700 dark:text-violet-300 border border-violet-500/20">
          <Wand2 className="w-3 h-3" /> AI generated
        </span>
        {structured.title && (
          <h3 className="text-base font-semibold leading-snug truncate">{structured.title}</h3>
        )}
      </div>

      {structured.summary && (
        <p className="text-sm text-muted-foreground leading-relaxed">{structured.summary}</p>
      )}

      {(structured.outline || []).map((sec, i) => (
        <section key={i} className="space-y-1.5">
          <h4 className="text-sm font-semibold flex items-center gap-1 flex-wrap">
            <span>{sec.heading}</span>
            <CitationList ids={sec.citations} citationsMap={cmap} />
          </h4>
          <ul className="text-sm leading-relaxed space-y-1 list-disc pl-5">
            {(sec.points || []).map((p, j) => (
              <li key={j}>{p}</li>
            ))}
          </ul>
        </section>
      ))}

      {structured.key_terms?.length > 0 && (
        <section className="space-y-1.5">
          <h4 className="text-sm font-semibold">Key terms</h4>
          <dl className="text-sm space-y-1">
            {structured.key_terms.map((kt, i) => (
              <div key={i} className="flex flex-wrap items-baseline gap-1">
                <dt className="font-semibold">{kt.term}:</dt>
                <dd className="text-muted-foreground">{kt.definition}</dd>
                <CitationList ids={kt.citations} citationsMap={cmap} />
              </div>
            ))}
          </dl>
        </section>
      )}

      {structured.qa?.length > 0 && (
        <section className="space-y-2">
          <h4 className="text-sm font-semibold">Q&amp;A</h4>
          <div className="space-y-2">
            {structured.qa.map((qa, i) => (
              <div key={i} className="rounded-lg border border-border/50 p-2.5 bg-muted/30">
                <div className="text-sm font-medium flex flex-wrap items-baseline gap-1">
                  Q: {qa.q}
                  <CitationList ids={qa.citations} citationsMap={cmap} />
                </div>
                <div className="text-sm text-muted-foreground mt-1">A: {qa.a}</div>
              </div>
            ))}
          </div>
        </section>
      )}

      {citations?.length > 0 && (
        <details className="text-xs text-muted-foreground border-t border-border/40 pt-2">
          <summary className="cursor-pointer hover:text-foreground">
            Sources ({citations.length})
          </summary>
          <ul className="mt-2 space-y-1">
            {citations.map((c) => {
              const safe = safeHref(c.url);
              return (
                <li key={c.id} className="flex items-center gap-1.5">
                  <span className="font-mono">[{c.id}]</span>
                  {safe ? (
                    safe.startsWith('/') ? (
                      <Link to={safe} className="hover:underline truncate">{c.label}</Link>
                    ) : (
                      <a href={safe} target="_blank" rel="noreferrer"
                         className="hover:underline truncate">{c.label}</a>
                    )
                  ) : (
                    <span className="truncate">{c.label}</span>
                  )}
                </li>
              );
            })}
          </ul>
        </details>
      )}
    </div>
  );
}

/* ─────────────── Note card ─────────────── */

function NoteCard({ note, onChange, onDelete, recentlySynced, selected, onToggleSelect }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(note.text);
  const [tags, setTags] = useState((note.tags || []).join(', '));
  const [saving, setSaving] = useState(false);
  const isGenerated = !!note.generated && !!note.structured;

  const save = async () => {
    setSaving(true);
    try {
      const tagArr = tags.split(',').map(t => t.trim()).filter(Boolean);
      // Generated notes render the structured body, not `text`. Editing
      // `text` here would be invisible to the user, so only patch tags.
      const patch = isGenerated ? { tags: tagArr } : { text, tags: tagArr };
      const updated = await studyApi.patchNote(note.id, patch);
      onChange(updated);
      setEditing(false);
    } catch (e) {
      toast.error(e.message || 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  return (
    <article className="rounded-2xl border border-border/60 bg-card p-4 shadow-sm">
      {editing ? (
        <>
          {isGenerated ? (
            <p className="text-xs text-muted-foreground italic mb-2">
              AI-generated content is read-only. You can still edit tags below.
            </p>
          ) : (
            <textarea
              value={text} onChange={(e) => setText(e.target.value)}
              rows={4}
              className="w-full text-sm rounded-lg border border-border/60 p-2 bg-background mb-2 font-mono"
            />
          )}
          <input
            value={tags} onChange={(e) => setTags(e.target.value)}
            placeholder="Tags (comma-separated)"
            className="w-full text-xs rounded-lg border border-border/60 px-2 py-1.5 bg-background mb-2"
          />
        </>
      ) : (
        <>
          {recentlySynced && (
            <div className="mb-2 inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border border-emerald-500/20">
              <Sparkles className="w-3 h-3" /> Recently synced
            </div>
          )}
          {isGenerated ? (
            <StructuredNoteBody structured={note.structured} citations={note.citations} />
          ) : (
            <p className="text-sm leading-relaxed whitespace-pre-wrap">{note.text}</p>
          )}
          {note.tags?.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {note.tags.map((t) => (
                <span key={t} className="text-[11px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                  #{t}
                </span>
              ))}
            </div>
          )}
        </>
      )}

      <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
        <div className="flex items-center gap-2 min-w-0">
          {onToggleSelect && !isGenerated && (
            <label className="inline-flex items-center gap-1 cursor-pointer select-none">
              <input
                type="checkbox" checked={!!selected}
                onChange={() => onToggleSelect(note.id)}
                className="h-3.5 w-3.5"
              />
              <span className="text-[10px]">use as source</span>
            </label>
          )}
          {(() => {
            const safe = safeHref(note.source_url);
            const label = note.source_title || safe || '';
            if (safe) {
              return safe.startsWith('/') ? (
                <Link to={safe}
                      className="inline-flex items-center gap-1 hover:underline truncate max-w-[260px]">
                  <ExternalLink className="w-3 h-3 shrink-0" />
                  <span className="truncate">{label}</span>
                </Link>
              ) : (
                <a href={safe} target="_blank" rel="noreferrer"
                   className="inline-flex items-center gap-1 hover:underline truncate max-w-[260px]">
                  <ExternalLink className="w-3 h-3 shrink-0" />
                  <span className="truncate">{label}</span>
                </a>
              );
            }
            if (note.chapter_ref) return <span className="truncate">{note.chapter_ref}</span>;
            return <span>Saved</span>;
          })()}
        </div>
        <div className="flex items-center gap-1">
          {editing ? (
            <>
              <button onClick={save} disabled={saving}
                      className="p-1.5 rounded hover:bg-muted text-emerald-600">
                {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
              </button>
              <button onClick={() => { setEditing(false); setText(note.text); }}
                      className="p-1.5 rounded hover:bg-muted">
                <X className="w-3.5 h-3.5" />
              </button>
            </>
          ) : (
            <>
              <button onClick={() => setEditing(true)} className="p-1.5 rounded hover:bg-muted">
                <Pencil className="w-3.5 h-3.5" />
              </button>
              <button onClick={() => onDelete(note.id)} className="p-1.5 rounded hover:bg-muted text-red-600">
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </>
          )}
        </div>
      </div>
    </article>
  );
}

/* ─────────────── Generate-with-AI modal ─────────────── */

const SOURCE_TABS = [
  { key: 'conversation', label: 'Recent chat', icon: MessageSquare },
  { key: 'chapter',      label: 'Chapter',     icon: BookOpen },
  { key: 'highlights',   label: 'Highlights',  icon: ListChecks },
];

function GenerateNotesModal({ open, onClose, onGenerated, selectedNoteIds, allNotes }) {
  const [tab, setTab] = useState('conversation');
  const [convs, setConvs] = useState(null);   // null = unloaded, [] = empty
  const [loadingConvs, setLoadingConvs] = useState(false);
  const [convErr, setConvErr] = useState('');
  const [convId, setConvId] = useState('');
  const [chapterId, setChapterId] = useState('');
  const [focus, setFocus] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  useEffect(() => {
    if (!open) return;
    setErr('');
    if (tab === 'conversation' && convs === null && !loadingConvs) {
      setLoadingConvs(true);
      studyApi.listMyConversations()
        .then((r) => {
          const list = Array.isArray(r) ? r : (r?.conversations || []);
          setConvs(list.slice(0, 50));
          if (list[0]) setConvId(list[0].id);
        })
        .catch((e) => {
          if (e.status === 401) {
            setConvErr('Sign in to use a chat conversation as a source.');
          } else {
            setConvErr(e.message || 'Could not load chats');
          }
          setConvs([]);
        })
        .finally(() => setLoadingConvs(false));
    }
  }, [open, tab]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!open) return null;

  const submit = async () => {
    setErr('');
    let payload = {
      source_kind: tab,
      response_lang: 'en',
      custom_focus: focus.trim().slice(0, 300),
    };
    if (tab === 'conversation') {
      if (!convId) { setErr('Pick a conversation.'); return; }
      payload.source_id = convId;
    } else if (tab === 'chapter') {
      if (!chapterId.trim()) {
        setErr('Paste a chapter id (you can find it on the chapter page URL).');
        return;
      }
      payload.source_id = chapterId.trim();
    } else if (tab === 'highlights') {
      const ids = (selectedNoteIds || []).filter(
        (id) => !allNotes.find((n) => n.id === id && n.generated),
      );
      if (!ids.length) {
        setErr('Tick the “use as source” boxes on at least one manual highlight first.');
        return;
      }
      payload.note_ids = ids.slice(0, 30);
    }
    setBusy(true);
    try {
      const r = await studyApi.generateNotes(payload);
      onGenerated(r.note);
      toast.success('Generated note saved.');
      onClose();
    } catch (e) {
      // Surface the backend's clear message — Gemini-only path means we
      // never silently fall back to another model.
      const msg = e?.detail?.message || e.message || 'Generation failed';
      setErr(msg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4"
         onClick={onClose}>
      <div className="bg-card border border-border/60 rounded-2xl w-full max-w-lg shadow-xl"
           onClick={(e) => e.stopPropagation()}>
        <header className="flex items-center justify-between px-5 py-3 border-b border-border/50">
          <h2 className="font-semibold text-base inline-flex items-center gap-2">
            <Wand2 className="w-4 h-4 text-primary" />
            Generate notes with AI
          </h2>
          <button onClick={onClose} className="p-1.5 rounded hover:bg-muted">
            <X className="w-4 h-4" />
          </button>
        </header>

        <div className="px-5 py-4 space-y-4">
          <p className="text-xs text-muted-foreground">
            Notes are generated by Google Gemini using only the source you pick —
            with citations back to each chat message, chapter section, or highlight.
          </p>

          <div className="flex gap-1 rounded-xl bg-muted p-1">
            {SOURCE_TABS.map(({ key, label, icon: Icon }) => (
              <button
                key={key}
                onClick={() => { setTab(key); setErr(''); }}
                className={
                  'flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition ' +
                  (tab === key ? 'bg-background shadow-sm' : 'text-muted-foreground hover:text-foreground')
                }
              >
                <Icon className="w-3.5 h-3.5" /> {label}
              </button>
            ))}
          </div>

          {tab === 'conversation' && (
            <div className="space-y-1.5">
              <label className="text-xs font-medium">Pick a chat</label>
              {loadingConvs ? (
                <div className="text-xs text-muted-foreground inline-flex items-center gap-1">
                  <Loader2 className="w-3 h-3 animate-spin" /> Loading chats…
                </div>
              ) : convErr ? (
                <div className="text-xs text-amber-600 inline-flex items-center gap-1">
                  <AlertCircle className="w-3 h-3" /> {convErr}
                </div>
              ) : (convs || []).length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No chat history yet. Try the chapter or highlights tabs.
                </p>
              ) : (
                <select
                  value={convId} onChange={(e) => setConvId(e.target.value)}
                  className="w-full text-sm rounded-lg border border-border/60 bg-background px-3 py-2"
                >
                  {convs.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.title || 'Untitled chat'}
                    </option>
                  ))}
                </select>
              )}
            </div>
          )}

          {tab === 'chapter' && (
            <div className="space-y-1.5">
              <label className="text-xs font-medium">Chapter id</label>
              <input
                value={chapterId}
                onChange={(e) => setChapterId(e.target.value)}
                placeholder="e.g. ch_abc123 (open a chapter and copy from URL/admin)"
                className="w-full text-sm rounded-lg border border-border/60 bg-background px-3 py-2 font-mono"
              />
              <p className="text-[11px] text-muted-foreground">
                Tip: open the chapter in the library, then copy its id from the address bar.
              </p>
            </div>
          )}

          {tab === 'highlights' && (
            <div className="space-y-1.5">
              <label className="text-xs font-medium">
                Selected highlights: {selectedNoteIds?.length || 0}
              </label>
              <p className="text-[11px] text-muted-foreground">
                Tick the “use as source” checkbox on any manual highlight in the list
                below the modal, then come back here.
              </p>
            </div>
          )}

          <div className="space-y-1.5">
            <label className="text-xs font-medium">Focus (optional)</label>
            <input
              value={focus} onChange={(e) => setFocus(e.target.value)}
              placeholder="e.g. only the photosynthesis equations"
              className="w-full text-sm rounded-lg border border-border/60 bg-background px-3 py-2"
            />
          </div>

          {err && (
            <div className="text-xs text-red-600 inline-flex items-start gap-1">
              <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
              <span>{err}</span>
            </div>
          )}
        </div>

        <footer className="flex justify-end gap-2 px-5 py-3 border-t border-border/50">
          <button
            onClick={onClose}
            className="text-sm px-3 py-2 rounded-xl hover:bg-muted"
          >
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={busy}
            className="inline-flex items-center gap-1.5 text-sm font-medium px-3 py-2 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
          >
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wand2 className="w-4 h-4" />}
            Generate
          </button>
        </footer>
      </div>
    </div>
  );
}

/* ─────────────── Page ─────────────── */

export default function NotebookPage() {
  const [notes, setNotes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState('');
  const [tag, setTag] = useState('');
  const [building, setBuilding] = useState(false);
  const [genOpen, setGenOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState([]);
  // Snapshot the per-surface high-water mark at mount so the badge
  // stays visible the entire time the page is open.
  const [seenAt] = useState(() => getClaimSeenAt('notes'));
  const maxClaimedRef = useRef('');

  const load = useCallback(() => {
    setLoading(true);
    studyApi.listNotes({ q, tag, limit: 200 })
      .then((r) => setNotes(r.notes || []))
      .catch((e) => toast.error(e.message || 'Failed to load notes'))
      .finally(() => setLoading(false));
  }, [q, tag]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const m = notes.reduce(
      (acc, n) => (n.claimed_at && n.claimed_at > acc ? n.claimed_at : acc),
      maxClaimedRef.current);
    maxClaimedRef.current = m;
  }, [notes]);

  useEffect(() => () => {
    if (maxClaimedRef.current) markClaimSeen('notes', maxClaimedRef.current);
  }, []);

  const allTags = useMemo(() => {
    const s = new Set();
    notes.forEach(n => (n.tags || []).forEach(t => s.add(t)));
    return Array.from(s).sort();
  }, [notes]);

  const onDelete = async (id) => {
    setNotes((n) => n.filter(x => x.id !== id));
    setSelectedIds((s) => s.filter((sid) => sid !== id));
    try { await studyApi.deleteNote(id); toast.success('Deleted'); }
    catch (e) { toast.error(e.message || 'Delete failed'); load(); }
  };

  const onChange = (updated) => {
    // The patch endpoint currently returns {ok, note}; older callers may
    // have returned the bare row. Handle both.
    const next = updated?.note || updated;
    setNotes((n) => n.map(x => x.id === next.id ? { ...x, ...next } : x));
  };

  const onGenerated = (note) => {
    setNotes((n) => [note, ...n]);
  };

  const toggleSelect = (id) => {
    setSelectedIds((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  };

  const buildCards = async () => {
    setBuilding(true);
    try {
      const r = await studyApi.buildFlashcards();
      toast.success(`Created ${r.created || 0} flashcards`);
    } catch (e) { toast.error(e.message || 'Could not build flashcards'); }
    finally { setBuilding(false); }
  };

  return (
    <AppLayout>
      <PageTitle title="Notebook · Syrabit.ai" />
      <div className="max-w-4xl mx-auto px-4 py-6">
        <div className="mb-3"><PinResetBanner /></div>
        <header className="flex flex-wrap items-start justify-between gap-3 mb-5">
          <div>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <NotebookPen className="w-6 h-6 text-primary" />
              Notebook
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              Highlights you saved + AI-generated study notes from your own chats and chapters.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => setGenOpen(true)}
              className="inline-flex items-center gap-1.5 text-sm px-3 py-2 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90"
            >
              <Wand2 className="w-4 h-4" />
              Generate with AI
            </button>
            <button
              onClick={buildCards}
              disabled={building || notes.length === 0}
              className="inline-flex items-center gap-1.5 text-sm px-3 py-2 rounded-xl border border-border/60 hover:bg-muted disabled:opacity-50"
            >
              {building ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
              Build flashcards
            </button>
            <a
              href={studyApi.exportNotesUrl('md')}
              className="inline-flex items-center gap-1.5 text-sm px-3 py-2 rounded-xl border border-border/60 hover:bg-muted"
            >
              <Download className="w-4 h-4" /> .md
            </a>
            <a
              href={studyApi.exportNotesUrl('csv')}
              className="inline-flex items-center gap-1.5 text-sm px-3 py-2 rounded-xl border border-border/60 hover:bg-muted"
            >
              <Download className="w-4 h-4" /> .csv
            </a>
          </div>
        </header>

        <div className="flex flex-col sm:flex-row gap-2 mb-4">
          <div className="relative flex-1">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input
              value={q} onChange={(e) => setQ(e.target.value)}
              placeholder="Search notes…"
              className="w-full pl-9 pr-3 py-2 rounded-xl border border-border/60 bg-background text-sm"
            />
          </div>
          <select
            value={tag} onChange={(e) => setTag(e.target.value)}
            className="px-3 py-2 rounded-xl border border-border/60 bg-background text-sm"
          >
            <option value="">All tags</option>
            {allTags.map(t => <option key={t} value={t}>#{t}</option>)}
          </select>
        </div>

        {selectedIds.length > 0 && (
          <div className="mb-3 inline-flex items-center gap-2 text-xs text-muted-foreground">
            <TagIcon className="w-3 h-3" />
            {selectedIds.length} highlight{selectedIds.length === 1 ? '' : 's'} selected as source.
            <button
              onClick={() => setSelectedIds([])}
              className="underline hover:text-foreground"
            >
              clear
            </button>
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center py-20 text-muted-foreground">
            <Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading notes…
          </div>
        ) : notes.length === 0 ? (
          <div className="text-center py-16 border border-dashed border-border/60 rounded-2xl">
            <NotebookPen className="w-10 h-10 mx-auto mb-3 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              No notes yet. Highlight any text in a chapter or article and tap <em>Save</em>,
              or generate a structured note from a chat or chapter.
            </p>
            <div className="mt-3 flex justify-center gap-2">
              <Link to="/library" className="inline-block text-sm font-medium text-primary hover:underline">
                Browse the library →
              </Link>
              <button
                onClick={() => setGenOpen(true)}
                className="text-sm font-medium text-primary hover:underline"
              >
                Generate with AI →
              </button>
            </div>
          </div>
        ) : (
          <div className="grid gap-3">
            {notes.map((n) => (
              <NoteCard
                key={n.id} note={n} onChange={onChange} onDelete={onDelete}
                recentlySynced={isRecentlyClaimed(n.claimed_at, seenAt)}
                selected={selectedIds.includes(n.id)}
                onToggleSelect={toggleSelect}
              />
            ))}
          </div>
        )}
      </div>

      <GenerateNotesModal
        open={genOpen}
        onClose={() => setGenOpen(false)}
        onGenerated={onGenerated}
        selectedNoteIds={selectedIds}
        allNotes={notes}
      />
    </AppLayout>
  );
}
