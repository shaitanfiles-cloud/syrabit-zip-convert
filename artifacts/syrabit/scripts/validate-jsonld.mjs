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
});
