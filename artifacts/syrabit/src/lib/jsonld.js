/**
 * SEO Phase D / Task #336 — Per-page-type JSON-LD schema builders.
 *
 * Pure functions, no side effects. Each returns a schema.org @graph
 * array suitable for embedding in a single <script type="application/ld+json">
 * tag (or to be passed to PageMeta's `jsonLd` prop).
 *
 * Builders:
 *   chapterSchema(data, url, basePath)      — Article + LearningResource + WebPage + BreadcrumbList (+ FAQPage, HowTo)
 *   subjectHubSchema(subject, url)          — EducationalOrganization + CollectionPage + BreadcrumbList (+ Course, FAQPage)
 *   libraryLandingSchema(subjects, url)     — Course + ItemList + WebPage + BreadcrumbList
 *   homeSchema(url)                         — Organization + WebSite + BreadcrumbList
 *   pyqSchema(doc, url)                     — Quiz + LearningResource + BreadcrumbList
 *   howToSchema({ name, steps, ... })       — HowTo node (used standalone or merged into a chapter graph)
 *   globalSiteSchema(url)                   — Organization + LocalBusiness (Guwahati) for the global head
 */

const SITE_ORIGIN = 'https://syrabit.ai';
const SITE_LOGO = `${SITE_ORIGIN}/icons/icon-192x192.png`;
const ORG_NODE = {
  '@type': 'Organization',
  name: 'Syrabit.ai',
  url: SITE_ORIGIN,
  logo: { '@type': 'ImageObject', url: SITE_LOGO },
};

// Single source of truth for the publisher's address/geo. Reused by the
// chapter Article publisher node, the global LocalBusiness emission, and
// any future PostalAddress consumers so the AI crawlers see the exact
// same locality string everywhere ("Guwahati, Assam").
const SYRABIT_ADDRESS = {
  '@type': 'PostalAddress',
  addressLocality: 'Guwahati',
  addressRegion: 'Assam',
  addressCountry: 'IN',
};
const SYRABIT_GEO = {
  '@type': 'GeoCoordinates',
  latitude: 26.1445,
  longitude: 91.7362,
};

/**
 * Detect numbered / stepwise content in a markdown-ish body and return
 * a HowToStep[] array. Returns [] when no procedural pattern is found
 * so callers can short-circuit. Patterns recognized:
 *   • lines starting with "1.", "2.", … "n."
 *   • lines starting with "Step 1:", "Step 2 —", etc.
 * Steps are capped at 12 to keep the schema lean for SERP cards.
 */
export function extractHowToSteps(content) {
  if (!content || typeof content !== 'string') return [];
  const lines = content.split(/\r?\n/);
  const steps = [];
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;
    const m = line.match(/^(?:\*\*)?(?:Step\s+)?(\d{1,2})[.):\-—]\s+(.{8,300})$/i);
    if (m) {
      const text = m[2].replace(/\*\*/g, '').trim();
      if (text) steps.push({ position: parseInt(m[1], 10), text });
      if (steps.length >= 12) break;
    }
  }
  // Require at least 2 distinct steps to avoid emitting HowTo for a
  // single bullet that happens to start with "1." in prose.
  if (steps.length < 2) return [];
  steps.sort((a, b) => a.position - b.position);
  return steps.map((s, i) => ({
    '@type': 'HowToStep',
    position: i + 1,
    name: s.text.split(/[.!?:]/, 1)[0].slice(0, 110),
    text: s.text,
  }));
}

/**
 * Site-wide JSON-LD: Organization + LocalBusiness (Guwahati). Mounted
 * once globally via <GlobalSeo />. Centralizes the publisher entity so
 * AI crawlers consistently identify Syrabit.ai across every page.
 */
