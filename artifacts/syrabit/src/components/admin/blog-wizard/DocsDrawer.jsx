import { useState } from 'react';
import { Loader2, RefreshCw, Trash2, X } from 'lucide-react';
import { toast } from 'sonner';
import axios from 'axios';
import { API, authHeaders } from '@/utils/adminHelpers';

export default function DocsDrawer({ docs, loading, onClose, onLoad, adminToken, onRefresh }) {
  const [search, setSearch] = useState('');
  const [deleting, setDeleting] = useState(null);

  const filtered = search
    ? docs.filter(d => d.title?.toLowerCase().includes(search.toLowerCase()) || d.seo_slug?.toLowerCase().includes(search.toLowerCase()))
    : docs;

  const handleDelete = async (doc, e) => {
    e.stopPropagation();
    if (!confirm(`Delete "${doc.title}"?`)) return;
    setDeleting(doc.id);
    try {
      await axios.delete(`${API}/admin/content/cms-documents/${doc.id}`, authHeaders(adminToken));
      toast.success('Deleted');
      onRefresh();
    } catch { toast.error('Delete failed'); }
    finally { setDeleting(null); }
  };

  return (
    <div className="fixed inset-0 z-50 flex" onClick={onClose}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
      <div
        className="relative ml-auto w-full max-w-sm h-full flex flex-col"
        style={{ background: '#0f0f1e', borderLeft: '1px solid rgba(255,255,255,0.08)' }}
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b" style={{ borderColor: 'rgba(255,255,255,0.07)' }}>
          <h3 className="text-sm font-bold text-white">My Documents</h3>
          <div className="flex items-center gap-2">
            <button onClick={onRefresh} className="text-white/40 hover:text-white/70 transition"><RefreshCw size={13} /></button>
            <button onClick={onClose} className="text-white/40 hover:text-white/70 transition"><X size={16} /></button>
          </div>
        </div>

        <div className="px-3 py-2 border-b flex-shrink-0" style={{ borderColor: 'rgba(255,255,255,0.07)' }}>
          <input
            value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Search documents…"
            className="w-full h-8 px-3 rounded-lg text-sm text-white bg-white/5 border border-white/10 outline-none focus:border-violet-500"
          />
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {loading && (
            <div className="flex items-center justify-center py-8 gap-2 text-white/30 text-sm">
              <Loader2 size={16} className="animate-spin" /> Loading…
            </div>
          )}
          {!loading && filtered.length === 0 && (
            <p className="text-center py-8 text-white/30 text-sm">No documents found</p>
          )}
          {filtered.map(doc => (
            <div key={doc.id}
              onClick={() => onLoad(doc)}
              className="rounded-xl p-3 cursor-pointer border transition group hover:border-violet-500/30"
              style={{ background: 'rgba(255,255,255,0.025)', borderColor: 'rgba(255,255,255,0.07)' }}>
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-white/80 truncate">{doc.title || 'Untitled'}</p>
                  <p className="text-[10px] text-white/35 truncate mt-0.5">{doc.seo_slug || doc.id}</p>
                </div>
                <div className="flex items-center gap-1.5 flex-shrink-0">
                  <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full ${
                    doc.status === 'published' ? 'bg-emerald-500/15 text-emerald-400' : 'bg-white/8 text-white/30'}`}>
                    {doc.status}
                  </span>
                  <button
                    onClick={e => handleDelete(doc, e)}
                    disabled={deleting === doc.id}
                    className="opacity-0 group-hover:opacity-100 transition text-red-400/50 hover:text-red-400"
                  >
                    {deleting === doc.id ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                  </button>
                </div>
              </div>
              {doc.word_count && (
                <p className="text-[10px] text-white/25 mt-1">{doc.word_count} words · {doc.schema_type}</p>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
