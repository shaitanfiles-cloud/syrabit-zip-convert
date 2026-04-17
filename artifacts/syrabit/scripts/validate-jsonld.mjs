/**
 * SEO Phase D — JSON-LD schema validator (no test runner needed).
 *
 * Asserts that each `pageType` builder emits a well-formed @graph containing
 * the schema.org node types Google's Rich Results validator expects. Run via:
 *
 *     node artifacts/syrabit/scripts/validate-jsonld.mjs
 *
 * Exits 0 on success, 1 on the first failure (so CI / `pnpm verify` can gate
 * on it without a separate test framework).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  chapterSchema,
  subjectHubSchema,
  libraryLandingSchema,
  homeSchema,
  pyqSchema,
  howToSchema,
  globalSiteSchema,
  extractHowToSteps,
  buildSchemaForPageType,
} from '../src/lib/jsonld.js';

const types = (g) => g['@graph'].map((n) => n['@type']);

test('chapterSchema → Article + LearningResource + WebPage + Breadcrumb (+ FAQ)', () => {
  const data = {
    title: 'Newton’s Third Law — Physics Notes',
    meta_description: 'Notes on Newton’s third law of motion.',
    topic_title: 'Newton’s Third Law',
    chapter_title: 'Laws of Motion',
    subject_name: 'Physics',
    board_name: 'AHSEC',
    class_name: 'Class 12',
    word_count: 1234,
    generated_at: '2026-04-01T00:00:00Z',
    faq_entries: [
      { question: 'What is Newton’s third law?', answer: 'Every action has an equal and opposite reaction.' },
      { question: 'Give an example.', answer: 'Rocket propulsion.' },
    ],
  };
  const url = 'https://syrabit.ai/ahsec/class-12/physics/newtons-third-law';
  const g = chapterSchema(data, url, '/ahsec/class-12/physics');
  assert.equal(g['@context'], 'https://schema.org');
  const t = types(g);
  for (const expected of ['Article', 'LearningResource', 'WebPage', 'BreadcrumbList', 'FAQPage']) {
    assert.ok(t.includes(expected), `chapter graph missing ${expected} (got: ${t.join(', ')})`);
  }
  const bc = g['@graph'].find((n) => n['@type'] === 'BreadcrumbList');
  assert.equal(bc.itemListElement.length, 4);
  assert.equal(bc.itemListElement[3].item, url);
});

test('chapterSchema returns null for missing inputs', () => {
  assert.equal(chapterSchema(null, 'x'), null);
  assert.equal(chapterSchema({ title: 'x' }, ''), null);
});

test('subjectHubSchema → EducationalOrganization + CollectionPage + Course + Breadcrumb', () => {
  const subject = {
    name: 'Physics', slug: 'physics', board_slug: 'ahsec', class_slug: 'class-12',
    board_name: 'AHSEC', class_name: 'Class 12', stream_name: 'Science',
    description: 'Physics notes for AHSEC Class 12 students.',
    chapters: [
      { title: 'Laws of Motion', slug: 'laws-of-motion', description: 'Newton’s laws of motion explained.' },
      { title: 'Work, Energy & Power', slug: 'work-energy-power', description: 'Mechanical energy concepts.' },
    ],
  };
  const url = 'https://syrabit.ai/ahsec/class-12/physics';
  const g = subjectHubSchema(subject, url);
  const t = types(g);
  for (const expected of ['EducationalOrganization', 'CollectionPage', 'Course', 'BreadcrumbList']) {
    assert.ok(t.includes(expected), `subject graph missing ${expected} (got: ${t.join(', ')})`);
  }
  // FAQPage emitted when ≥2 chapters carry descriptions
  assert.ok(t.includes('FAQPage'), 'expected FAQPage when chapters have descriptions');
  const collection = g['@graph'].find((n) => n['@type'] === 'CollectionPage');
  assert.equal(collection.hasPart.length, 2);
  assert.equal(
    collection.hasPart[0].url,
    'https://syrabit.ai/ahsec/class-12/physics/laws-of-motion',
  );
});

test('libraryLandingSchema → Course + ItemList + WebPage + Breadcrumb', () => {
  const subjects = [
    { id: 's1', name: 'Physics', slug: 'physics', boardSlug: 'ahsec', classSlug: 'class-12', boardName: 'AHSEC', className: 'Class 12' },
    { id: 's2', name: 'Chemistry', slug: 'chemistry', boardSlug: 'ahsec', classSlug: 'class-12', boardName: 'AHSEC', className: 'Class 12' },
  ];
  const url = 'https://syrabit.ai/library';
  const g = libraryLandingSchema(subjects, url);
  const t = types(g);
  for (const expected of ['Course', 'ItemList', 'WebPage', 'BreadcrumbList']) {
    assert.ok(t.includes(expected), `library graph missing ${expected} (got: ${t.join(', ')})`);
  }
  const list = g['@graph'].find((n) => n['@type'] === 'ItemList');
  assert.equal(list.numberOfItems, 2);
  assert.equal(
    list.itemListElement[0].item.url,
    'https://syrabit.ai/ahsec/class-12/physics',
  );
});

test('homeSchema → Organization + WebSite + Breadcrumb with SearchAction', () => {
  const g = homeSchema('https://syrabit.ai/');
  const t = types(g);
  for (const expected of ['Organization', 'WebSite', 'BreadcrumbList']) {
    assert.ok(t.includes(expected), `home graph missing ${expected} (got: ${t.join(', ')})`);
  }
  const site = g['@graph'].find((n) => n['@type'] === 'WebSite');
  assert.equal(site.potentialAction['@type'], 'SearchAction');
});

test('buildSchemaForPageType dispatches all known page types', () => {
  assert.equal(buildSchemaForPageType('unknown', {}), null);
  assert.ok(buildSchemaForPageType('home', { url: 'https://syrabit.ai/' }));
  assert.ok(buildSchemaForPageType('library', {
    url: 'https://syrabit.ai/library',
    subjects: [{ id: 's1', name: 'X', slug: 'x', boardSlug: 'b', classSlug: 'c' }],
  }));
  assert.ok(buildSchemaForPageType('pyq', {
    url: 'https://syrabit.ai/pyq/ahsec-2024-physics',
    doc: { slug: 'ahsec-2024-physics', board: 'AHSEC', year: '2024', subject: 'Physics' },
  }));
});

// ── Task #336 additions ────────────────────────────────────────────────

test('globalSiteSchema → Organization + LocalBusiness with Guwahati address', () => {
  const g = globalSiteSchema('https://syrabit.ai/');
  const t = types(g).map(x => Array.isArray(x) ? x[0] : x);
  for (const expected of ['Organization', 'LocalBusiness', 'WebPage']) {
    assert.ok(t.includes(expected), `global graph missing ${expected} (got: ${JSON.stringify(t)})`);
  }
  const lb = g['@graph'].find((n) => n['@type'] === 'LocalBusiness');
  assert.equal(lb.address.addressLocality, 'Guwahati');
  assert.equal(lb.address.addressRegion, 'Assam');
  assert.equal(lb.geo['@type'], 'GeoCoordinates');
  // Stable @id keeps the org node deduplicable across the page.
  const org = g['@graph'].find((n) => Array.isArray(n['@type']) && n['@type'].includes('Organization'));
  assert.equal(org['@id'], 'https://syrabit.ai/#organization');
  assert.deepEqual(org.knowsLanguage, ['en', 'as']);
});

test('extractHowToSteps detects numbered steps and returns >=2 step nodes', () => {
  const md = `
Some intro text.

1. Open the chapter notes
2. Scan the syllabus block for keywords
3. Practice the MCQs at the end
4. Review past papers from the library

Some closing prose.
  `;
  const steps = extractHowToSteps(md);
  assert.equal(steps.length, 4);
  assert.equal(steps[0]['@type'], 'HowToStep');
  assert.equal(steps[0].position, 1);
  assert.match(steps[0].text, /Open the chapter/);
});

test('extractHowToSteps returns [] for prose with a single numbered line', () => {
  assert.equal(extractHowToSteps('Note 1. only one item here').length, 0);
  assert.equal(extractHowToSteps('').length, 0);
  assert.equal(extractHowToSteps(null).length, 0);
});

test('howToSchema builds a HowTo node from string steps', () => {
  const g = howToSchema({
    name: 'Solve a quadratic equation',
    steps: ['Identify a, b, c', 'Apply the discriminant formula', 'Compute the two roots'],
    totalTime: 'PT5M',
    url: 'https://syrabit.ai/learn/quadratics',
  });
  assert.equal(g['@graph'][0]['@type'], 'HowTo');
  assert.equal(g['@graph'][0].step.length, 3);
  assert.equal(g['@graph'][0].totalTime, 'PT5M');
});

test('howToSchema returns null when fewer than 2 steps', () => {
  assert.equal(howToSchema({ name: 'x', steps: ['only one'] }), null);
  assert.equal(howToSchema({ name: 'x', steps: [] }), null);
});

test('chapterSchema appends HowTo when content has numbered steps', () => {
  const data = {
    title: 'Plant Lab Procedure',
    meta_description: 'Step-by-step plant tissue lab.',
    topic_title: 'Plant Lab', chapter_title: 'Lab Manual',
    subject_name: 'Biology', board_name: 'AHSEC', class_name: 'Class 12',
    word_count: 500,
    content: '1. Sterilize the tools\n2. Cut the leaf into 1cm sections\n3. Place on agar plate\n4. Incubate at 25C',
  };
  const g = chapterSchema(data, 'https://syrabit.ai/ahsec/class-12/biology/plant-lab', '/ahsec/class-12/biology');
  const t = types(g);
  assert.ok(t.includes('HowTo'), `expected HowTo in chapter graph (got: ${t.join(', ')})`);
  const howto = g['@graph'].find((n) => n['@type'] === 'HowTo');
  assert.equal(howto.step.length, 4);
});

test('chapterSchema omits dateModified when no real timestamps are provided', () => {
  // Critical: AI crawlers use dateModified for freshness — never bake
  // build-time `new Date()` values into Article schema.
  const g = chapterSchema(
    { title: 'X', meta_description: 'd', topic_title: 'X', subject_name: 'S', board_name: 'B', class_name: 'C' },
    'https://syrabit.ai/x',
    '/s',
  );
  const article = g['@graph'].find((n) => n['@type'] === 'Article');
  assert.equal(article.datePublished, undefined);
  assert.equal(article.dateModified, undefined);
});

test('chapterSchema preserves real timestamps from chapter metadata', () => {
  const g = chapterSchema(
    {
      title: 'X', meta_description: 'd', topic_title: 'X', subject_name: 'S',
      board_name: 'B', class_name: 'C',
      generated_at: '2026-01-02T03:04:05Z',
      updated_at: '2026-04-17T10:20:30Z',
    },
    'https://syrabit.ai/x',
    '/s',
  );
  const article = g['@graph'].find((n) => n['@type'] === 'Article');
  assert.equal(article.datePublished, '2026-01-02T03:04:05Z');
  assert.equal(article.dateModified, '2026-04-17T10:20:30Z');
});

test('pyqSchema → Quiz + LearningResource + Breadcrumb with educational alignment', () => {
  const g = pyqSchema(
    { slug: 'ahsec-2024-physics', board: 'AHSEC', year: '2024', subject: 'Physics', class: 'Class 12' },
    'https://syrabit.ai/pyq/ahsec-2024-physics',
  );
  const t = types(g);
  for (const expected of ['Quiz', 'LearningResource', 'BreadcrumbList']) {
    assert.ok(t.includes(expected), `pyq graph missing ${expected} (got: ${t.join(', ')})`);
  }
  const quiz = g['@graph'].find((n) => n['@type'] === 'Quiz');
  assert.equal(quiz.educationalAlignment.educationalFramework, 'AHSEC');
  assert.equal(quiz.educationalAlignment.targetName, 'Physics');
  assert.equal(quiz.inLanguage, 'en-IN');
});

test('pyqSchema falls back gracefully when only a slug is known', () => {
  const g = pyqSchema({ slug: 'mystery-paper' }, 'https://syrabit.ai/pyq/mystery-paper');
  assert.ok(g);
  const quiz = g['@graph'].find((n) => n['@type'] === 'Quiz');
  assert.match(quiz.name, /mystery-paper/);
});
