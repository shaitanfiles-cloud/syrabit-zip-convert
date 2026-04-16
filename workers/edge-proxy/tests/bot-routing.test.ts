import { describe, it, expect } from "vitest";
import { getBotPageCacheKey, getBotCacheTtl } from "../src/index";

describe("getBotPageCacheKey", () => {
  describe("static pages", () => {
    it.each([
      ["/", "bot:static:/"],
      ["/home", "bot:static:/home"],
      ["/library", "bot:static:/library"],
      ["/pricing", "bot:static:/pricing"],
      ["/terms", "bot:static:/terms"],
      ["/privacy", "bot:static:/privacy"],
      ["/about", "bot:static:/about"],
      ["/curriculum", "bot:static:/curriculum"],
      ["/exam-routine", "bot:static:/exam-routine"],
      ["/chat", "bot:static:/chat"],
    ])("returns static cache key for %s", (path, expected) => {
      expect(getBotPageCacheKey(path)).toBe(expected);
    });

    it("strips trailing slash", () => {
      expect(getBotPageCacheKey("/pricing/")).toBe("bot:static:/pricing");
      expect(getBotPageCacheKey("/about///")).toBe("bot:static:/about");
    });

    it("normalizes empty/root path", () => {
      expect(getBotPageCacheKey("/")).toBe("bot:static:/");
      expect(getBotPageCacheKey("")).toBe("bot:static:/");
    });
  });

  describe("board / board-class / subject / topic patterns", () => {
    it("matches board landing page for known boards", () => {
      expect(getBotPageCacheKey("/ahsec")).toBe("bot:content:/ahsec");
      expect(getBotPageCacheKey("/seba")).toBe("bot:content:/seba");
      expect(getBotPageCacheKey("/degree")).toBe("bot:content:/degree");
      expect(getBotPageCacheKey("/cbse")).toBe("bot:content:/cbse");
      expect(getBotPageCacheKey("/nep")).toBe("bot:content:/nep");
    });

    it("rejects unknown boards as single-segment paths", () => {
      expect(getBotPageCacheKey("/random")).toBeNull();
      expect(getBotPageCacheKey("/icse")).toBeNull();
    });

    it("matches board+class for known boards", () => {
      expect(getBotPageCacheKey("/ahsec/class-12")).toBe("bot:content:/ahsec/class-12");
      expect(getBotPageCacheKey("/seba/class-10")).toBe("bot:content:/seba/class-10");
    });

    it("rejects unknown board for board+class", () => {
      expect(getBotPageCacheKey("/foo/bar")).toBeNull();
    });

    it("matches subject (3 segments)", () => {
      expect(getBotPageCacheKey("/ahsec/class-12/physics")).toBe(
        "bot:content:/ahsec/class-12/physics",
      );
    });

    it("matches topic (4 segments)", () => {
      expect(getBotPageCacheKey("/ahsec/class-12/physics/mechanics")).toBe(
        "bot:content:/ahsec/class-12/physics/mechanics",
      );
    });

    it("matches typed topic (5 segments) only for valid types", () => {
      expect(
        getBotPageCacheKey("/ahsec/class-12/physics/mechanics/notes"),
      ).toBe("bot:content:/ahsec/class-12/physics/mechanics/notes");
      expect(
        getBotPageCacheKey("/ahsec/class-12/physics/mechanics/mcqs"),
      ).toBe("bot:content:/ahsec/class-12/physics/mechanics/mcqs");
      expect(
        getBotPageCacheKey("/ahsec/class-12/physics/mechanics/faq"),
      ).toBe("bot:content:/ahsec/class-12/physics/mechanics/faq");
    });

    it("rejects 5-segment paths with invalid type", () => {
      expect(
        getBotPageCacheKey("/ahsec/class-12/physics/mechanics/banana"),
      ).toBeNull();
    });
  });

  describe("learn and pyq routes", () => {
    it("matches /learn/{slug}", () => {
      expect(getBotPageCacheKey("/learn/photosynthesis")).toBe(
        "bot:content:/learn/photosynthesis",
      );
    });

    it("matches /pyq/{slug}", () => {
      expect(getBotPageCacheKey("/pyq/2024-physics")).toBe(
        "bot:content:/pyq/2024-physics",
      );
    });
  });

  describe("excluded paths", () => {
    it.each([
      "/api/chat",
      "/admin",
      "/admin/dashboard",
      "/static/foo.css",
      "/assets/main.js",
      "/icons/logo.svg",
      "/fonts/inter.woff2",
      "/history",
      "/profile",
    ])("returns null for %s", (path) => {
      expect(getBotPageCacheKey(path)).toBeNull();
    });

    it.each([
      "/foo.js",
      "/style.css",
      "/img.png",
      "/photo.jpg",
      "/icon.svg",
      "/font.woff2",
      "/data.json",
      "/movie.mp4",
    ])("returns null for asset extension %s", (path) => {
      expect(getBotPageCacheKey(path)).toBeNull();
    });
  });

  describe("unsupported shapes", () => {
    it("returns null for empty-segment paths beyond 5 parts", () => {
      expect(
        getBotPageCacheKey("/a/b/c/d/e/f"),
      ).toBeNull();
    });
  });
});

describe("getBotCacheTtl", () => {
  it("returns 24h for static pages", () => {
    expect(getBotCacheTtl("bot:static:/pricing")).toBe(86400);
    expect(getBotCacheTtl("bot:static:/")).toBe(86400);
  });

  it("returns 1h for content pages", () => {
    expect(getBotCacheTtl("bot:content:/ahsec/class-12/physics")).toBe(3600);
    expect(getBotCacheTtl("bot:content:/learn/photosynthesis")).toBe(3600);
  });

  it("defaults to 1h for unrecognized prefixes", () => {
    expect(getBotCacheTtl("random:key")).toBe(3600);
  });
});
