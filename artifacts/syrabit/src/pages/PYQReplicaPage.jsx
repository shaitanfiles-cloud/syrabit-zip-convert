import { useEffect, useState, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import { API_BASE } from '../utils/api';
import { useShare } from '../hooks/useShare';

export default function PYQReplicaPage() {
  const { slug } = useParams();
  const [html, setHtml]         = useState('');
  const [title, setTitle]       = useState('');
  const [loading, setLoading]   = useState(true);
  const [notFound, setNotFound] = useState(false);
  const { sharing, share } = useShare();

  const handleShare = useCallback(() => {
    const pyqTitle = title || `PYQ — ${slug}`;
    share(pyqTitle, `/pyq/${slug}`);
  }, [slug, title, share]);

  useEffect(() => {
    if (!slug) return;
    setLoading(true);
    setNotFound(false);
    setHtml('');

    fetch(`${API_BASE}/pyq/${slug}`, { method: 'GET' })
      .then(async (res) => {
        if (res.status === 404) { setNotFound(true); return; }
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const rawHtml = await res.text();
        const titleMatch = rawHtml.match(/<title>([^<]*)<\/title>/i);
        if (titleMatch) setTitle(titleMatch[1]);
        const descMatch  = rawHtml.match(/<meta[^>]+name=["']description["'][^>]+content=["']([^"']+)["']/i)
                        || rawHtml.match(/<meta[^>]+content=["']([^"']+)["'][^>]+name=["']description["']/i);
        if (descMatch) {
          const el = document.querySelector('meta[name="description"]');
          if (el) el.setAttribute('content', descMatch[1]);
        }
        setHtml(rawHtml);
      })
      .catch(() => setNotFound(true))
      .finally(() => setLoading(false));
  }, [slug]);

  useEffect(() => {
    if (title) document.title = title;
  }, [title]);

  if (loading) {
    return (
      <div style={{
        minHeight: '100vh', display: 'flex', alignItems: 'center',
        justifyContent: 'center', background: '#fff', color: '#333',
        fontFamily: '"Times New Roman", Times, serif',
      }}>
        <p>Loading question paper…</p>
      </div>
    );
  }

  if (notFound) {
    return (
      <div style={{
        minHeight: '100vh', display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center', background: '#fff',
        color: '#333', fontFamily: '"Times New Roman", Times, serif',
        gap: '12px',
      }}>
        <h1 style={{ fontSize: '1.4em' }}>Question Paper Not Found</h1>
        <p style={{ fontSize: '0.95em', color: '#666' }}>
          The page <code>/pyq/{slug}</code> does not exist.
        </p>
        <a href="/" style={{ color: '#1a56db', fontSize: '0.9em' }}>← Back to Syrabit.ai</a>
      </div>
    );
  }

  return (
    <div style={{ background: '#fff', minHeight: '100vh', position: 'relative' }}>
      <button
        onClick={handleShare}
        disabled={sharing}
        style={{
          position: 'fixed', bottom: '20px', right: '20px', zIndex: 1000,
          background: '#3b82f6', color: '#fff', border: 'none', borderRadius: '50px',
          padding: '10px 18px', fontSize: '14px', fontWeight: 600,
          cursor: sharing ? 'wait' : 'pointer', boxShadow: '0 2px 10px rgba(0,0,0,0.15)',
          display: 'flex', alignItems: 'center', gap: '6px',
          opacity: sharing ? 0.7 : 1,
        }}
      >
        📤 {sharing ? 'Sharing…' : 'Share'}
      </button>
      <div dangerouslySetInnerHTML={{ __html: html }} />
    </div>
  );
}