export function globalSiteSchema(url) {
  const homeUrl = url || `${SITE_ORIGIN}/`;
  return {
    '@context': 'https://schema.org',
    '@graph': [
      {
        '@type': ['Organization', 'EducationalOrganization'],
        '@id': `${SITE_ORIGIN}/#organization`,
        name: 'Syrabit.ai',
        alternateName: 'Syrabit',
        url: SITE_ORIGIN,
        logo: { '@type': 'ImageObject', url: SITE_LOGO, width: 192, height: 192 },
        sameAs: [SITE_ORIGIN],
        address: SYRABIT_ADDRESS,
        areaServed: { '@type': 'AdministrativeArea', name: 'Assam, India' },
        knowsLanguage: ['en', 'as'],
      },
      {
        '@type': 'LocalBusiness',
        '@id': `${SITE_ORIGIN}/#localbusiness`,
        name: 'Syrabit.ai',
        url: SITE_ORIGIN,
        image: SITE_LOGO,
        priceRange: '₹₹',
        address: SYRABIT_ADDRESS,
        geo: SYRABIT_GEO,
        areaServed: { '@type': 'AdministrativeArea', name: 'Assam, India' },
        parentOrganization: { '@id': `${SITE_ORIGIN}/#organization` },
      },
      {
        '@type': 'WebPage',
        '@id': homeUrl,
        url: homeUrl,
        isPartOf: { '@type': 'WebSite', '@id': SITE_ORIGIN, name: 'Syrabit.ai' },
        publisher: { '@id': `${SITE_ORIGIN}/#organization` },
      },
    ],
  };
}

/** Standalone HowTo builder. Pass `steps` (string[] | HowToStep[]). */
export function howToSchema({ name, description, steps, totalTime, inLanguage = 'en-IN', url }) {
  const stepNodes = (steps || []).map((s, i) => {
    if (s && typeof s === 'object' && s['@type'] === 'HowToStep') {
      return { ...s, position: s.position || i + 1 };
    }
    const text = String(s || '').trim();
    if (!text) return null;
    return {
      '@type': 'HowToStep',
      position: i + 1,
      name: text.split(/[.!?:]/, 1)[0].slice(0, 110),
      text,
    };
  }).filter(Boolean);
  if (stepNodes.length < 2) return null;
  const node = {
    '@type': 'HowTo',
    name: name || 'How To',
    description: description || `${name || 'Step-by-step guide'} — ${stepNodes.length} steps.`,
    inLanguage,
    step: stepNodes,
  };
  if (totalTime) node.totalTime = totalTime;
  if (url) node.url = url;
  return { '@context': 'https://schema.org', '@graph': [node] };
}

function _kw(chapterTitle, subjectName, boardName, className) {
  const words = (chapterTitle || '').split(/[\s,\-–—/&]+/).filter(w => w.length > 2);
  const kws = [
    chapterTitle, subjectName, boardName, ...words,
    `${chapterTitle} notes`, `${chapterTitle} definition`, `${chapterTitle} MCQ`,
    `${chapterTitle} ${subjectName}`, `${chapterTitle} ${boardName} ${className}`,
  ].filter(Boolean);
  return [...new Set(kws.map(k => String(k).toLowerCase()))].join(', ');
}

