from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any

import httpx


DEFAULT_REPORT_DIR = Path(r"D:\Donggri_Runtime\BloggerGent\storage\travel\reports")
DEFAULT_VERIFY_URL = "https://donggri-korea.blogspot.com/2026/03/jeonju-dawn-hanok-alley-transit-loop.html"
PATCH_MARKER = "donggri-travel-related-trending-r2-script"
LEGACY_PATCH_MARKER = "donggri-travel-trending-r2-script"
FULL_THEME_MARKER = "donggri-travel-theme-script"


THEME_H1_LINE_TO_REMOVE = (
    "<h1 class='text-4xl font-black font-headline tracking-tighter mb-8 text-primary "
    "font-headline'><data:post.title/></h1>"
)


THEME_PATCH_SNIPPET = r"""<!-- Donggri English Travel Related/Trending R2 thumbnails: start -->
<script id="donggri-travel-related-trending-r2-script" type="text/javascript">
//<![CDATA[
(function(){
  "use strict";

  var FALLBACK_IMAGE = "https://images.unsplash.com/photo-1517154421773-0529f29ea451?q=80&w=1200";
  var R2_RE = /https:\/\/api\.dongriarchive\.com\/assets\/travel-blogger\/[^"'<>\\\s)]+?\.webp/ig;
  var postHtmlCache = new Map();

  function cleanText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function cleanUrl(value) {
    try {
      var url = new URL(String(value || ""), window.location.href);
      if (url.protocol === "http:") url.protocol = "https:";
      url.hash = "";
      url.search = "";
      return url.href;
    } catch (_err) {
      return "";
    }
  }

  function firstR2ImageFromHtml(html) {
    R2_RE.lastIndex = 0;
    var matches = String(html || "").match(R2_RE);
    if (!matches || !matches.length) return "";
    for (var i = 0; i < matches.length; i += 1) {
      if (String(matches[i]).indexOf("blogger_img_proxy") === -1) return matches[i];
    }
    return "";
  }

  function fetchPostHtml(url) {
    var key = cleanUrl(url);
    if (!key) return Promise.resolve("");
    if (postHtmlCache.has(key)) return Promise.resolve(postHtmlCache.get(key));

    return fetch(key, { credentials: "same-origin" })
      .then(function(response) {
        if (!response.ok) return "";
        return response.text();
      })
      .then(function(html) {
        postHtmlCache.set(key, html || "");
        return html || "";
      })
      .catch(function() {
        return "";
      });
  }

  function fetchFirstR2Image(url) {
    return fetchPostHtml(url).then(firstR2ImageFromHtml);
  }

  function titleFromAnchor(anchor) {
    if (!anchor) return "Untitled";
    var titleNode = anchor.querySelector("h3,h2,.title,.entry-title");
    return cleanText(
      (titleNode && titleNode.textContent) ||
      anchor.getAttribute("aria-label") ||
      anchor.getAttribute("title") ||
      anchor.textContent ||
      "Untitled"
    );
  }

  function createSidebarItem(item) {
    return fetchFirstR2Image(item.href).then(function(r2) {
      var row = document.createElement("div");
      row.className = "sidebar-item";

      var textSide = document.createElement("div");
      textSide.className = "text-side";

      var textLink = document.createElement("a");
      textLink.className = "line-clamp-2";
      textLink.href = item.href;
      textLink.textContent = item.title || "Untitled";
      textSide.appendChild(textLink);

      var imageLink = document.createElement("a");
      imageLink.href = item.href;

      var img = document.createElement("img");
      img.loading = "lazy";
      img.decoding = "async";
      img.alt = "";
      img.src = r2 || FALLBACK_IMAGE;
      img.setAttribute("data-thumb-state", r2 ? "r2" : "fallback");
      imageLink.appendChild(img);

      row.appendChild(textSide);
      row.appendChild(imageLink);
      row.setAttribute("data-thumb-state", r2 ? "r2" : "fallback");
      return row;
    });
  }

  function dedupePostTitleH1() {
    var article = document.querySelector("article.post-body");
    if (!article) return;
    var h1s = article.querySelectorAll("h1");
    if (h1s.length < 2) return;
    var firstTitle = cleanText(h1s[0].textContent);
    var secondTitle = cleanText(h1s[1].textContent);
    if (firstTitle && firstTitle === secondTitle && h1s[0].parentNode) {
      h1s[0].parentNode.removeChild(h1s[0]);
    }
  }

  function loadFeedRelatedLinks() {
    return fetch("/feeds/posts/default/-/Travel?alt=json&max-results=8", { credentials: "same-origin" })
      .then(function(response) {
        if (!response.ok) return [];
        return response.json();
      })
      .then(function(data) {
        var entries = data && data.feed && data.feed.entry ? data.feed.entry : [];
        var currentUrl = cleanUrl(window.location.href);
        var rows = [];

        entries.forEach(function(entry) {
          var links = entry && entry.link ? entry.link : [];
          var href = "";
          for (var i = 0; i < links.length; i += 1) {
            if (links[i].rel === "alternate") {
              href = links[i].href || "";
              break;
            }
          }
          href = cleanUrl(href);
          if (!href || href === currentUrl) return;
          rows.push({
            href: href,
            title: entry && entry.title ? cleanText(entry.title.$t) : "Untitled"
          });
        });

        return rows.slice(0, 3);
      })
      .catch(function() {
        return [];
      });
  }

  function collectSourceRelatedLinks(source) {
    if (!source) return [];
    var anchors = Array.prototype.slice.call(source.querySelectorAll("a[href]"));
    var seen = {};
    var rows = [];

    anchors.forEach(function(anchor) {
      var href = cleanUrl(anchor.getAttribute("href") || anchor.href);
      if (!href || seen[href]) return;
      seen[href] = true;
      rows.push({
        href: href,
        title: titleFromAnchor(anchor)
      });
    });

    return rows.slice(0, 3);
  }

  function hydrateRelatedReads() {
    var source = document.querySelector(".post-body .related-posts");
    var relTarget = document.getElementById("related-posts-content");
    var relBox = document.getElementById("sidebar-related-target");
    if (!relTarget || !relBox) return;

    var links = collectSourceRelatedLinks(source);
    var linksPromise = links.length ? Promise.resolve(links) : loadFeedRelatedLinks();

    linksPromise.then(function(rows) {
      rows = rows.slice(0, 3);
      relTarget.innerHTML = "";

      if (!rows.length) {
        relBox.classList.add("hidden");
        return;
      }

      return Promise.all(rows.map(createSidebarItem)).then(function(nodes) {
        nodes.forEach(function(node) {
          relTarget.appendChild(node);
        });
        relBox.classList.remove("hidden");
      });
    });
  }

  function hydrateTrendingNowImages() {
    var items = Array.prototype.slice.call(document.querySelectorAll("#sidebar-trending-section .sidebar-item"));
    items.forEach(function(item) {
      var link = item.querySelector(".text-side a[href]") || item.querySelector("a[href]");
      var img = item.querySelector("img");
      if (!link || !img) return;

      img.setAttribute("data-thumb-state", "loading");
      item.setAttribute("data-thumb-state", "loading");

      fetchFirstR2Image(link.href).then(function(r2) {
        img.removeAttribute("srcset");
        img.src = r2 || FALLBACK_IMAGE;
        img.setAttribute("data-thumb-state", r2 ? "r2" : "fallback");
        item.setAttribute("data-thumb-state", r2 ? "r2" : "fallback");
      });
    });
  }

  function boot() {
    dedupePostTitleH1();
    hydrateTrendingNowImages();
    hydrateRelatedReads();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
//]]>
</script>
<!-- Donggri English Travel Related/Trending R2 thumbnails: end -->
"""


