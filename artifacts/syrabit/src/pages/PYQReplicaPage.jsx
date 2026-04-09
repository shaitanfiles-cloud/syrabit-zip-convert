import { useEffect, useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { WORKER_API } from '../utils/api';
import { useShare } from '../hooks/useShare';

export default function PYQReplicaPage() {
  const { slug } = useParams();
  const navigate = useNavigate();
  const [html, setHtml]         = useState('');
  const [title, setTitle]       = useState('');
  const [loading, setLoading]   = useState(true);
  const [notFound, setNotFound] = useState(false);
  const { sharing, share } = useShare();

  const handleShare = useCallback(() => {
    const pyqTitle = title || `PYQ — ${slug}`;
    share(pyqTitle, `/pyq/${slug}`);
  }, [slug, title, share]);

  const handlePrint = useCallback(() => {
    window.print();
  }, []);

  useEffect(() => {
    if (!slug) return;
    setLoading(true);
    setNotFound(false);
    setHtml('');

    fetch(`${WORKER_API}/pyq/${slug}`, { method: 'GET' })
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
        <div style={{ textAlign: 'center' }}>
          <div style={{ width: 32, height: 32, border: '3px solid #e5e7eb', borderTopColor: '#6366f1', borderRadius: '50%', animation: 'spin 0.8s linear infinite', margin: '0 auto 12px' }} />
          <p>Loading question paper…</p>
        </div>
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  if (notFound) {
    return (
      <div style={{
        minHeight: '100vh', display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center', background: '#fff',
        color: '#333', fontFamily: '"Times New Roman", Times, serif',
        gap: '12px', padding: '20px',
      }}>
        <h1 style={{ fontSize: '1.4em' }}>Question Paper Not Found</h1>
        <p style={{ fontSize: '0.95em', color: '#666', textAlign: 'center' }}>
          The page <code>/pyq/{slug}</code> does not exist.
        </p>
        <a href="/" style={{ color: '#6366f1', fontSize: '0.9em', textDecoration: 'none' }}>← Back to Syrabit.ai</a>
      </div>
    );
  }

  return (
    <div style={{ background: '#fff', minHeight: '100vh', position: 'relative' }}>
      <div
        className="pyq-toolbar"
        style={{
          position: 'fixed', top: 0, left: 0, right: 0, zIndex: 1000,
          background: 'rgba(255,255,255,0.95)', backdropFilter: 'blur(8px)',
          borderBottom: '1px solid #e5e7eb', padding: '8px 16px',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}
      >
        <button
          onClick={() => navigate(-1)}
          style={{
            background: 'none', border: 'none', color: '#6366f1',
            fontSize: '14px', fontWeight: 500, cursor: 'pointer',
            display: 'flex', alignItems: 'center', gap: '4px',
            fontFamily: 'system-ui, sans-serif',
          }}
        >
          ← Back
        </button>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            onClick={handlePrint}
            style={{
              background: '#f3f4f6', color: '#374151', border: 'none', borderRadius: '8px',
              padding: '6px 14px', fontSize: '13px', fontWeight: 500,
              cursor: 'pointer', fontFamily: 'system-ui, sans-serif',
              display: 'flex', alignItems: 'center', gap: '4px',
            }}
          >
            🖨️ Print / Save PDF
          </button>
          <button
            onClick={handleShare}
            disabled={sharing}
            style={{
              background: '#6366f1', color: '#fff', border: 'none', borderRadius: '8px',
              padding: '6px 14px', fontSize: '13px', fontWeight: 500,
              cursor: sharing ? 'wait' : 'pointer', fontFamily: 'system-ui, sans-serif',
              opacity: sharing ? 0.7 : 1,
            }}
          >
            📤 {sharing ? 'Sharing…' : 'Share'}
          </button>
        </div>
      </div>

      <div className="pyq-content" style={{ paddingTop: '52px' }} dangerouslySetInnerHTML={{ __html: html }} />

      <style>{`
        @media print {
          .pyq-toolbar { display: none !important; }
          .pyq-content { padding-top: 0 !important; }
        }
      `}</style>
    </div>
  );
}