export function chapterSchema(data, url, basePath = '') {
  if (!data || !url) return null;
  const subjectName = data.subject_name || '';
  const boardName = data.board_name || '';
  const className = data.class_name || '';
  const chapterTitle = data.topic_title || data.chapter_title || '';
  const subjectUrl = basePath ? `${SITE_ORIGIN}${basePath}` : SITE_ORIGIN;

  const aboutThings = [{ '@type': 'Thing', name: chapterTitle }];
  const words = chapterTitle.split(/[\s,\-–—/&]+/).filter(w => w.length > 2);
  words.slice(0, 5).forEach(w => aboutThings.push({ '@type': 'Thing', name: w }));
  if (data.chapter_title && data.chapter_title !== chapterTitle) {
    aboutThings.push({ '@type': 'Thing', name: data.chapter_title });
  }

  // Real timestamps only — never bake build-time dates into Article
  // metadata, since AI crawlers use dateModified to decide whether the
  // page is fresh enough to cite. If we have neither generated_at nor
  // updated_at, drop the field rather than fabricate one.
  const datePublished = data.generated_at || data.created_at || data.published_at || null;
  const dateModified = data.updated_at || data.modified_at || datePublished || null;

  const articleNode = {
    '@type': 'Article',
    headline: data.title,
    description: data.meta_description,
    url,
    author: {
      '@type': ['Organization', 'EducationalOrganization'],
      name: 'Syrabit.ai',
      url: SITE_ORIGIN,
    },
    publisher: { ...ORG_NODE, address: SYRABIT_ADDRESS },
    educationalLevel: `${className} ${boardName}`.trim(),
    about: aboutThings.length > 1 ? aboutThings : aboutThings[0],
    keywords: _kw(chapterTitle, subjectName, boardName, className),
    wordCount: data.word_count || 0,
    inLanguage: data.has_assamese ? ['en-IN', 'as-IN'] : 'en-IN',
    mainEntityOfPage: { '@type': 'WebPage', '@id': url },
    image: `${SITE_ORIGIN}/opengraph.jpg`,
  };
  if (datePublished) articleNode.datePublished = datePublished;
  if (dateModified) articleNode.dateModified = dateModified;

  const graph = [
    articleNode,
    {
      '@type': 'LearningResource',
      name: chapterTitle,
      description: data.meta_description,
      educationalLevel: `${className} ${boardName}`.trim(),
      learningResourceType: 'Study Notes',
      teaches: chapterTitle,
      provider: { '@type': 'Organization', name: 'Syrabit.ai', url: SITE_ORIGIN },
      inLanguage: 'en-IN',
      isAccessibleForFree: true,
      url,
    },
    {
      '@type': 'WebPage',
      '@id': url,
      name: data.title,
      speakable: {
        '@type': 'SpeakableSpecification',
        cssSelector: ['article h1', 'article > p:first-of-type', 'article h2'],
      },
    },
    {
      '@type': 'BreadcrumbList',
      itemListElement: [
        { '@type': 'ListItem', position: 1, name: 'Home', item: `${SITE_ORIGIN}/` },
        { '@type': 'ListItem', position: 2, name: 'Library', item: `${SITE_ORIGIN}/library` },
        { '@type': 'ListItem', position: 3, name: subjectName, item: subjectUrl },
        { '@type': 'ListItem', position: 4, name: chapterTitle, item: url },
      ],
    },
  ];

  const faq = Array.isArray(data.faq_entries) ? data.faq_entries : [];
  if (faq.length >= 2) {
    graph.push({
      '@type': 'FAQPage',
      mainEntity: faq.slice(0, 10).map(q => ({
        '@type': 'Question',
        name: q.question || q.name,
        acceptedAnswer: { '@type': 'Answer', text: q.answer || q.text },
      })),
    });
  }

  // Task #336: detect numbered/stepwise content in chapter body and
  // emit a HowTo node so AI assistants can surface step-by-step
  // procedural answers (rocket-science derivations, lab procedures,
  // exam-prep workflows). The chapter title doubles as the HowTo name.
  const howToSteps = extractHowToSteps(data.content || '');
  if (howToSteps.length >= 2) {
    graph.push({
      '@type': 'HowTo',
      name: chapterTitle,
      description: data.meta_description || `${chapterTitle} — step-by-step.`,
      inLanguage: 'en-IN',
      step: howToSteps,
    });
  }

  return { '@context': 'https://schema.org', '@graph': graph };
}

/**
 * Task #336: schema for PYQ (Previous Year Question paper) replicas.
 * Emits Quiz + LearningResource + BreadcrumbList. Doc shape mirrors
 * what the worker returns from `/pyq/{slug}`:
 *   { slug, title, description?, board?, year?, subject?, class?, exam? }
 */
