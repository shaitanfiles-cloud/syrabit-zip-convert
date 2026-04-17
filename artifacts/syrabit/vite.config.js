import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const isProd = process.env.NODE_ENV === 'production';
const BACKEND_TARGET = process.env.VITE_BACKEND_URL || 'http://localhost:8000';

const BOT_UA = /googlebot|google-extended|googleother|google-inspectiontool|bingbot|yandexbot|yandex|duckduckbot|slurp|baiduspider|facebookexternalhit|facebookbot|twitterbot|linkedinbot|telegrambot|whatsapp|applebot|applebot-extended|ia_archiver|msnbot|ahrefsbot|semrushbot|petalbot|gptbot|oai-searchbot|chatgpt-user|claudebot|anthropic-ai|perplexitybot|meta-externalagent|cohere-ai|bytespider|ccbot/i;

const SKIP_ROUTES = new Set([
  'library', 'chat', 'history', 'profile', 'pricing', 'signup', 'login',
  'admin', 'auth', 'api', 'health', 'docs', 'openapi.json', 'assets',
  'icons', 'fonts', 'robots.txt', 'sitemap.xml', 'favicon.ico',
]);

function mdToText(md = '') {
  return md
    .replace(/^#+\s+/gm, '')
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/\*(.+?)\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/^[-*]\s+/gm, '')
    .replace(/^\d+\.\s+/gm, '')
    .replace(/\n{2,}/g, '\n')
    .trim();
}

function mdToHtml(md = '') {
  let html = md
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/^#### (.+)$/gm, '<h4>$1</h4>')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$2</h2>'.replace('$2', '$1'))
    .replace(/^# (.+)$/gm, '<h2>$1</h2>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/^---$/gm, '<hr>')
    .replace(/^[-*] (.+)$/gm, '<li>$1</li>')
    .replace(/^\d+\. (.+)$/gm, '<li>$1</li>')
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g, '<br>');
  return `<p>${html}</p>`;
}

