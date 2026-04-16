/**
 * SEO Phase D — Per-page-type JSON-LD schema builders.
 *
 * Pure functions, no side effects. Each returns a schema.org @graph
 * array suitable for embedding in a single <script type="application/ld+json">
 * tag (or to be passed to PageMeta's `jsonLd` prop).
 *
 * Builders:
 *   chapterSchema(data, url, basePath)      — Article + LearningResource + WebPage + BreadcrumbList (+ FAQPage)
 *   subjectHubSchema(subject, url)          — EducationalOrganization + CollectionPage + BreadcrumbList (+ Course, FAQPage)
 *   libraryLandingSchema(subjects, url)     — Course + ItemList + WebPage + BreadcrumbList
 *   homeSchema(url)                         — Organization + WebSite + BreadcrumbList
 */

const SITE_ORIGIN = 'https://syrabit.ai';
const ORG_NODE = {
  '@type': 'Organization',
  name: 'Syrabit.ai',
  url: SITE_ORIGIN,
  logo: { '@type': 'ImageObject', url: `${SITE_ORIGIN}/icons/icon-192x192.png` },
};

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

  const graph = [
    {
      '@type': 'Article',
      headline: data.title,
      description: data.meta_description,
      url,
      author: { '@type': 'Organization', name: 'Syrabit.ai', url: SITE_ORIGIN },
      publisher: ORG_NODE,
      datePublished: data.generated_at || new Date().toISOString(),
      dateModified: data.updated_at || data.generated_at || new Date().toISOString(),
      educationalLevel: `${className} ${boardName}`.trim(),
      about: aboutThings.length > 1 ? aboutThings : aboutThings[0],
      keywords: _kw(chapterTitle, subjectName, boardName, className),
      wordCount: data.word_count || 0,
      inLanguage: 'en-IN',
      mainEntityOfPage: { '@type': 'WebPage', '@id': url },
      image: `${SITE_ORIGIN}/opengraph.jpg`,
    },
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

  return { '@context': 'https://schema.org', '@graph': graph };
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
    default:
      return null;
  }
}