export function pyqSchema(doc, url) {
  if (!doc || !url) return null;
  const slug = doc.slug || '';
  const title = doc.title || `Previous Year Question Paper — ${slug}`;
  const subject = doc.subject || doc.subject_name || '';
  const board = doc.board || doc.board_name || '';
  const className = doc.class || doc.class_name || '';
  const year = doc.year || doc.exam_year || '';
  const description = doc.description
    || `${board ? board + ' ' : ''}${subject ? subject + ' ' : ''}${year ? year + ' ' : ''}previous year question paper for ${className || 'students'}.`;
  const eduLevel = `${className} ${board}`.trim() || 'Higher Secondary';

  return {
    '@context': 'https://schema.org',
    '@graph': [
      {
        '@type': 'Quiz',
        '@id': url,
        name: title,
        description,
        url,
        about: subject ? { '@type': 'Thing', name: subject } : undefined,
        educationalLevel: eduLevel,
        educationalAlignment: board
          ? {
              '@type': 'AlignmentObject',
              alignmentType: 'educationalSubject',
              educationalFramework: board,
              targetName: subject || 'General',
            }
          : undefined,
        learningResourceType: 'Question Paper',
        inLanguage: 'en-IN',
        author: { '@type': 'Organization', name: board || 'Syrabit.ai' },
        publisher: ORG_NODE,
      },
      {
        '@type': 'LearningResource',
        name: title,
        description,
        url,
        learningResourceType: 'Past Examination Paper',
        educationalLevel: eduLevel,
        inLanguage: 'en-IN',
        isAccessibleForFree: true,
        provider: ORG_NODE,
        license: 'https://syrabit.ai/terms',
      },
      {
        '@type': 'BreadcrumbList',
        itemListElement: [
          { '@type': 'ListItem', position: 1, name: 'Home', item: `${SITE_ORIGIN}/` },
          { '@type': 'ListItem', position: 2, name: 'Library', item: `${SITE_ORIGIN}/library` },
          { '@type': 'ListItem', position: 3, name: title, item: url },
        ],
      },
    ],
  };
}

export function subjectHubSchema(subject, url) {
  if (!subject || !url) return null;
  const eduLevel = ((subject.class_name || '') + ' ' + (subject.board_name || '') + ' ' + (subject.stream_name || '')).replace(/\s+/g, ' ').trim() || 'FYUGP';
  const description = subject.description || `Complete ${subject.name} notes and study material for ${eduLevel} students.`;
  const chapters = Array.isArray(subject.chapters) ? subject.chapters : [];

  const graph = [
    {
      '@type': 'EducationalOrganization',
      name: 'Syrabit.ai',
      url: SITE_ORIGIN,
      logo: `${SITE_ORIGIN}/icons/icon-192x192.png`,
      sameAs: [SITE_ORIGIN],
    },
    {
      '@type': 'CollectionPage',
      '@id': url,
      name: `${subject.name} — ${eduLevel}`,
      description,
      url,
      isPartOf: { '@type': 'WebSite', '@id': SITE_ORIGIN, name: 'Syrabit.ai' },
      inLanguage: 'en-IN',
      hasPart: chapters.slice(0, 50).map(ch => ({
        '@type': 'LearningResource',
        name: ch.title,
        url: subject.board_slug && subject.class_slug && subject.slug && ch.slug
          ? `${SITE_ORIGIN}/${subject.board_slug}/${subject.class_slug}/${subject.slug}/${ch.slug}`
          : undefined,
        learningResourceType: 'Study Notes',
        inLanguage: 'en-IN',
      })),
    },
    {
      '@type': 'Course',
      name: `${subject.name} — ${eduLevel}`,
      description,
      provider: { '@type': 'Organization', name: 'Syrabit.ai', sameAs: SITE_ORIGIN },
      educationalLevel: eduLevel,
      url,
      inLanguage: 'en-IN',
    },
    {
      '@type': 'BreadcrumbList',
      itemListElement: [
        { '@type': 'ListItem', position: 1, name: 'Home', item: `${SITE_ORIGIN}/` },
        { '@type': 'ListItem', position: 2, name: 'Library', item: `${SITE_ORIGIN}/library` },
        { '@type': 'ListItem', position: 3, name: subject.name, item: url },
      ],
    },
  ];

  const faqEntries = [];
  for (const ch of chapters) {
    if (ch.title && ch.description && ch.description.length > 10) {
      faqEntries.push({
        '@type': 'Question',
        name: `What is ${ch.title}?`,
        acceptedAnswer: { '@type': 'Answer', text: ch.description },
      });
    }
    if (faqEntries.length >= 10) break;
  }
  if (faqEntries.length >= 2) {
    graph.push({ '@type': 'FAQPage', mainEntity: faqEntries });
  }

  return { '@context': 'https://schema.org', '@graph': graph };
}

