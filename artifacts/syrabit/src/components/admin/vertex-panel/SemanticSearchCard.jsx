import { useState } from 'react';
import { Search, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { vertexSemanticSearch } from '@/utils/api';
import { card, btn, Badge } from './shared';

export default function SemanticSearchCard({ token }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);

  async function run() {
    if (!query.trim()) return;
    setLoading(true);
    try {
      const r = await vertexSemanticSearch(token, query.trim(), 10);
      setResults(r.data.results || []);
    } catch {
      toast.error('Semantic search failed');
    } finally { setLoading(false); }
  }

  return (
    <div style={card}>
      <div className="flex items-center gap-2 mb-4">
        <Search size={16} color="#3b82f6" />
        <span style={{ fontWeight: 700, color: '#e8e8e8' }}>Semantic Topic Search</span>
        <Badge label="Embeddings" color="#3b82f6" />
      </div>
      <p style={{ fontSize: 12, color: 'rgba(232,232,232,0.5)', marginBottom: 12 }}>
        Find topics by meaning, not keyword. Powered by text-embedding-004.
      </p>
      <div className="flex gap-2 mb-4">
        <input
          value={query} onChange={e => setQuery(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && run()}
          placeholder="e.g. chemical bonding in organic chemistry"
          style={{ flex: 1, background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10, padding: '8px 14px', color: '#e8e8e8', fontSize: 13 }}
        />
        <button onClick={run} disabled={loading} style={btn('#3b82f6')}>
          {loading ? <Loader2 size={13} className="animate-spin" /> : <Search size={13} />}
          Search
        </button>
      </div>
      {results.length > 0 && (
        <div style={{ maxHeight: 260, overflowY: 'auto' }}>
          {results.map((r, i) => (
            <div key={i} className="flex items-center gap-3 py-2" style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: '#3b82f6', width: 24 }}>#{i + 1}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, color: '#e8e8e8', fontWeight: 600 }}>{r.title}</div>
                <div style={{ fontSize: 11, color: 'rgba(232,232,232,0.45)' }}>{r.subject_name} · {r.class_name}</div>
              </div>
              <span style={{ background: 'rgba(59,130,246,0.15)', color: '#3b82f6', borderRadius: 8, padding: '2px 8px', fontSize: 11, fontWeight: 700 }}>
                {(r.score * 100).toFixed(0)}%
              </span>
              <Badge label={r.status || 'draft'} color={r.status === 'published' ? '#10b981' : '#64748b'} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