function buildBotHtml(page, url, board, classSlug, subjectSlug, topicSlug, currentType, related) {
  const canonical = `https://syrabit.ai${url.split('?')[0]}`;
  const ogImage = 'https://syrabit.ai/opengraph.jpg';
  const keywords = [
    page.topic_title, page.subject_name, page.chapter_title, page.board_name,
    page.class_name, 'study notes', 'exam preparation', 'AHSEC', 'SEBA',
    `${page.topic_title} notes`, `${page.board_name} ${page.subject_name}`,
    `${page.topic_title} important questions`,
  ].filter(Boolean).join(', ');

  const articleSchema = {
    '@context': 'https://schema.org',
    '@type': 'Article',
    headline: page.title,
    description: page.meta_description,
    author: { '@type': 'Organization', name: 'Syrabit.ai', url: 'https://syrabit.ai' },
    publisher: {
      '@type': 'Organization',
      name: 'Syrabit.ai',
      url: 'https://syrabit.ai',
      logo: { '@type': 'ImageObject', url: 'https://syrabit.ai/icons/icon-192x192.png' },
    },
    datePublished: page.generated_at,
    dateModified: page.updated_at || page.generated_at,
    image: ogImage,
    mainEntityOfPage: { '@type': 'WebPage', '@id': canonical },
    educationalLevel: `${page.class_name || ''} ${page.board_name || ''}`.trim(),
    about: { '@type': 'Thing', name: page.topic_title },
    inLanguage: 'en-IN',
  };

  const breadcrumbSchema = {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: [
      { '@type': 'ListItem', position: 1, name: 'Home', item: 'https://syrabit.ai' },
      { '@type': 'ListItem', position: 2, name: 'Library', item: 'https://syrabit.ai/library' },
      { '@type': 'ListItem', position: 3, name: page.subject_name, item: `https://syrabit.ai/${page.board_slug || 'library'}/${page.class_slug || ''}/${page.stream_slug || ''}/${page.subject_slug || ''}`.replace(/\/+$/, '') },
      { '@type': 'ListItem', position: 4, name: page.chapter_title, item: `https://syrabit.ai/${page.board_slug || 'library'}/${page.class_slug || ''}/${page.stream_slug || ''}/${page.subject_slug || ''}/${page.chapter_slug || ''}`.replace(/\/+$/, '') },
      { '@type': 'ListItem', position: 5, name: page.topic_title, item: canonical },
    ],
  };

  const schemas = [articleSchema, breadcrumbSchema];

  if (['important-questions', 'mcqs'].includes(currentType) && page.content) {
    const lines = page.content.split('\n').filter(Boolean);
    const questions = [];
    let currentQ = null;
    for (const line of lines) {
      const stripped = line.replace(/^#+\s*/, '').replace(/^\*\*/, '').replace(/\*\*$/, '').trim();
      if (line.match(/^[#*]/) && stripped.endsWith('?')) { currentQ = stripped; }
      else if (currentQ && stripped.length > 10) {
        questions.push({ '@type': 'Question', name: currentQ, acceptedAnswer: { '@type': 'Answer', text: stripped } });
        currentQ = null;
        if (questions.length >= 10) break;
      }
    }
    if (questions.length >= 3) {
      schemas.push({ '@context': 'https://schema.org', '@type': 'FAQPage', mainEntity: questions });
    }
  }

  const basePath = `/${board}/${classSlug}/${subjectSlug}/${topicSlug}`;
  const pageTypes = ['notes', 'definition', 'important-questions', 'mcqs', 'examples'];

  const navLinks = related?.related?.slice(0, 6).map(t =>
    `<li><a href="${t.seo_path || '#'}" rel="related">${t.title} — ${page.board_name} ${page.class_name} ${page.subject_name} Notes</a></li>`
  ).join('') || '';

  const prevNext = [
    related?.prev ? `<a href="${related.prev.seo_path || '#'}" rel="prev">← Previous: ${related.prev.title}</a>` : '',
    related?.next ? `<a href="${related.next.seo_path || '#'}" rel="next">Next: ${related.next.title} →</a>` : '',
  ].filter(Boolean).join(' | ');

  const typeLinks = pageTypes.map(t =>
    `<a href="${t === 'notes' ? basePath : `${basePath}/${t}`}">${t === 'notes' ? 'Notes' : t === 'definition' ? 'Definition' : t === 'important-questions' ? 'Important Questions' : t === 'mcqs' ? 'MCQs' : 'Examples'} for ${page.topic_title}</a>`
  ).join(' | ');

  const contentText = mdToText(page.content || '');
  const excerpt = contentText.slice(0, 300).replace(/\n/g, ' ').trim();
  const contentHtml = mdToHtml(page.content || '');

  return `<!DOCTYPE html>
<html lang="en-IN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>${page.title}</title>
<meta name="description" content="${(page.meta_description || excerpt).replace(/"/g, '&quot;')}">
<meta name="keywords" content="${keywords.replace(/"/g, '&quot;')}">
<link rel="canonical" href="${canonical}">
<meta property="og:type" content="article">
<meta property="og:title" content="${(page.title || '').replace(/"/g, '&quot;')}">
<meta property="og:description" content="${(page.meta_description || excerpt).replace(/"/g, '&quot;')}">
<meta property="og:url" content="${canonical}">
<meta property="og:image" content="${ogImage}">
<meta property="og:site_name" content="Syrabit.ai">
<meta property="og:locale" content="en_IN">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="${(page.title || '').replace(/"/g, '&quot;')}">
<meta name="twitter:description" content="${(page.meta_description || excerpt).replace(/"/g, '&quot;')}">
<meta name="twitter:image" content="${ogImage}">
<meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large, max-video-preview:-1">
${schemas.map(s => `<script type="application/ld+json">${JSON.stringify(s)}</script>`).join('\n')}
<style>
body{font-family:system-ui,sans-serif;background:#0a0a1a;color:#e2e8f0;margin:0;padding:0}
.wrap{max-width:860px;margin:0 auto;padding:24px 16px}
nav a,a{color:#a78bfa;text-decoration:none}
a:hover{text-decoration:underline}
h1{font-size:1.8rem;font-weight:700;margin:0 0 8px}
h2{font-size:1.3rem;font-weight:600;color:#f1f5f9;margin:24px 0 8px;border-bottom:1px solid rgba(255,255,255,0.1);padding-bottom:6px}
h3,h4{font-size:1.1rem;font-weight:600;color:#e2e8f0;margin:16px 0 6px}
p{color:#94a3b8;line-height:1.7;margin:0 0 12px}
li{color:#94a3b8;margin:4px 0;line-height:1.6}
strong{color:#f1f5f9}
code{background:rgba(255,255,255,0.1);color:#c4b5fd;padding:2px 6px;border-radius:4px;font-size:0.9em}
hr{border:none;border-top:1px solid rgba(255,255,255,0.1);margin:20px 0}
.badges{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.badge{padding:2px 10px;border-radius:20px;font-size:0.78rem;border:1px solid rgba(139,92,246,0.3);color:#a78bfa}
.meta{color:#64748b;font-size:0.85rem;margin-bottom:20px}
.content{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:16px;padding:24px;margin:20px 0}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}
.tabs a{padding:6px 14px;border-radius:8px;background:rgba(255,255,255,0.06);font-size:0.85rem;color:#94a3b8}
.related{margin-top:28px}
.related ul{list-style:none;padding:0;display:grid;grid-template-columns:1fr 1fr;gap:8px}
.related li a{display:block;padding:10px 14px;background:rgba(255,255,255,0.05);border-radius:10px;font-size:0.9rem;transition:background 0.2s}
.related li a:hover{background:rgba(255,255,255,0.1);text-decoration:none}
.prevnext{display:flex;justify-content:space-between;margin-top:24px;gap:12px}
.cta{text-align:center;margin:32px 0;padding:24px;background:rgba(124,58,237,0.1);border:1px solid rgba(124,58,237,0.2);border-radius:16px}
.cta a{display:inline-block;padding:10px 24px;background:#7c3aed;color:#fff;border-radius:10px;font-weight:600;margin-top:8px}
.breadcrumb{font-size:0.82rem;color:#475569;margin-bottom:16px}
.breadcrumb a{color:#6d28d9}
@media(max-width:600px){.related ul{grid-template-columns:1fr}.prevnext{flex-direction:column}}
</style>
</head>
<body>
<div class="wrap">

<nav class="breadcrumb" aria-label="Breadcrumb">
  <a href="/">Home</a> &rsaquo;
  <a href="/library">Library</a> &rsaquo;
  <span>${page.subject_name || subjectSlug}</span> &rsaquo;
  <span>${page.topic_title || topicSlug}</span>
</nav>

<div class="badges">
  <span class="badge">${page.board_name || board}</span>
  <span class="badge">${page.class_name || classSlug}</span>
  <span class="badge">${page.subject_name || subjectSlug}</span>
</div>

<h1>${page.topic_title || topicSlug} – ${page.board_name || board} ${page.class_name || classSlug} ${page.subject_name || subjectSlug}</h1>
<p class="meta">${page.chapter_title || ''} &middot; ${page.word_count || 0} words &middot; Updated ${new Date(page.updated_at || page.generated_at || Date.now()).toLocaleDateString('en-IN')}</p>

<p>${page.meta_description || excerpt}</p>

<div class="tabs" role="navigation" aria-label="Content types">
${typeLinks}
</div>

<div class="content">
${contentHtml}
</div>

${prevNext ? `<div class="prevnext">${prevNext}</div>` : ''}

${navLinks ? `<div class="related"><h2>Related Topics in ${page.subject_name}</h2><ul>${navLinks}</ul></div>` : ''}

<div class="cta">
  <strong>Study smarter with AI-powered tutoring</strong>
  <p>Get instant answers, MCQs, and exam tips for ${page.board_name} ${page.class_name} ${page.subject_name}</p>
  <a href="/signup">Start for Free — No Card Needed</a>
</div>

<p style="font-size:0.8rem;color:#334155;margin-top:32px;text-align:center">
  <a href="/">Syrabit.ai</a> &mdash; AI-powered exam prep for Assam Board students (AHSEC, SEBA, Degree) &mdash;
  <a href="/library">Study Library</a> &mdash; <a href="/pricing">Plans &amp; Pricing</a>
</p>

</div>
</body>
</html>`;
}

// ── PYQ HTML Replica page plugin ──────────────────────────────────────────────
// Intercepts ALL requests to /pyq/* and serves the full SEO HTML document
// directly from the backend (bypassing the React SPA wrapper).
// This ensures bots and direct visitors get crawlable, rankable HTML.
function pyqPagePlugin() {
  return {
    name: 'syrabit-pyq-page',
    configureServer(server) {
      return () => server.middlewares.use(async (req, res, next) => {
        const rawPath = (req.url || '/').split('?')[0];
        if (!rawPath.startsWith('/pyq/')) return next();
        const slug = rawPath.slice(5); // strip leading "/pyq/"
        if (!slug || slug.includes('/') || slug.includes('.')) return next();
        try {
          const backendRes = await fetch(`${BACKEND_TARGET}/api/pyq/${encodeURIComponent(slug)}`);
          if (!backendRes.ok) return next();
          const html = await backendRes.text();
          res.statusCode = 200;
          res.setHeader('Content-Type', 'text/html; charset=utf-8');
          res.setHeader('Cache-Control', 'public, max-age=3600, s-maxage=86400');
          res.end(html);
        } catch {
          next();
        }
      });
    },
  };
}

function botRenderPlugin() {
  return {
    name: 'syrabit-bot-render',
    // NOTE: configureServer only runs in Vite dev mode.
    // In production, bot rendering is handled by:
    //   1. Edge proxy (workers/edge-proxy) — detects bot UA, proxies to backend SEO engine
    //   2. Backend BotRenderMiddleware (routes/cms_sarvam_health.py) — catches bots on CMS pages
    //   3. Backend root_redirect (server.py) — serves SEO HTML for bots hitting /
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        const ua = req.headers['user-agent'] || '';
        if (!BOT_UA.test(ua)) return next();

        const rawPath = (req.url || '/').split('?')[0];
        const parts = rawPath.split('/').filter(Boolean);

        if (parts.length < 3 || SKIP_ROUTES.has(parts[0])) return next();
        if (parts[0].includes('.')) return next();

        const [board, classSlug, subjectSlug, topicSlug, pageTypePart] = parts;

        if (parts.length === 3) {
          try {
            const apiBase = `${BACKEND_TARGET}/api/content`;
            const subjectRes = await fetch(`${apiBase}/resolve-subject/${board}/${classSlug}/${subjectSlug}`);
            if (!subjectRes.ok) return next();
            const subject = await subjectRes.json();
            const chaptersRes = await fetch(`${apiBase}/chapters/${subject.id}`);
            const chapters = chaptersRes.ok ? await chaptersRes.json() : [];
            const canonical = `https://syrabit.ai/${board}/${classSlug}/${subjectSlug}`;
            const title = `${subject.name} — ${classSlug.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase())} | Syrabit.ai`;
            const desc = subject.description || `Study ${subject.name} for ${board.toUpperCase()} students. Notes, PYQs, MCQs and AI-powered learning.`;

            const courseSchema = {
              '@context': 'https://schema.org',
              '@type': 'Course',
              name: subject.name,
              description: desc,
              provider: { '@type': 'Organization', name: 'Syrabit.ai', url: 'https://syrabit.ai' },
              hasCourseInstance: chapters.map(ch => ({
                '@type': 'CourseInstance', name: ch.title || ch.name,
              })),
            };
            const breadcrumbSchema = {
              '@context': 'https://schema.org', '@type': 'BreadcrumbList',
              itemListElement: [
                { '@type': 'ListItem', position: 1, name: 'Home', item: 'https://syrabit.ai' },
                { '@type': 'ListItem', position: 2, name: 'Library', item: 'https://syrabit.ai/library' },
                { '@type': 'ListItem', position: 3, name: subject.name, item: canonical },
              ],
            };
            const itemListSchema = {
              '@context': 'https://schema.org', '@type': 'ItemList',
              name: `${subject.name} Chapters`,
              itemListElement: chapters.map((ch, i) => ({
                '@type': 'ListItem', position: i + 1, name: ch.title || ch.name,
                url: `${canonical}/${ch.slug || ''}`,
              })),
            };

            const chapterLinks = chapters.map(ch =>
              `<li><a href="/${board}/${classSlug}/${subjectSlug}/${ch.slug}">${ch.title || ch.name}</a></li>`
            ).join('');

            const html = `<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"/>
<title>${title}</title>
<meta name="description" content="${desc}"/>
<meta name="robots" content="index, follow"/>
<link rel="canonical" href="${canonical}"/>
<meta property="og:type" content="website"/>
<meta property="og:title" content="${title}"/>
<meta property="og:description" content="${desc}"/>
<meta property="og:url" content="${canonical}"/>
<meta property="og:image" content="https://syrabit.ai/opengraph.jpg"/>
<meta name="twitter:card" content="summary_large_image"/>
<meta name="twitter:title" content="${title}"/>
<meta name="twitter:description" content="${desc}"/>
<script type="application/ld+json">${JSON.stringify(courseSchema)}</script>
<script type="application/ld+json">${JSON.stringify(breadcrumbSchema)}</script>
<script type="application/ld+json">${JSON.stringify(itemListSchema)}</script>
</head><body>
<h1>${subject.name}</h1>
<p>${desc}</p>
<h2>Chapters</h2>
<ol>${chapterLinks}</ol>
<nav><a href="/library">Back to Library</a></nav>
</body></html>`;

            res.statusCode = 200;
            res.setHeader('Content-Type', 'text/html; charset=utf-8');
            res.setHeader('X-Bot-Rendered', '1');
            res.setHeader('Cache-Control', 'public, max-age=3600, s-maxage=86400');
            return res.end(html);
          } catch (err) {
            return next();
          }
        }

        try {
          const apiBase = `${BACKEND_TARGET}/api/content`;
          const chapterRes = await fetch(`${apiBase}/chapter-by-slug/${board}/${classSlug}/${subjectSlug}/${topicSlug}`);
          if (!chapterRes.ok) return next();

          const chapter = await chapterRes.json();
          const canonical = `https://syrabit.ai/${board}/${classSlug}/${subjectSlug}/${topicSlug}`;
          const chTitle = chapter.topic_title || chapter.chapter_title || topicSlug;
          const subName = chapter.subject_name || subjectSlug;
          const bName = chapter.board_name || board;
          const cName = chapter.class_name || classSlug;
          const title = `${chTitle} — ${subName} | ${bName} ${cName} Notes`;
          const desc = chapter.meta_description || `${chTitle} notes for ${subName}. Study material for ${bName} ${cName} students.`;
          const contentHtml = mdToHtml(chapter.content || '');

          const articleSchema = {
            '@context': 'https://schema.org', '@type': 'Article',
            headline: title, description: desc,
            author: { '@type': 'Organization', name: 'Syrabit.ai', url: 'https://syrabit.ai' },
            publisher: { '@type': 'Organization', name: 'Syrabit.ai', url: 'https://syrabit.ai',
              logo: { '@type': 'ImageObject', url: 'https://syrabit.ai/icons/icon-192x192.png' } },
            datePublished: chapter.generated_at, dateModified: chapter.updated_at || chapter.generated_at,
            image: 'https://syrabit.ai/opengraph.jpg',
            mainEntityOfPage: { '@type': 'WebPage', '@id': canonical },
            educationalLevel: `${cName} ${bName}`.trim(),
            wordCount: chapter.word_count || 0, inLanguage: 'en-IN',
          };
          const breadcrumbSchema = {
            '@context': 'https://schema.org', '@type': 'BreadcrumbList',
            itemListElement: [
              { '@type': 'ListItem', position: 1, name: 'Home', item: 'https://syrabit.ai' },
              { '@type': 'ListItem', position: 2, name: 'Library', item: 'https://syrabit.ai/library' },
              { '@type': 'ListItem', position: 3, name: subName, item: `https://syrabit.ai/${board}/${classSlug}/${subjectSlug}` },
              { '@type': 'ListItem', position: 4, name: chTitle, item: canonical },
            ],
          };

          const html = `<!DOCTYPE html>
<html lang="en-IN"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>${title}</title>
<meta name="description" content="${desc.replace(/"/g, '&quot;')}">
<meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large">
<link rel="canonical" href="${canonical}">
<meta property="og:type" content="article"><meta property="og:title" content="${title.replace(/"/g, '&quot;')}">
<meta property="og:description" content="${desc.replace(/"/g, '&quot;')}"><meta property="og:url" content="${canonical}">
<meta property="og:image" content="https://syrabit.ai/opengraph.jpg"><meta property="og:site_name" content="Syrabit.ai">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="${title.replace(/"/g, '&quot;')}">
<meta name="twitter:description" content="${desc.replace(/"/g, '&quot;')}">
<script type="application/ld+json">${JSON.stringify(articleSchema)}</script>
<script type="application/ld+json">${JSON.stringify(breadcrumbSchema)}</script>
<style>body{font-family:system-ui,sans-serif;background:#0a0a1a;color:#e2e8f0;margin:0;padding:0}.wrap{max-width:860px;margin:0 auto;padding:24px 16px}a{color:#a78bfa;text-decoration:none}a:hover{text-decoration:underline}h1{font-size:1.8rem;font-weight:700;margin:0 0 8px}h2{font-size:1.3rem;font-weight:600;color:#f1f5f9;margin:24px 0 8px;border-bottom:1px solid rgba(255,255,255,0.1);padding-bottom:6px}h3,h4{font-size:1.1rem;font-weight:600;color:#e2e8f0;margin:16px 0 6px}p{color:#94a3b8;line-height:1.7;margin:0 0 12px}li{color:#94a3b8;margin:4px 0;line-height:1.6}strong{color:#f1f5f9}code{background:rgba(255,255,255,0.1);color:#c4b5fd;padding:2px 6px;border-radius:4px;font-size:0.9em}hr{border:none;border-top:1px solid rgba(255,255,255,0.1);margin:20px 0}.breadcrumb{font-size:0.82rem;color:#475569;margin-bottom:16px}.breadcrumb a{color:#6d28d9}.badges{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}.badge{padding:2px 10px;border-radius:20px;font-size:0.78rem;border:1px solid rgba(139,92,246,0.3);color:#a78bfa}.content{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:16px;padding:24px;margin:20px 0}.cta{text-align:center;margin:32px 0;padding:24px;background:rgba(124,58,237,0.1);border:1px solid rgba(124,58,237,0.2);border-radius:16px}.cta a{display:inline-block;padding:10px 24px;background:#7c3aed;color:#fff;border-radius:10px;font-weight:600;margin-top:8px}</style>
</head><body><div class="wrap">
<nav class="breadcrumb" aria-label="Breadcrumb"><a href="/">Home</a> &rsaquo; <a href="/library">Library</a> &rsaquo; <a href="/${board}/${classSlug}/${subjectSlug}">${subName}</a> &rsaquo; <span>${chTitle}</span></nav>
<div class="badges"><span class="badge">${bName}</span><span class="badge">${cName}</span><span class="badge">${subName}</span></div>
<h1>${chTitle}</h1>
<p style="color:#64748b;font-size:0.85rem">${chapter.word_count || 0} words &middot; Updated ${new Date(chapter.updated_at || chapter.generated_at || Date.now()).toLocaleDateString('en-IN')}</p>
<p>${desc}</p>
<div class="content">${contentHtml}</div>
<div class="cta"><strong>Study smarter with AI-powered tutoring</strong><p>Get instant answers for ${bName} ${cName} ${subName}</p><a href="/signup">Start for Free</a></div>
<p style="font-size:0.8rem;color:#334155;margin-top:32px;text-align:center"><a href="/">Syrabit.ai</a> &mdash; AI-powered exam prep for Assam Board students &mdash; <a href="/library">Study Library</a></p>
</div></body></html>`;

          res.statusCode = 200;
          res.setHeader('Content-Type', 'text/html; charset=utf-8');
          res.setHeader('X-Bot-Rendered', '1');
          res.setHeader('Cache-Control', 'public, max-age=3600, s-maxage=86400');
          res.end(html);
        } catch (err) {
          next();
        }
      });
    },
  };
}

function cfAnalyticsPlugin() {
  const token = process.env.VITE_CF_ANALYTICS_TOKEN || '';
  return {
    name: 'syrabit-cf-analytics',
    transformIndexHtml(html) {
      if (!token) return html.replace('<!--CF_ANALYTICS_BEACON-->', '');
      const tag = `<!-- Cloudflare Web Analytics -->\n    <script defer src='https://static.cloudflareinsights.com/beacon.min.js' data-cf-beacon='{"token": "${token}", "spa": true}'></script>`;
      return html.replace('<!--CF_ANALYTICS_BEACON-->', tag);
    },
  };
}

function backendPreconnectPlugin() {
  const backendUrl = process.env.VITE_BACKEND_URL || '';
  return {
    name: 'syrabit-backend-preconnect',
    transformIndexHtml(html) {
      if (!backendUrl) return html;
      try {
        const origin = new URL(backendUrl).origin;
        const tags = `<link rel="preconnect" href="${origin}" crossorigin />\n    <link rel="dns-prefetch" href="${origin}" />`;
        return html.replace('<!--BACKEND_PRECONNECT-->', tags);
      } catch {
        return html;
      }
    },
  };
}

export default defineConfig(({ mode }) => ({
  oxc: {
    include: /\.(m?[jt]sx?)$/,
    exclude: /node_modules/,
    lang: 'jsx',
    jsx: {
      runtime: 'automatic',
      importSource: 'react',
    },
  },

  plugins: [
    react({
      include: /\.(js|jsx|ts|tsx)$/,
    }),
    backendPreconnectPlugin(),
    cfAnalyticsPlugin(),
    pyqPagePlugin(),
    botRenderPlugin(),
  ],

  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
    extensions: ['.js', '.jsx', '.ts', '.tsx'],
  },

  server: {
    port: Number.isFinite(parseInt(process.env.PORT, 10)) ? parseInt(process.env.PORT, 10) : 5000,
    host: '0.0.0.0',
    allowedHosts: true,
    proxy: {
      '/api': { target: BACKEND_TARGET, changeOrigin: true },
      '/health': { target: BACKEND_TARGET, changeOrigin: true },
      '/docs': { target: BACKEND_TARGET, changeOrigin: true },
      '/openapi.json': { target: BACKEND_TARGET, changeOrigin: true },
      '/ads.txt': { target: BACKEND_TARGET, changeOrigin: true },
    },
  },

  define: {
    'process.env.NODE_ENV': JSON.stringify(mode),
    '__TRUSTPILOT_BU_ID__': JSON.stringify(process.env.TRUSTPILOT_BUSINESS_UNIT_ID || ''),
  },

  esbuild: {
    target: 'esnext',
    drop: mode === 'production' ? ['console', 'debugger'] : [],
    logOverride: { 'this-is-undefined-in-esm': 'silent' },
  },

  build: {
    outDir: 'dist',
    sourcemap: false,
    target: 'esnext',
    minify: 'esbuild',
    cssMinify: true,
    reportCompressedSize: false,
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        // Manual chunk strategy — see Task #359 for the full root-cause
        // and the matching audit note in `.local/audits/syrabit-page-load
        // -speed-audit.md`. Post-fix sizes (production build,
        // NODE_ENV=production, measured 2026-04-17):
        //   react-dom : 1,117 kB → 190 kB raw   /  ~280 kB → 60 kB gzipped
        //                (react + react-dom/client + scheduler + react-is)
        //   vendor    :    57 kB → 198 kB raw   /  ~18 kB → 63 kB gzipped
        //                (react-router + @tanstack + @radix-ui only)
        //   entry     : 108 kB raw / 35 kB gzipped
        // dist/index.html modulepreload set is exactly the four chunks
        // the entry statically imports — react-dom, vendor, ui-utils,
        // icons — with no syntax/codemirror leakage onto the
        // landing critical path.
        manualChunks(id) {
          if (!id.includes('node_modules')) return;
          // IMPORTANT: pnpm encodes peer-dep info in directory names
          // (e.g. `<pkg>@x.y_react-dom@19.1.0_react@19.1.0`), so a
          // naive `id.includes('react-dom')` matches every package
          // that has react-dom as a peer dep — pulling CodeMirror,
          // sandpack, lexical, radix, etc. into the react-dom chunk.
          // Match against the *actual* package directory instead:
          // `node_modules/<pkg>/...` (the second `node_modules/` in pnpm
          // layouts: `node_modules/.pnpm/<peerhash>/node_modules/<pkg>/`).
          const has = (pkg) => id.includes(`/node_modules/${pkg}/`);
          const hasScope = (scope) => id.includes(`/node_modules/${scope}/`);

          if (has('recharts') || hasScope('victory') || /\/node_modules\/d3-[^/]+\//.test(id) || id.includes('/node_modules/d3/')) return 'charts';
          if (
            has('react-markdown') ||
            /\/node_modules\/(remark|rehype|micromark|mdast-util|unist-util|hast-util)-[^/]+\//.test(id) ||
            has('unified') || has('vfile') || has('devlop') || has('bail') ||
            has('trough') || has('character-entities') || has('character-entities-html4') ||
            has('character-entities-legacy') || has('character-reference-invalid') ||
            has('decode-named-character-reference') || has('zwitch') ||
            has('property-information') || has('space-separated-tokens') ||
            has('comma-separated-tokens') || has('html-void-elements') ||
            has('ccount') || has('escape-string-regexp') || has('longest-streak') ||
            has('markdown-table') || has('html-url-attributes')
          ) return 'markdown';
          if (has('lucide-react')) return 'icons';
          if (has('react-syntax-highlighter') || has('refractor') || has('prismjs') || has('highlight.js')) return 'syntax';
          // React runtime — keep react + react-dom (client only) + scheduler
          // + react-is together in one chunk. Grouping them avoids the
          // `react-dom <-> vendor` circular chunk that arose when react-dom
          // and react were in different chunks while react-router (in
          // vendor) depended on react-dom.
          if (
            id.includes('/node_modules/react-dom/') &&
            !/\/node_modules\/react-dom\/(server|static|profiling)/.test(id)
          ) return 'react-dom';
          if (id.includes('/node_modules/scheduler/')) return 'react-dom';
          if (
            id.includes('/node_modules/react/') ||
            id.includes('/node_modules/react-is/')
          ) return 'react-dom';
          if (
            has('react-helmet') || has('react-helmet-async') ||
            has('react-hot-toast') || has('sonner') || has('cmdk') ||
            has('class-variance-authority') || has('clsx') || has('tailwind-merge')
          ) return 'ui-utils';
          if (
            has('react-router') || has('react-router-dom') ||
            id.includes('/node_modules/@remix-run/') ||
            id.includes('/node_modules/@tanstack/') ||
            id.includes('/node_modules/@radix-ui/')
          ) return 'vendor';
        },
      },
    },
  },

  optimizeDeps: {
    include: [
      'react',
      'react-dom',
      'react/jsx-dev-runtime',
      'react/jsx-runtime',
      'react-router-dom',
      '@tanstack/react-query',
      'react-markdown',
      'remark-gfm',
    ],
    needsInterop: [
      'react',
      'react-dom',
      'react/jsx-dev-runtime',
      'react/jsx-runtime',
    ],
    extensions: ['.js', '.jsx'],
    rolldownOptions: {
      moduleTypes: { '.js': 'jsx' },
    },
  },
}));
