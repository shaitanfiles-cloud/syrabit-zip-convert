import { useState, useEffect, useRef, useCallback } from 'react';
import { log } from '@/utils/logger';
import { BookText, Loader2 } from 'lucide-react';
import { MasonryInfiniteGrid } from '@egjs/react-infinitegrid';
import CmsPostCard from './CmsPostCard';

const CMS_API = `${import.meta.env.VITE_BACKEND_URL || ''}/api`;
const POSTS_PER_PAGE = 12;

export default function CmsPostsGrid({ board, classSlug }) {
  const [items,    setItems]    = useState([]);
  const [total,    setTotal]    = useState(0);
  const [loading,  setLoading]  = useState(false);
  const [done,     setDone]     = useState(false);
  const groupKey = useRef(0);

  const fetchPage = useCallback(async (skip) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: POSTS_PER_PAGE, skip });
      if (board)      params.append('board',      board);
      if (classSlug)  params.append('class_slug', classSlug);
      const res  = await fetch(`${CMS_API}/cms/posts?${params}`);
      const data = await res.json();
      const newItems = (data.items || []).map(p => ({ ...p, groupKey: groupKey.current }));
      setItems(prev => skip === 0 ? newItems : [...prev, ...newItems]);
      setTotal(data.total || 0);
      if (skip + POSTS_PER_PAGE >= (data.total || 0)) setDone(true);
      groupKey.current += 1;
    } catch (err) { log.error('CMS posts fetch failed', { error: err.message, route: '/api/cms/posts', skip }); }
    finally { setLoading(false); }
  }, [board, classSlug]);

  useEffect(() => { setItems([]); setDone(false); groupKey.current = 0; fetchPage(0); }, [fetchPage]);

  if (!loading && items.length === 0) return null;

  return (
    <div className="w-full max-w-6xl mx-auto px-4 md:px-6 pb-10">
      <div className="flex items-center gap-2 mb-4 mt-2">
        <BookText size={16} className="text-violet-400" />
        <h2 className="text-base font-semibold text-foreground">Subject Blog Posts</h2>
        {total > 0 && (
          <span className="ml-1 px-2 py-0.5 rounded-full text-[10px] font-medium" style={{ background: 'rgba(149,117,224,0.12)', color: '#a78bfa' }}>{total}</span>
        )}
      </div>
      <MasonryInfiniteGrid
        className="cms-posts-masonry"
        gap={16}
        align="stretch"
        useResizeObserver
        observeChildren
        onRequestAppend={({ groupKey: gk }) => {
          if (loading || done) return;
          fetchPage(items.length);
        }}
      >
        {items.map(post => (
          <CmsPostCard key={post.subject_id} post={post} />
        ))}
      </MasonryInfiniteGrid>
      {loading && (
        <div className="flex justify-center py-6">
          <Loader2 size={20} className="animate-spin text-violet-400" />
        </div>
      )}
      {done && items.length > 0 && (
        <p className="text-center text-xs py-4" style={{ color: 'rgba(232,232,232,0.25)' }}>All {total} posts loaded</p>
      )}
    </div>
  );
}
