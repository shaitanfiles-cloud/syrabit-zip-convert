import { useEffect } from 'react';

const DEFAULT_OG_IMAGE =
  'https://images.unsplash.com/photo-1652380277180-9b31dbc96a51?crop=entropy&cs=tinysrgb&fit=crop&fm=jpg&h=630&w=1200&q=80';

/**
 * PageMeta — sets document.title and meta tags without react-helmet-async.
 * Uses direct DOM manipulation (safe for CRA single-page apps).
 */
export const PageMeta = ({
  title,
  description,
  canonical,
  ogImage,
}) => {
  const metaTitle = title || 'Syrabit.ai – AI-Powered AHSEC Exam Preparation';
  const metaDesc = description || 'Prepare for AHSEC exams with AI-powered tutoring, structured syllabus notes, and intelligent revision tools.';
  const metaCanonical = canonical || 'https://syrabit.ai/';
  const metaImage = ogImage || DEFAULT_OG_IMAGE;

  useEffect(() => {
    // Title
    document.title = metaTitle;

    // Helper to set/create meta tag
    const setMeta = (attr, value, content) => {
      let el = document.querySelector(`meta[${attr}="${value}"]`);
      if (!el) {
        el = document.createElement('meta');
        el.setAttribute(attr, value);
        document.head.appendChild(el);
      }
      el.setAttribute('content', content);
    };

    // Helper to set/create link tag
    const setLink = (rel, href) => {
      let el = document.querySelector(`link[rel="${rel}"]`);
      if (!el) {
        el = document.createElement('link');
        el.setAttribute('rel', rel);
        document.head.appendChild(el);
      }
      el.setAttribute('href', href);
    };

    setMeta('name', 'description', metaDesc);
    setLink('canonical', metaCanonical);
    setMeta('property', 'og:title', metaTitle);
    setMeta('property', 'og:description', metaDesc);
    setMeta('property', 'og:image', metaImage);
    setMeta('property', 'og:type', 'website');
    setMeta('property', 'og:url', metaCanonical);
    setMeta('name', 'twitter:card', 'summary_large_image');
    setMeta('name', 'twitter:title', metaTitle);
    setMeta('name', 'twitter:description', metaDesc);
    setMeta('name', 'twitter:image', metaImage);

    return () => {
      // Reset title on unmount
      document.title = 'Syrabit.ai';
    };
  }, [metaTitle, metaDesc, metaCanonical, metaImage]);

  return null;
};
