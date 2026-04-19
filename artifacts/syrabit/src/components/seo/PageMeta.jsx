// React 19 natively hoists <title>, <meta>, <link>, and
// <script type="application/ld+json"> to <head> from anywhere in the tree
// AND keeps SSR/client output identical so hydration matches. We previously
// used react-helmet-async, but on React 19 it emitted these tags inline in
// the SSR body while emitting nothing on the client first render —
// triggering React error #418 (hydration mismatch) on every prerendered
// page. Render the tags directly; React handles hoisting + dedupe.
import { buildSchemaForPageType, dedupeGraphTypes } from "@/lib/jsonld";

export default function PageMeta({
  title,
  description,
  url,
  image = "https://syrabit.ai/opengraph.jpg",
  keywords,
  type = "website",
  section,
  tags,
  publishedTime,
  modifiedTime,
  jsonLd,
  pageType,
  pageData,
  hasAssamese = false,
}) {
  const siteName = "Syrabit.ai";
  const absImage = image.startsWith("http") ? image : `https://syrabit.ai${image}`;

  // Per-page-type JSON-LD (Phase D, Plan 9). When a `pageType` is supplied,
  // build the canonical schema graph for that page type and merge it with any
  // page-supplied `jsonLd` so legacy callers keep working.
  const externalLd = jsonLd ? (Array.isArray(jsonLd) ? jsonLd : [jsonLd]) : [];
  const rawTyped = pageType ? buildSchemaForPageType(pageType, { url, ...(pageData || {}) }) : null;
  // Deduplicate schema.org @types so the same type (e.g. FAQPage) is never
  // emitted twice when a caller supplies its own jsonLd alongside the
  // per-page-type builder output. BreadcrumbList / WebPage are always kept.
  const typedSchema = rawTyped ? dedupeGraphTypes(rawTyped, externalLd) : null;
  const allLd = [
    ...(typedSchema && Array.isArray(typedSchema['@graph']) && typedSchema['@graph'].length ? [typedSchema] : []),
    ...externalLd,
  ];

  // Phase E (Plan 7): bilingual hreflang alternates. When an Assamese variant
  // exists for this URL, emit en/as/x-default link tags so Google indexes both
  // language versions instead of treating the AS page as a duplicate. The AS
  // variant is the same URL with `?lang=as` (i18n routing convention is a
  // client-side query param, not a path prefix).
  const asUrl = url ? (url.includes("?") ? `${url}&lang=as` : `${url}?lang=as`) : null;

  // Mirror react-helmet-async titleTemplate behavior locally so existing
  // callers that pass a bare `title` continue to get the "%s | Syrabit.ai"
  // suffix in <title>.
  const finalTitle = title ? `${title} | ${siteName}` : siteName;

  return (
    <>
      <title>{finalTitle}</title>
      <meta name="description" content={description} />
      {keywords && <meta name="keywords" content={keywords} />}

      <link rel="canonical" href={url} />

      {/* OpenGraph */}
      <meta property="og:site_name" content={siteName} />
      <meta property="og:locale" content="en_IN" />
      <meta property="og:title" content={title} />
      <meta property="og:description" content={description} />
      <meta property="og:type" content={type} />
      <meta property="og:url" content={url} />
      <meta property="og:image" content={absImage} />
      <meta property="og:image:width" content="1200" />
      <meta property="og:image:height" content="630" />
      {type === "article" && section && <meta property="article:section" content={section} />}
      {type === "article" && tags && tags.map((tag) => (
        <meta key={tag} property="article:tag" content={tag} />
      ))}
      {type === "article" && publishedTime && <meta property="article:published_time" content={publishedTime} />}
      {type === "article" && modifiedTime && <meta property="article:modified_time" content={modifiedTime} />}

      {/* Twitter */}
      <meta name="twitter:card" content="summary_large_image" />
      <meta name="twitter:site" content="@SyrabitAI" />
      <meta name="twitter:title" content={title} />
      <meta name="twitter:description" content={description} />
      <meta name="twitter:image" content={absImage} />

      {/* GEO targeting */}
      <meta name="geo.region" content="IN-AS" />
      <meta name="geo.placename" content="Assam, India" />
      <meta name="geo.position" content="26.2006;92.9376" />
      <meta name="ICBM" content="26.2006, 92.9376" />
      <meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large" />
      <meta httpEquiv="content-language" content="en-IN" />
      {hasAssamese && asUrl ? (
        <link rel="alternate" hrefLang="en" href={url} />
      ) : (
        <link rel="alternate" hrefLang="en-IN" href={url} />
      )}
      {hasAssamese && asUrl && <link rel="alternate" hrefLang="as" href={asUrl} />}
      {hasAssamese && asUrl && <link rel="alternate" hrefLang="x-default" href={url} />}

      {allLd.map((ld, i) => (
        <script key={i} type="application/ld+json">
          {JSON.stringify(ld)}
        </script>
      ))}
    </>
  );
}
