import { useEffect } from 'react';

const DEFAULT_OG_IMAGE = 'https://syrabit.ai/opengraph.jpg';
const SITE_NAME = 'Syrabit.ai';

/**
 * PageMeta — sets document.title and all SEO meta tags without react-helmet.
 * Uses direct DOM manipulation — safe for SPA (no SSR needed).
 */
export const PageMeta = ({
  title,
  description,
  canonical,
  ogImage,
  keywords,
  ogType = 'website',
}) => {
  const metaTitle   = title       || 'Syrabit.ai – AI-Powered AHSEC & Degree Exam Preparation';
  const metaDesc    = description || 'Prepare for AHSEC Class 11-12 and Degree exams with AI-powered tutoring, syllabus-aligned notes, PYQs, and intelligent revision tools. Free to start.';
  const metaCanon   = canonical   || 'https://syrabit.ai/';
  const metaImage   = ogImage     || DEFAULT_OG_IMAGE;
  const metaKW      = keywords    || 'AHSEC exam prep, Assam board AI tutor, Class 11 12 notes, Degree college prep, B.Com B.A B.Sc, SEBA, AHSEC AI, study notes Assam';

  useEffect(() => {
    document.title = `${metaTitle}`;

    const setMeta = (attr, value, content) => {
      let el = document.querySelector(`meta[${attr}="${CSS.escape(value)}"]`);
      if (!el) {
        el = document.createElement('meta');
        el.setAttribute(attr, value);
        document.head.appendChild(el);
      }
      el.setAttribute('content', content);
    };

    const setLink = (rel, href) => {
      let el = document.querySelector(`link[rel="${rel}"]`);
      if (!el) {
        el = document.createElement('link');
        el.setAttribute('rel', rel);
        document.head.appendChild(el);
      }
      el.setAttribute('href', href);
    };

    // Basic SEO
    setMeta('name', 'description', metaDesc);
    setMeta('name', 'keywords', metaKW);
    setLink('canonical', metaCanon);

    // Open Graph
    setMeta('property', 'og:site_name', SITE_NAME);
    setMeta('property', 'og:locale',    'en_IN');
    setMeta('property', 'og:type',       ogType);
    setMeta('property', 'og:title',      metaTitle);
    setMeta('property', 'og:description', metaDesc);
    setMeta('property', 'og:image',      metaImage);
    setMeta('property', 'og:image:width', '1200');
    setMeta('property', 'og:image:height', '630');
    setMeta('property', 'og:url',        metaCanon);

    // Twitter / X
    setMeta('name', 'twitter:card',        'summary_large_image');
    setMeta('name', 'twitter:site',        '@SyrabitAI');
    setMeta('name', 'twitter:title',       metaTitle);
    setMeta('name', 'twitter:description', metaDesc);
    setMeta('name', 'twitter:image',       metaImage);

    return () => { document.title = SITE_NAME; };
  }, [metaTitle, metaDesc, metaCanon, metaImage, metaKW, ogType]);

  return null;
};
