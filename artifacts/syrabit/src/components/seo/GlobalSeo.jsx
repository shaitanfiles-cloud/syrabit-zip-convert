import { Helmet } from 'react-helmet-async';
import { globalSiteSchema } from '@/lib/jsonld';

/**
 * Task #336: site-wide structured data injected once at the App root.
 * Emits Organization + LocalBusiness (Guwahati) + a WebPage stub so AI
 * crawlers (ChatGPT, Gemini, Perplexity, Bingbot/Copilot) can resolve
 * the publisher entity on every route — including pages that don't pass
 * a `pageType` to PageMeta. Per-page PageMeta blocks add more specific
 * graphs on top; nothing here gets duplicated because each node uses
 * a stable `@id`.
 */
export default function GlobalSeo() {
  const schema = globalSiteSchema('https://syrabit.ai/');
  return (
    <Helmet>
      <script type="application/ld+json">{JSON.stringify(schema)}</script>
    </Helmet>
  );
}
