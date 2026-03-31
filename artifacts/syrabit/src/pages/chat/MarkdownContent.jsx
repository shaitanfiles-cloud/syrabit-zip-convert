import { useMemo } from 'react';
import { motion } from 'framer-motion';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const MD_LINK_COMPONENTS = {
  a: ({ href, children }) => {
    if (!href) return <span>{children}</span>;
    if (href.startsWith('http')) {
      return <a href={href} target="_blank" rel="noopener noreferrer" className="inline-source-link">{children}</a>;
    }
    return (
      <button onClick={() => { window.location.href = href; }} className="inline-source-link">
        {children}
      </button>
    );
  },
};

export function MarkdownContent({ content, streaming, sources }) {
  const processed = useMemo(() => {
    if (!content) return content;
    const normalize = (s) => (s || '').trim().toLowerCase().replace(/[\s\-_]+/g, ' ').replace(/[^a-z0-9 ]/g, '');
    const toSlug = (s) => normalize(s).replace(/\s+/g, '-');
    const urlMap = new Map();
    for (const s of (sources || [])) {
      const url = s.url || '';
      if (s.title) {
        urlMap.set(normalize(s.title), url);
        urlMap.set(toSlug(s.title), url);
      }
      if (s.slug) {
        urlMap.set(normalize(s.slug), url || `/learn/${s.slug}`);
        urlMap.set(toSlug(s.slug), url || `/learn/${s.slug}`);
      }
    }
    const findUrl = (raw) => {
      const norm = normalize(raw);
      const slug = toSlug(raw);
      if (urlMap.has(norm)) return urlMap.get(norm);
      if (urlMap.has(slug)) return urlMap.get(slug);
      if (norm.length >= 8) {
        for (const [k, v] of urlMap) {
          if (k.length >= 8 && (k.includes(norm) || norm.includes(k))) return v;
        }
      }
      return '';
    };
    return content.replace(/\[(PAGE|CHAPTER|TOPIC|LESSON|SECTION):\s*([^\]]+)\]/gi, (_, _type, rawTitle) => {
      const title = rawTitle.trim();
      const url = findUrl(title);
      return url ? `[${title}](${url})` : `**${title}**`;
    });
  }, [content, sources]);

  return (
    <div className="md-content-light" style={{ fontSize: '0.9375rem' }}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_LINK_COMPONENTS}>
        {processed}
      </ReactMarkdown>
      {streaming && (
        <motion.span
          className="inline-block rounded-full align-middle"
          style={{ width: 2, height: '1em', marginLeft: 2, background: 'hsl(var(--primary))' }}
          animate={{ opacity: [1, 0, 1] }}
          transition={{ duration: 0.65, repeat: Infinity }}
        />
      )}
    </div>
  );
}
