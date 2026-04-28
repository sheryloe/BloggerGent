from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
import re

# 미스테리 블로그 설정
BLOG_ID = 35
BLOG_URL = "https://dongdonggri.blogspot.com/"
ASSET_PATH_PART = "the-midnight-archives"
DEFAULT_REPORT_DIR = Path(r"D:\Donggri_Runtime\BloggerGent\storage\mystery\reports")

PATCH_MARKER = "donggri-mystery-archives-r2-script"

# 미스테리 블로그 테마 패치 스니펫 (범용 R2 정규식 적용)
THEME_PATCH_SNIPPET = r"""<!-- Donggri Mystery Archives R2 thumbnails: start -->
<script id="donggri-mystery-archives-r2-script" type="text/javascript">
//<![CDATA[
(function(){
  "use strict";

  var FALLBACK_IMAGE = "https://images.unsplash.com/photo-1501139083538-0139583c060f?q=80&w=1200";
  // 범용 R2 정규식: assets/ 뒤의 모든 경로를 허용
  var R2_RE = /https:\/\/api\.dongriarchive\.com\/assets\/[^"'<>\\\s)]+?\.webp/ig;
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
      // blogger_img_proxy 등 제외 로직 유지
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

  function hydratePopularArchives() {
    // 사용자가 지적한 ID: popular-records-content
    var container = document.getElementById("popular-records-content");
    if (!container) return;

    // Blogger 기본 PopularPosts 위젯의 데이터를 읽어와서 커스텀 레이아웃으로 대체하거나, 
    // 기존 아이템들의 이미지를 R2로 교체합니다.
    // 여기서는 기존 아이템들의 이미지를 교체하는 방식을 우선 시도합니다.
    var items = Array.prototype.slice.call(container.querySelectorAll(".sidebar-item, .item-content, li"));
    
    items.forEach(function(item) {
      var link = item.querySelector("a[href]");
      var img = item.querySelector("img");
      if (!link || !img) return;

      img.setAttribute("data-thumb-state", "loading");
      
      fetchFirstR2Image(link.href).then(function(r2) {
        if (r2) {
            img.removeAttribute("srcset");
            img.src = r2;
            img.setAttribute("data-thumb-state", "r2");
            item.setAttribute("data-thumb-state", "r2");
        } else {
            img.setAttribute("data-thumb-state", "fallback");
            item.setAttribute("data-thumb-state", "fallback");
        }
      });
    });
  }

  function boot() {
    hydratePopularArchives();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
//]]>
</script>
<!-- Donggri Mystery Archives R2 thumbnails: end -->
"""

def main():
    parser = argparse.ArgumentParser(description="Generate R2 thumbnail patch for Mystery Blog.")
    parser.add_argument("--output-dir", default=str(DEFAULT_REPORT_DIR))
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    html_path = output_dir / f"mystery-archives-patch-{stamp}.html"
    
    html_path.write_text(THEME_PATCH_SNIPPET.strip() + "\n", encoding="utf-8")
    
    print(f"Patch file generated at: {html_path}")
    print("\n--- PATCH SNIPPET START ---")
    print(THEME_PATCH_SNIPPET.strip())
    print("--- PATCH SNIPPET END ---\n")
    print("Instruction: Copy the snippet above and paste it just before </body> in your Blogger Theme XML.")

if __name__ == "__main__":
    main()