THEME_EDIT_MARKDOWN = f"""# English Travel Blogger Theme Patch

## 1. Remove the duplicate single-post H1

In the `Blog1` single item block, remove this exact line:

```xml
{THEME_H1_LINE_TO_REMOVE}
```

Do not remove the H1 inside `<data:post.body/>`. That body H1 is the title that should remain.

## 2. Add the Related/Trending R2 runtime patch

Paste the generated HTML snippet before `</body>` in the Blogger theme XML.

The snippet:

- leaves Blogger post URLs/HTML unchanged
- replaces Trending Now `blogger_img_proxy` thumbnails with each linked post's first R2 image
- rebuilds Related Travel Reads from real related links when present
- falls back to the Travel feed only when no related links exist
- marks only failed image extraction as `data-thumb-state="fallback"`
- includes a runtime H1 de-duplication guard, but the static SEO fix is still the XML H1 removal above
"""


def extract_patch_javascript(snippet: str) -> str:
    match = re.search(
        r"<script[^>]*>\s*//<!\[CDATA\[(?P<js>[\s\S]*?)//\]\]>\s*</script>",
        snippet,
        flags=re.IGNORECASE,
    )
    if not match:
        raise ValueError("Could not extract CDATA JavaScript from theme patch snippet.")
    return match.group("js").strip()


