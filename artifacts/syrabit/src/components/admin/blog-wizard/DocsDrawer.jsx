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
        style={{ background: '#f8f9fc', borderLeft: '1px solid #e5e7eb' }}
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b" style={{ borderColor: '#e5e7eb' }}>
          <h3 className="text-sm font-bold text-gray-900">My Documents</h3>
          <div className="flex items-center gap-2">
            <button onClick={onRefresh} className="text-gray-600 hover:text-gray-800 transition"><RefreshCw size={13} /></button>
            <button onClick={onClose} className="text-gray-600 hover:text-gray-800 transition"><X size={16} /></button>
          </div>
        </div>

        <div className="px-3 py-2 border-b flex-shrink-0" style={{ borderColor: '#e5e7eb' }}>
          <input
            value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Search documents…"
            className="w-full h-8 px-3 rounded-lg text-sm text-gray-900 bg-gray-50 border border-gray-200 outline-none focus:border-violet-500"
          />
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {loading && (
            <div className="flex items-center justify-center py-8 gap-2 text-gray-600 text-sm">
              <Loader2 size={16} className="animate-spin" /> Loading…
            </div>
          )}
          {!loading && filtered.length === 0 && (
            <p className="text-center py-8 text-gray-600 text-sm">No documents found</p>
          )}
          {filtered.map(doc => (
            <div key={doc.id}
              onClick={() => onLoad(doc)}
              className="rounded-xl p-3 cursor-pointer border transition group hover:border-violet-500/30"
              style={{ background: '#ffffff', borderColor: '#e5e7eb' }}>
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-gray-700 truncate">{doc.title || 'Untitled'}</p>
                  <p className="text-[10px] text-gray-600 truncate mt-0.5">{doc.seo_slug || doc.id}</p>
                </div>
                <div className="flex items-center gap-1.5 flex-shrink-0">
                  <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full ${
                    doc.status === 'published' ? 'bg-emerald-500/15 text-emerald-600' : 'bg-gray-100 text-gray-600'}`}>
                    {doc.status}
                  </span>
                  <button
                    onClick={e => handleDelete(doc, e)}
                    disabled={deleting === doc.id}
                    className="opacity-0 group-hover:opacity-100 transition text-red-600/50 hover:text-red-600"
                  >
                    {deleting === doc.id ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                  </button>
                </div>
              </div>
              {doc.word_count && (
                <p className="text-[10px] text-gray-700 mt-1">{doc.word_count} words · {doc.schema_type}</p>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