export function libraryLandingSchema(subjects, url) {
  if (!Array.isArray(subjects) || subjects.length === 0 || !url) return null;
  const items = subjects.map((s, i) => ({
    '@type': 'ListItem',
    position: i + 1,
    item: {
      '@type': 'LearningResource',
      name: s.name,
      description: s.description || `Study ${s.name} — ${s.boardName || ''} ${s.className || ''}`.trim(),
      url: s.boardSlug && s.classSlug && s.slug
        ? `${SITE_ORIGIN}/${s.boardSlug}/${s.classSlug}/${s.slug}`
        : `${SITE_ORIGIN}/subject/${s.id}`,
      provider: { '@type': 'Organization', name: 'Syrabit.ai', url: SITE_ORIGIN },
      educationalLevel: `${s.className || ''} ${s.boardName || ''}`.trim(),
      inLanguage: 'en-IN',
      isAccessibleForFree: true,
    },
  }));

  return {
    '@context': 'https://schema.org',
    '@graph': [
      {
        '@type': 'Course',
        name: 'Syrabit.ai — Assam Board Study Library',
        description: 'Course catalogue covering AHSEC, SEBA and FYUGP subjects with AI-generated notes, MCQs, definitions and exam prep.',
        provider: { '@type': 'Organization', name: 'Syrabit.ai', sameAs: SITE_ORIGIN },
        educationalLevel: 'Higher Secondary, Undergraduate',
        url,
        inLanguage: 'en-IN',
        hasCourseInstance: {
          '@type': 'CourseInstance',
          courseMode: 'online',
          courseWorkload: 'PT1H',
          inLanguage: 'en-IN',
        },
      },
      {
        '@type': 'ItemList',
        name: 'Assamboard Subject Library',
        description: 'Complete study material library for Assam Board (AHSEC/SEBA/FYUGP) students.',
        numberOfItems: items.length,
        itemListElement: items,
      },
      {
        '@type': 'WebPage',
        '@id': url,
        name: 'Assamboard Subject Library — Study Notes, MCQs & Exam Prep',
        url,
        isPartOf: { '@type': 'WebSite', '@id': SITE_ORIGIN, name: 'Syrabit.ai' },
        inLanguage: 'en-IN',
      },
      {
        '@type': 'BreadcrumbList',
        itemListElement: [
          { '@type': 'ListItem', position: 1, name: 'Home', item: SITE_ORIGIN },
          { '@type': 'ListItem', position: 2, name: 'Library', item: url },
        ],
      },
    ],
  };
}

export function homeSchema(url) {
  const homeUrl = url || `${SITE_ORIGIN}/`;
  return {
    '@context': 'https://schema.org',
    '@graph': [
      {
        '@type': 'Organization',
        '@id': `${SITE_ORIGIN}/#organization`,
        name: 'Syrabit.ai',
        url: SITE_ORIGIN,
        logo: { '@type': 'ImageObject', url: `${SITE_ORIGIN}/icons/icon-192x192.png` },
        sameAs: [SITE_ORIGIN],
      },
      {
        '@type': 'WebSite',
        '@id': SITE_ORIGIN,
        url: SITE_ORIGIN,
        name: 'Syrabit.ai',
        publisher: { '@id': `${SITE_ORIGIN}/#organization` },
        inLanguage: 'en-IN',
        potentialAction: {
          '@type': 'SearchAction',
          target: {
            '@type': 'EntryPoint',
            urlTemplate: `${SITE_ORIGIN}/library?q={search_term_string}`,
          },
          'query-input': 'required name=search_term_string',
        },
      },
      {
        '@type': 'BreadcrumbList',
        itemListElement: [
          { '@type': 'ListItem', position: 1, name: 'Home', item: homeUrl },
        ],
      },
    ],
  };
}

export function buildSchemaForPageType(pageType, payload) {
  switch (pageType) {
    case 'chapter':
      return chapterSchema(payload?.data, payload?.url, payload?.basePath);
    case 'subject':
      return subjectHubSchema(payload?.subject, payload?.url);
    case 'library':
      return libraryLandingSchema(payload?.subjects, payload?.url);
    case 'home':
      return homeSchema(payload?.url);
    case 'pyq':
      return pyqSchema(payload?.doc, payload?.url);
    default:
      return null;
  }
}
