/**
 * NotebookPage — saved highlights from chapters, reader, and chat.
 *
 * Lets the learner search, filter by tag, edit, delete, and export their
 * notes (markdown / CSV). Each note links back to its source page.
 */
import { useEffect, useMemo, useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import {
  Search, Tag as TagIcon, Trash2, Download, ExternalLink,
  Loader2, NotebookPen, Pencil, Check, X, Sparkles,
} from 'lucide-react';
import { AppLayout } from '@/components/layout/AppLayout';
import { PageTitle } from '@/components/PageTitle';
import { studyApi } from '@/utils/studyApi';
import PinResetBanner from '@/components/PinResetBanner';
import { getClaimSeenAt, markClaimSeen, isRecentlyClaimed } from '@/utils/claimSeen';
import { toast } from 'sonner';

function NoteCard({ note, onChange, onDelete, recentlySynced }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(note.text);
  const [tags, setTags] = useState((note.tags || []).join(', '));
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      const tagArr = tags.split(',').map(t => t.trim()).filter(Boolean);
      const updated = await studyApi.patchNote(note.id, { text, tags: tagArr });
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
          <textarea
            value={text} onChange={(e) => setText(e.target.value)}
            rows={4}
            className="w-full text-sm rounded-lg border border-border/60 p-2 bg-background mb-2"
          />
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
          <p className="text-sm leading-relaxed whitespace-pre-wrap">{note.text}</p>
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
          {note.source_url ? (
            <a
              href={note.source_url} target="_blank" rel="noreferrer"
              className="inline-flex items-center gap-1 hover:underline truncate max-w-[260px]"
            >
              <ExternalLink className="w-3 h-3 shrink-0" />
              <span className="truncate">{note.source_title || note.source_url}</span>
            </a>
          ) : note.chapter_ref ? (
            <span className="truncate">{note.chapter_ref}</span>
          ) : <span>Saved</span>}
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

export default function NotebookPage() {
  const [notes, setNotes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState('');
  const [tag, setTag] = useState('');
  const [building, setBuilding] = useState(false);
  const [seenAt, setSeenAt] = useState(() => getClaimSeenAt());

  const load = useCallback(() => {
    setLoading(true);
    studyApi.listNotes({ q, tag, limit: 200 })
      .then((r) => setNotes(r.notes || []))
      .catch((e) => toast.error(e.message || 'Failed to load notes'))
      .finally(() => setLoading(false));
  }, [q, tag]);

  useEffect(() => { load(); }, [load]);

  // Once any "Recently synced" badges are visible, mark them as seen so
  // they disappear on the next page load (first-session-only badge).
  useEffect(() => {
    if (loading) return;
    const maxClaimed = notes.reduce(
      (m, n) => (n.claimed_at && n.claimed_at > m ? n.claimed_at : m), '');
    if (maxClaimed && maxClaimed > seenAt) {
      const t = setTimeout(() => {
        markClaimSeen(maxClaimed);
        setSeenAt(maxClaimed);
      }, 1500);
      return () => clearTimeout(t);
    }
  }, [loading, notes, seenAt]);

  const allTags = useMemo(() => {
    const s = new Set();
    notes.forEach(n => (n.tags || []).forEach(t => s.add(t)));
    return Array.from(s).sort();
  }, [notes]);

  const onDelete = async (id) => {
    setNotes((n) => n.filter(x => x.id !== id));
    try { await studyApi.deleteNote(id); toast.success('Deleted'); }
    catch (e) { toast.error(e.message || 'Delete failed'); load(); }
  };

  const onChange = (updated) => {
    setNotes((n) => n.map(x => x.id === updated.id ? updated : x));
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
        <header className="flex items-start justify-between gap-3 mb-5">
          <div>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <NotebookPen className="w-6 h-6 text-primary" />
              Notebook
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              Highlights you saved from chapters, the educational browser, and chat.
            </p>
          </div>
          <div className="flex gap-2">
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

        {loading ? (
          <div className="flex items-center justify-center py-20 text-muted-foreground">
            <Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading notes…
          </div>
        ) : notes.length === 0 ? (
          <div className="text-center py-16 border border-dashed border-border/60 rounded-2xl">
            <NotebookPen className="w-10 h-10 mx-auto mb-3 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              No notes yet. Highlight any text in a chapter or article and tap <em>Save</em>.
            </p>
            <Link to="/library" className="inline-block mt-3 text-sm font-medium text-primary hover:underline">
              Browse the library →
            </Link>
          </div>
        ) : (
          <div className="grid gap-3">
            {notes.map((n) => (
              <NoteCard
                key={n.id} note={n} onChange={onChange} onDelete={onDelete}
                recentlySynced={isRecentlyClaimed(n.claimed_at, seenAt)}
              />
            ))}
          </div>
        )}
      </div>
    </AppLayout>
  );
}
