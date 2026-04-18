// Task #494: emit per-route static HTML stubs for non-data-driven
// pages so Lighthouse / Googlebot / AI crawlers see the route-specific
// <link rel="canonical"> in the served HTML instead of inheriting the
// homepage URL via the SPA fallback.
//
// These pages do NOT need an SSR snapshot in #root — they hydrate to
// real React content via the existing client bundle. We only rewrite
// the <head> (title, description, canonical, hreflang, og:url,
// twitter:title, twitter:description) so the static document Lighthouse
// inspects matches the actual route. The SPA shell, modulepreload, and
// asset hashes from dist/index.html are preserved unchanged.
//
// Routes covered:
//   /home       (LandingPage — public marketing landing)
//   /pricing
//   /login
//   /signup
//   /terms
//   /privacy
//   /about
//   /technology
//
// /chat and /library are prerendered with full SSR by their dedicated
// scripts; subject + chapter pages by scripts/prerender-routes.mjs.
// Auth-gated routes (/profile, /history, /admin, /onboarding) are not
// emitted here because they should stay noindex via robots.txt.

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const distDir = path.resolve(__dirname, "..", "dist");
const srcHtml = path.join(distDir, "index.html");

const SITE = "https://syrabit.ai";

const ROUTES = [
  {
    path: "/home",
    title:
      "Syrabit.ai — Educational Browser For Assam Board Students",
    description:
      "AI-powered educational browser for AHSEC, SEBA and Degree students in Assam. Browse syllabus content, get instant answers, and study smarter.",
  },
  {
    path: "/pricing",
    title: "Pricing & Plans — Free, Starter & Pro | Syrabit.ai",
    description:
      "Compare Syrabit.ai plans for AHSEC and Degree students. Start free or upgrade to Starter (₹99) or Pro (₹999) for unlimited AI study help.",
  },
  {
    path: "/login",
    title: "Log In to Syrabit.ai",
    description:
      "Sign in to Syrabit.ai to continue your AHSEC, SEBA or Degree exam preparation. Resume your study notes, MCQs, and AI chat history.",
    robots: "noindex, follow",
  },
  {
    path: "/signup",
    title: "Create Your Free Syrabit.ai Account",
    description:
      "Sign up free for Syrabit.ai — the AI-powered study platform built for Assam Board (AHSEC, SEBA) and Degree (B.Com, B.A, B.Sc) students.",
  },
  {
    path: "/terms",
    title: "Terms of Service | Syrabit.ai",
    description:
      "Terms and conditions for using Syrabit.ai — the AI-powered study platform for Assam Board and Degree students.",
  },
  {
    path: "/privacy",
    title: "Privacy Policy | Syrabit.ai",
    description:
      "How Syrabit.ai collects, uses and protects student data on our AI-powered exam preparation platform for AHSEC, SEBA and Degree students.",
  },
  {
    path: "/about",
    title: "About Syrabit.ai — The Educational Browser For Assam",
    description:
      "Learn about Syrabit.ai, the AI-powered study platform built in Guwahati for AHSEC (Class 11-12), SEBA, and Degree students across Assam.",
  },
  {
    path: "/technology",
    title: "Technology Behind Syrabit.ai — RAG, AI Tutors & Speed",
    description:
      "How Syrabit.ai combines retrieval-augmented generation, AI tutors and Cloudflare's edge to deliver fast, syllabus-grounded answers for Assam students.",
  },
];