def build_playwright_runtime_check(snippet: str) -> str:
    js = extract_patch_javascript(snippet)
    js_literal = json.dumps(js)
    return f"""async (page) => {{
  const patch = {js_literal};
  await page.addScriptTag({{ content: patch }});
  await page.waitForTimeout(5000);
  const data = await page.evaluate(() => ({{
    h1Count: document.querySelectorAll("h1").length,
    h1Texts: Array.from(document.querySelectorAll("h1")).map(h => h.textContent.trim()),
    trending: Array.from(document.querySelectorAll("#sidebar-trending-section .sidebar-item")).map(item => ({{
      state: item.getAttribute("data-thumb-state") || (item.querySelector("img") && item.querySelector("img").dataset.thumbState) || "",
      src: (item.querySelector("img") && item.querySelector("img").src) || ""
    }})),
    related: Array.from(document.querySelectorAll("#related-posts-content .sidebar-item")).map(item => ({{
      title: (item.querySelector(".text-side a") && item.querySelector(".text-side a").textContent.trim()) || "",
      state: item.getAttribute("data-thumb-state") || (item.querySelector("img") && item.querySelector("img").dataset.thumbState) || "",
      src: (item.querySelector("img") && item.querySelector("img").src) || "",
      href: (item.querySelector("a[href]") && item.querySelector("a[href]").href) || ""
    }}))
  }}));
  console.log(JSON.stringify(data, null, 2));
}}"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate and verify the English Travel Blogger Related/Trending R2 thumbnail theme patch."
    )
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--verify-url", default=DEFAULT_VERIFY_URL)
    parser.add_argument(
        "--check-installed",
        action="store_true",
        help="Fetch the live page and check whether the marker script is present.",
    )
    parser.add_argument("--report-prefix", default="english-travel-related-trending-r2-patch")
    return parser.parse_args()


def report_path(report_dir: Path, prefix: str, suffix: str) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return report_dir / f"{prefix}-{stamp}.{suffix}"


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def count_pattern(pattern: str, html: str) -> int:
    return len(re.findall(pattern, html, flags=re.IGNORECASE))


def check_installed(url: str) -> dict[str, Any]:
    try:
        response = httpx.get(url, timeout=30.0, follow_redirects=True)
        html = response.text
        return {
            "url": url,
            "status_code": response.status_code,
            "ok": response.is_success,
            "installed": PATCH_MARKER in html or FULL_THEME_MARKER in html,
            "full_theme_installed": FULL_THEME_MARKER in html,
            "related_trending_installed": PATCH_MARKER in html,
            "legacy_installed": LEGACY_PATCH_MARKER in html,
            "marker": PATCH_MARKER,
            "full_theme_marker": FULL_THEME_MARKER,
            "bytes": len(response.content),
            "static_h1_count": count_pattern(r"<h1\b", html),
            "static_r2_count": count_pattern(r"api\.dongriarchive\.com/assets/travel-blogger", html),
            "static_blogger_proxy_count": count_pattern(r"blogger_img_proxy", html),
            "static_related_posts_present": "related-posts" in html,
            "error": "" if response.is_success else html[:500],
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "url": url,
            "status_code": None,
            "ok": False,
            "installed": False,
            "full_theme_installed": False,
            "related_trending_installed": False,
            "legacy_installed": False,
            "marker": PATCH_MARKER,
            "full_theme_marker": FULL_THEME_MARKER,
            "bytes": 0,
            "static_h1_count": None,
            "static_r2_count": None,
            "static_blogger_proxy_count": None,
            "static_related_posts_present": False,
            "error": str(exc),
        }


def main() -> int:
    args = parse_args()
    report_dir = Path(str(args.report_dir)).resolve()

    snippet_path = report_path(report_dir, str(args.report_prefix), "html")
    write_text(snippet_path, THEME_PATCH_SNIPPET.strip() + "\n")

    guide_path = report_path(report_dir, str(args.report_prefix), "md")
    write_text(guide_path, THEME_EDIT_MARKDOWN.strip() + "\n")

    playwright_check_path = report_path(report_dir, str(args.report_prefix), "playwright.js")
    write_text(playwright_check_path, build_playwright_runtime_check(THEME_PATCH_SNIPPET) + "\n")

    report: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "snippet_path": str(snippet_path),
        "guide_path": str(guide_path),
        "playwright_check_path": str(playwright_check_path),
        "marker": PATCH_MARKER,
        "legacy_marker": LEGACY_PATCH_MARKER,
        "h1_static_xml_edit": {
            "action": "remove_exact_line",
            "line": THEME_H1_LINE_TO_REMOVE,
            "reason": "The post body already contains the article H1.",
        },
        "behavior": {
            "trending_now": {
                "uses_popular_posts_for": ["title", "link", "order"],
                "thumbnail_source": "first R2 image inside each fetched linked post",
                "excluded_thumbnail_source": "lh3.googleusercontent.com/blogger_img_proxy",
            },
            "related_travel_reads": {
                "primary_links": ".post-body .related-posts a[href]",
                "fallback_links": "/feeds/posts/default/-/Travel?alt=json&max-results=8",
                "thumbnail_source": "first R2 image inside each fetched linked post",
                "post_html_republish": False,
            },
            "failed_image_extraction": "fallback image with data-thumb-state=fallback",
        },
    }
    if args.check_installed:
        report["live_check"] = check_installed(str(args.verify_url or DEFAULT_VERIFY_URL))

    json_path = report_path(report_dir, str(args.report_prefix), "json")
    report["report_path"] = str(json_path)
    write_text(json_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