function escapeHtml(s = "") {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function rewriteHead(html, { title, description, canonical, robots }) {
  html = html.replace(
    /<title>[^<]*<\/title>/,
    `<title>${escapeHtml(title)}</title>`,
  );
  html = html.replace(
    /<meta name="description" content="[^"]*"\s*\/?>(\n)?/,
    `<meta name="description" content="${escapeHtml(description)}" />\n    `,
  );

  // Insert canonical + hreflang. Swap if a placeholder exists (legacy
  // build), else inject before </head> so Lighthouse always sees one
  // canonical tag pointing to the real route.
  if (/<link rel="canonical" href="[^"]*"\s*\/?>(\n)?/.test(html)) {
    html = html.replace(
      /<link rel="canonical" href="[^"]*"\s*\/?>(\n)?/,
      `<link rel="canonical" href="${canonical}" />\n    `,
    );
  } else {
    html = html.replace(
      /<\/head>/,
      `    <link rel="canonical" href="${canonical}" />\n` +
      `    <link rel="alternate" hreflang="en-IN" href="${canonical}" />\n  </head>`,
    );
  }

  // og:url + matching titles/descriptions
  html = html.replace(
    /<meta property="og:url" content="[^"]*"\s*\/?>/,
    `<meta property="og:url" content="${canonical}" />`,
  );
  html = html.replace(
    /<meta property="og:title" content="[^"]*"\s*\/?>/,
    `<meta property="og:title" content="${escapeHtml(title)}" />`,
  );
  html = html.replace(
    /<meta property="og:description" content="[^"]*"\s*\/?>/,
    `<meta property="og:description" content="${escapeHtml(description)}" />`,
  );
  html = html.replace(
    /<meta name="twitter:title" content="[^"]*"\s*\/?>/,
    `<meta name="twitter:title" content="${escapeHtml(title)}" />`,
  );
  html = html.replace(
    /<meta name="twitter:description" content="[^"]*"\s*\/?>/,
    `<meta name="twitter:description" content="${escapeHtml(description)}" />`,
  );

  // Optional per-route robots override (e.g. /login is noindex,follow).
  if (robots) {
    if (/<meta name="robots" content="[^"]*"\s*\/?>/.test(html)) {
      html = html.replace(
        /<meta name="robots" content="[^"]*"\s*\/?>/,
        `<meta name="robots" content="${escapeHtml(robots)}" />`,
      );
    } else {
      html = html.replace(
        /<\/head>/,
        `    <meta name="robots" content="${escapeHtml(robots)}" />\n  </head>`,
      );
    }
  }

  return html;
}

function main() {
  if (!fs.existsSync(srcHtml)) {
    console.warn(
      `[prerender-static-routes] dist/index.html not found at ${srcHtml}; skipping`,
    );
    return;
  }

  const baseHtml = fs.readFileSync(srcHtml, "utf-8");
  let written = 0;
  const summary = [];

  for (const route of ROUTES) {
    const canonical = `${SITE}${route.path}`;
    const outDir = path.join(distDir, route.path.replace(/^\//, ""));
    const outFile = path.join(outDir, "index.html");

    // Don't overwrite a real SSR'd prerender if one already exists for
    // this path (e.g. some future task adds full SSR for /pricing).
    if (fs.existsSync(outFile)) {
      const existing = fs.readFileSync(outFile, "utf-8");
      if (/data-hydrate="[a-z]+"/.test(existing)) {
        console.log(
          `[prerender-static-routes] skipping ${route.path} — full SSR snapshot already present`,
        );
        continue;
      }
    }

    const html = rewriteHead(baseHtml, {
      title: route.title,
      description: route.description,
      canonical,
      robots: route.robots,
    });

    // Hard assertion: exactly one <link rel="canonical"> with the
    // expected href. Catches accidental regressions where a stray
    // placeholder canonical leaks into the static template again.
    const canonicalTags =
      html.match(/<link\s+rel="canonical"\s+href="[^"]*"[^>]*>/g) || [];
    if (canonicalTags.length !== 1) {
      throw new Error(
        `[prerender-static-routes] ${route.path}: expected exactly 1 canonical tag, found ${canonicalTags.length}`,
      );
    }
    if (!canonicalTags[0].includes(`href="${canonical}"`)) {
      throw new Error(
        `[prerender-static-routes] ${route.path}: canonical points to wrong URL — ${canonicalTags[0]}`,
      );
    }

    fs.mkdirSync(outDir, { recursive: true });
    fs.writeFileSync(outFile, html);
    written++;
    summary.push({ path: route.path, canonical });
    console.log(
      `[prerender-static-routes] wrote ${path.relative(distDir, outFile)} ` +
        `(canonical=${canonical}${route.robots ? `, robots=${route.robots}` : ""})`,
    );
  }

  console.log(
    `[prerender-static-routes] done — ${written}/${ROUTES.length} static-route stubs written`,
  );

  // Persist a tiny manifest so verify-canonicals.mjs can iterate over
  // the exact set of routes this script claims to have produced.
  fs.writeFileSync(
    path.join(distDir, "prerender-static-manifest.json"),
    JSON.stringify(
      { generated_at: new Date().toISOString(), routes: summary },
      null,
      2,
    ),
  );
}

main();
