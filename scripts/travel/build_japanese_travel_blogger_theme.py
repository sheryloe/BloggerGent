from __future__ import annotations

import argparse
from datetime import datetime
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

import httpx
from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
RUNTIME_ENV_PATH = REPO_ROOT / "env" / "runtime.settings.env"
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent"


def load_runtime_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and ((value.startswith("'") and value.endswith("'")) or (value.startswith('"') and value.endswith('"'))):
            value = value[1:-1]
        os.environ[key] = value


load_runtime_env(RUNTIME_ENV_PATH)
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get("BLOGGENT_DATABASE_URL", DEFAULT_DATABASE_URL)
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


DEFAULT_REPORT_DIR = Path(r"D:\Donggri_Runtime\BloggerGent\storage\travel\reports")
DEFAULT_PROFILE_IMAGE = Path(r"C:\Users\wlflq\Downloads\cab2744f-5b3c-41d4-8de0-b9f529198e96.jfif")
DEFAULT_PROFILE_OBJECT_KEY = "assets/travel-blogger/profile/donggri-kankoku-about-profile.webp"
DEFAULT_PROFILE_URL = "https://api.dongriarchive.com/assets/travel-blogger/profile/donggri-kankoku-about-profile.webp"
THEME_MARKER = "donggri-japanese-travel-theme-script"
BLOG_URL = "https://donggri-kankoku.blogspot.com/"
VERIFY_URLS = [
    BLOG_URL,
    f"{BLOG_URL}search/label/Travel",
    f"{BLOG_URL}search/label/Food",
    f"{BLOG_URL}search/label/Culture",
]


THEME_TEMPLATE = r'''<?xml version="1.0" encoding="UTF-8" ?>
<!DOCTYPE html>
<html b:version='2' class='v2' expr:dir='data:blog.languageDirection' expr:lang='data:blog.locale' xmlns='http://www.w3.org/1999/xhtml' xmlns:b='http://www.google.com/2005/gml/b' xmlns:data='http://www.google.com/2005/gml/data' xmlns:expr='http://www.google.com/2005/gml/expr'>
<head>
  <b:include data='blog' name='all-head-content'/>
  <title><data:view.title.escaped/></title>
  <meta content='width=device-width, initial-scale=1.0' name='viewport'/>
  <link href='https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@300;400;500;700;900&amp;family=Zen+Maru+Gothic:wght@400;700&amp;display=swap' rel='stylesheet'/>
  <script src='https://cdn.tailwindcss.com?plugins=forms,container-queries'/>
  <script>
  //<![CDATA[
  tailwind.config = {
    theme: {
      extend: {
        colors: {
          primary: '#1a1a1a',
          accent: '#fe932c',
          'light-brown': '#f7f2ed'
        },
        fontFamily: {
          headline: ['Noto Sans JP', 'sans-serif'],
          body: ['Noto Sans JP', 'sans-serif']
        }
      }
    }
  };
  //]]>
  </script>

  <b:skin><![CDATA[
  body { font-family: 'Noto Sans JP', sans-serif; background: #f7f2ed; margin: 0; padding: 0; color: #333; }
  .editorial-grid { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 2.5rem; align-items: start; }
  @media (max-width: 1024px) { .editorial-grid { grid-template-columns: 1fr; gap: 2rem; } }
  .sidebar-box { background: #fff; padding: 20px; border-radius: 4px; border: 1px solid rgba(0,0,0,0.05); margin-bottom: 12px !important; }
  .sidebar-title { font-size: 12px !important; font-weight: 900; text-transform: uppercase; letter-spacing: 0.1em; color: #1a1a1a; margin-bottom: 15px; border-left: 4px solid #fe932c; padding-left: 10px; }
  .line-clamp-1 { display: -webkit-box; -webkit-line-clamp: 1; -webkit-box-orient: vertical; overflow: hidden; }
  .line-clamp-2 { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .post-body img { border-radius: 8px; }
  .nav-link { border-bottom: 2px solid transparent; padding-bottom: 3px; }
  .nav-link.is-active { color: #1a1a1a !important; border-bottom-color: #fe932c; }
  .jp-profile-image { width: 100%; aspect-ratio: 16 / 9; object-fit: cover; border-radius: 8px; border: 1px solid rgba(254,147,44,0.18); background: #f7f2ed; }
  .jp-trending-item { display: grid; grid-template-columns: 82px minmax(0,1fr); gap: 10px; align-items: center; text-decoration: none; }
  .jp-trending-item img { width: 82px; height: 56px; object-fit: cover; border-radius: 6px; background: #f7f2ed; }
  .jp-card-image { background: #f7f2ed; }
  .jp-card-image[data-thumb-state="loading"], .jp-trending-item img[data-thumb-state="loading"] { opacity: 0.55; }
  .main.section { min-height: 0; }
  ]]></b:skin>
</head>

<body class='text-slate-900'>
  <nav class='fixed top-0 w-full z-50 bg-white/95 backdrop-blur-md shadow-sm border-b border-slate-100'>
    <div class='flex justify-between items-center px-6 py-4 max-w-7xl mx-auto w-full'>
      <a class='text-xl font-black font-headline tracking-tighter text-primary' href='https://donggri-kankoku.blogspot.com/' style='font-family: &quot;Noto Sans JP&quot;, sans-serif !important;'>
        Donggri | 日韓夫婦の韓国案内
      </a>
      <div class='hidden md:flex gap-6 font-headline text-[13px] font-bold text-slate-500'>
        <a class='nav-link hover:text-accent transition-colors' data-nav='home' href='https://donggri-kankoku.blogspot.com/'>ホーム</a>
        <a class='nav-link hover:text-accent transition-colors' data-nav-label='Travel' href='/search/label/Travel'>旅行&#12539;お祭り</a>
        <a class='nav-link hover:text-accent transition-colors' data-nav-label='Food' href='/search/label/Food'>グルメ&#12539;カフェ</a>
        <a class='nav-link hover:text-accent transition-colors' data-nav-label='Culture' href='/search/label/Culture'>ライフスタイル</a>
        <a class='nav-link hover:text-accent transition-colors' data-nav='about' href='/p/about.html'>運営者情報</a>
      </div>
    </div>
  </nav>

  <main class='pt-24 max-w-7xl mx-auto px-6 pb-20'>
    <div class='editorial-grid'>
      <div class='space-y-10'>
        <div class='relative w-full h-[400px] md:h-[500px] rounded-lg overflow-hidden bg-primary shadow-lg group' id='js-auto-hero'>
          <div class='absolute inset-0 flex items-center justify-center text-white/20 animate-pulse text-sm uppercase tracking-widest font-bold'>リアルな韓国を&#12289;もっと身近に&#12290;</div>
        </div>

        <b:section class='main' id='main-section' showaddelement='no'/>
      </div>

      <aside class='hidden lg:flex flex-col gap-4 sticky top-32 h-fit'>
        <div class='sidebar-box bg-white'>
          <h3 class='sidebar-title'>About Us</h3>
          <div class='space-y-3'>
            <img alt='日韓夫婦の韓国案内' class='jp-profile-image' decoding='async' loading='lazy' src='__PROFILE_IMAGE_URL__'/>
            <p class='text-[11px] leading-relaxed text-slate-600'>
              <b>日韓夫婦の視点で届ける韓国案内</b><br/>
              ソウル在住夫婦が&#12289;現地人だけが知る穴場スポットを徹底解説します&#12290;
            </p>
          </div>
        </div>

        <div class='sidebar-box'>
          <h3 class='sidebar-title'>注目記事</h3>
          <div class='space-y-3' id='sidebar-trending-section'/>
        </div>
      </aside>
    </div>
  </main>

  <footer class='w-full py-20 bg-white border-t mt-20 text-center'>
    <div class='max-w-7xl mx-auto px-6 space-y-6'>
      <div class='text-xl font-black font-headline tracking-tighter uppercase text-primary'>Donggri Korea</div>
      <div class='flex justify-center gap-6 text-[11px] font-medium text-slate-400'>
        <a class='hover:text-primary transition-colors' href='/p/privacy-policy.html'>プライバシーポリシー</a>
        <a class='hover:text-primary transition-colors' href='/p/disclaimer.html'>免責事項</a>
        <a class='hover:text-primary transition-colors' href='/p/contact.html'>お問い合わせ</a>
        <a class='hover:text-primary transition-colors' href='/p/faq.html'>よくある質問</a>
        <a class='hover:text-primary transition-colors' href='/p/editorial-policy.html'>編集方針</a>
      </div>
      <p class='text-[10px] text-slate-300 tracking-widest'>&#169; 2026 DONGGRI KOREA JP. ALL RIGHTS RESERVED.</p>
    </div>
  </footer>

  <script id='donggri-japanese-travel-theme-script' type='text/javascript'>
  //<![CDATA[
  (function () {
    "use strict";

    var PROFILE_IMAGE = "__PROFILE_IMAGE_URL__";
    var FALLBACK_IMAGE = "https://placehold.co/1200x675?text=Donggri";
    var R2_RE = /https:\/\/api\.dongriarchive\.com\/assets\/travel-blogger\/[^"'<>\\\s)]+?\.webp/ig;
    var feedCache = new Map();

    var TEXT = {
      empty: 'まだ記事がありません',
      read: '続きを読む',
      latestPrefix: '最新: ',
      updated: '更新日'
    };

    var CATEGORIES = [
      { label: 'Travel', title: '旅行・お祭り', desc: '韓国旅行、祭り、季節イベントの実用ガイド' },
      { label: 'Food', title: 'グルメ・カフェ', desc: 'ローカルグルメ、カフェ、食べ歩き情報' },
      { label: 'Culture', title: 'ライフスタイル', desc: '韓国の日常、文化、暮らしのヒント' }
    ];

    function stripHtml(raw) {
      return String(raw || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
    }

    function esc(raw) {
      return String(raw || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    }

    function isHomepage() {
      var p = (window.location.pathname || '/').replace(/\/+$/, '') || '/';
      return p === '/' || p === '/index.html';
    }

    function isPostPage() {
      return /^\/\d{4}\/\d{2}\/.+\.html$/.test(window.location.pathname || '');
    }

    function isStaticPage() {
      return /^\/p\/.+\.html$/.test(window.location.pathname || '');
    }

    function getCurrentLabel() {
      var m = (window.location.pathname || '').match(/^\/search\/label\/(.+)$/);
      if (!m) return '';
      return decodeURIComponent(m[1]).replace(/\+/g, ' ');
    }

    function firstR2FromHtml(html) {
      R2_RE.lastIndex = 0;
      var matches = String(html || '').match(R2_RE);
      if (!matches || !matches.length) return '';
      for (var i = 0; i < matches.length; i += 1) {
        var candidate = String(matches[i] || '').trim();
        if (candidate && candidate.indexOf('blogger_img_proxy') === -1) return candidate;
      }
      return '';
    }

    function normalizeImageUrl(url) {
      var raw = String(url || '').trim();
      if (!raw) return '';
      if (raw.indexOf('blogger_img_proxy') !== -1) return '';
      if (raw.indexOf('api.dongriarchive.com/assets/travel-blogger/') === -1) return '';
      if (raw.indexOf('//') === 0) return 'https:' + raw;
      return raw;
    }

    function postUrl(entry) {
      var links = entry && entry.link ? entry.link : [];
      for (var i = 0; i < links.length; i += 1) {
        if (links[i].rel === 'alternate') return links[i].href || '#';
      }
      return '#';
    }

    function firstImageFromContent(entry) {
      var html = String(entry && entry.content ? entry.content.$t : '');
      var r2 = firstR2FromHtml(html);
      if (r2) return r2;
      var srcMatch = html.match(/<img[^>]+src=["']([^"']+)["']/i);
      if (srcMatch) return normalizeImageUrl(srcMatch[1]);
      var dataSrcMatch = html.match(/<img[^>]+data-src=["']([^"']+)["']/i);
      if (dataSrcMatch) return normalizeImageUrl(dataSrcMatch[1]);
      return '';
    }

    function thumb(entry) {
      return firstImageFromContent(entry) || FALLBACK_IMAGE;
    }

    function parseEntry(entry) {
      return {
        id: String(entry && entry.id ? entry.id.$t : '').split('-').pop() || '',
        title: entry && entry.title ? entry.title.$t : '',
        href: postUrl(entry),
        image: thumb(entry),
        summary: stripHtml((entry && entry.summary ? entry.summary.$t : '') || (entry && entry.content ? entry.content.$t : '')).slice(0, 130),
        content: String(entry && entry.content ? entry.content.$t : '').replace(/<!--RELATED_POSTS-->/g, ''),
        published: String(entry && entry.published ? entry.published.$t : '').slice(0, 10),
        updated: String(entry && entry.updated ? entry.updated.$t : '').slice(0, 10)
      };
    }

    function parsePageEntry(entry) {
      return {
        id: String(entry && entry.id ? entry.id.$t : '').split('-').pop() || '',
        title: entry && entry.title ? entry.title.$t : '',
        href: postUrl(entry),
        image: '',
        summary: stripHtml(entry && entry.content ? entry.content.$t : '').slice(0, 160),
        content: String(entry && entry.content ? entry.content.$t : ''),
        published: String(entry && entry.published ? entry.published.$t : '').slice(0, 10),
        updated: String(entry && entry.updated ? entry.updated.$t : '').slice(0, 10)
      };
    }

    function fetchJson(url) {
      if (feedCache.has(url)) return Promise.resolve(feedCache.get(url));
      return fetch(url, { credentials: 'same-origin' })
        .then(function(res) {
          if (!res.ok) throw new Error('feed_error');
          return res.json();
        })
        .then(function(payload) {
          feedCache.set(url, payload);
          return payload;
        });
    }

    function fetchFeed(path, maxResults) {
      var q = new URLSearchParams({ alt: 'json', 'max-results': String(maxResults || 12) });
      return fetchJson('/feeds/posts/default' + path + '?' + q.toString())
        .then(function(payload) {
          var entries = payload && payload.feed && payload.feed.entry ? payload.feed.entry : [];
          return entries.map(parseEntry);
        })
        .catch(function() { return []; });
    }

    function fetchByLabel(label, maxResults) {
      return fetchFeed('/-/' + encodeURIComponent(label), maxResults || 12);
    }

    function fetchRecent(maxResults) {
      return fetchFeed('', maxResults || 10);
    }

    function fetchPages(maxResults) {
      var q = new URLSearchParams({ alt: 'json', 'max-results': String(maxResults || 50) });
      return fetchJson('/feeds/pages/default?' + q.toString())
        .then(function(payload) {
          return payload && payload.feed && payload.feed.entry ? payload.feed.entry : [];
        })
        .catch(function() { return []; });
    }

    function fetchByPath(pathname) {
      return fetchRecent(200).then(function(items) {
        for (var i = 0; i < items.length; i += 1) {
          try {
            if (new URL(items[i].href).pathname === pathname) return items[i];
          } catch (_err) {}
        }
        return null;
      });
    }

    function fetchStaticPageByPath(pathname) {
      return fetchPages(50).then(function(entries) {
        for (var i = 0; i < entries.length; i += 1) {
          var url = postUrl(entries[i]);
          try {
            if (new URL(url).pathname === pathname) return parsePageEntry(entries[i]);
          } catch (_err) {}
        }
        return null;
      });
    }

    function card(item) {
      return [
        '<article class="bg-white rounded-2xl overflow-hidden border border-orange-100 shadow-sm hover:shadow-md transition-shadow">',
        '<a href="' + esc(item.href) + '" class="block">',
        '<img src="' + esc(item.image) + '" alt="' + esc(item.title) + '" class="jp-card-image w-full h-44 object-cover" data-thumb-state="' + (item.image.indexOf('api.dongriarchive.com/assets/travel-blogger/') !== -1 ? 'r2' : 'fallback') + '" loading="lazy" onerror="this.onerror=null;this.src=&quot;' + FALLBACK_IMAGE + '&quot;"/>',
        '</a>',
        '<div class="p-4 space-y-2">',
        '<a href="' + esc(item.href) + '" class="block text-sm font-extrabold text-primary leading-tight hover:text-accent line-clamp-2">' + esc(item.title) + '</a>',
        '<p class="text-xs text-slate-600 leading-relaxed line-clamp-2">' + esc(item.summary) + '</p>',
        '<a href="' + esc(item.href) + '" class="inline-block text-[11px] font-bold text-accent">' + TEXT.read + '</a>',
        '</div>',
        '</article>'
      ].join('');
    }

    function renderList(container, items) {
      if (!container) return;
      if (!items.length) {
        container.innerHTML = '<p class="text-sm text-slate-400">' + TEXT.empty + '</p>';
        return;
      }
      container.innerHTML = items.map(card).join('');
    }

    function renderHero(item) {
      var hero = document.getElementById('js-auto-hero');
      if (!hero) return;
      var safeImage = item && item.image ? item.image : PROFILE_IMAGE;
      var safeHref = item && item.href ? item.href : '#';
      var safeTitle = item && item.title ? item.title : 'Donggri Korea';
      var safePublished = item && item.published ? item.published : '';

      hero.innerHTML = [
        '<a href="' + esc(safeHref) + '" class="block w-full h-full relative">',
        '<img src="' + esc(safeImage) + '" alt="' + esc(safeTitle) + '" class="absolute inset-0 w-full h-full object-cover" data-thumb-state="' + (safeImage.indexOf('api.dongriarchive.com/assets/travel-blogger/') !== -1 ? 'r2' : 'fallback') + '" onerror="this.onerror=null;this.src=&quot;' + PROFILE_IMAGE + '&quot;"/>',
        '<div class="absolute inset-0 bg-gradient-to-t from-black/70 via-black/25 to-transparent"></div>',
        '<div class="absolute left-6 right-6 bottom-6 text-white">',
        '<div class="text-[11px] uppercase tracking-[0.2em] text-white/80">' + TEXT.latestPrefix + esc(safePublished) + '</div>',
        '<h2 class="mt-2 text-2xl md:text-3xl font-black leading-tight">' + esc(safeTitle) + '</h2>',
        '</div>',
        '</a>'
      ].join('');
    }

    function setActiveNav() {
      var currentLabel = getCurrentLabel();
      var active = isHomepage() ? 'home' : '';
      if (!active && currentLabel) active = currentLabel;
      if (!active && /^\/p\/about\.html$/i.test(window.location.pathname || '')) active = 'about';
      document.querySelectorAll('[data-nav], [data-nav-label]').forEach(function(el) {
        var key = el.getAttribute('data-nav') || el.getAttribute('data-nav-label') || '';
        el.classList.toggle('is-active', key === active);
      });
    }

    function ensureHomeCategoryShell() {
      if (!isHomepage() || isPostPage()) return null;
      var host = document.querySelector('#main-section') || document.querySelector('main');
      if (!host) return null;
      host.innerHTML = '';
      var section = document.createElement('section');
      section.id = 'category-latest';
      section.className = 'space-y-10 mt-8';
      section.innerHTML = CATEGORIES.map(function(cfg) {
        return [
          '<section data-label="' + esc(cfg.label) + '" class="space-y-4">',
          '<div class="flex items-end justify-between border-l-4 border-accent pl-4">',
          '<div><h2 class="text-sm font-black uppercase tracking-widest text-primary">' + esc(cfg.title) + '</h2>',
          '<p class="text-xs text-slate-500 mt-1">' + esc(cfg.desc) + '</p></div>',
          '<a href="/search/label/' + encodeURIComponent(cfg.label) + '" class="text-[11px] font-bold text-accent">' + TEXT.read + '</a>',
          '</div>',
          '<div class="grid grid-cols-1 md:grid-cols-3 gap-6 category-items"></div>',
          '</section>'
        ].join('');
      }).join('');
      host.appendChild(section);
      return section;
    }

    function renderHomepage() {
      var section = ensureHomeCategoryShell();
      if (!section) return Promise.resolve();
      var all = [];
      var chain = Promise.resolve();
      CATEGORIES.forEach(function(cfg) {
        chain = chain.then(function() {
          var blocks = Array.prototype.slice.call(section.querySelectorAll('[data-label]'));
          var block = blocks.find(function(el) { return (el.getAttribute('data-label') || '') === cfg.label; });
          var list = block ? block.querySelector('.category-items') : null;
          if (!list) return Promise.resolve();
          return fetchByLabel(cfg.label, 3).then(function(items) {
            renderList(list, items);
            all = all.concat(items);
          });
        });
      });
      return chain.then(function() {
        if (all.length) {
          all.sort(function(a, b) { return String(b.published).localeCompare(String(a.published)); });
          renderHero(all[0]);
        }
      });
    }

    function renderLabelArchive() {
      var label = getCurrentLabel();
      if (!label || isPostPage()) return Promise.resolve();
      var host = document.querySelector('#main-section') || document.querySelector('main');
      if (!host) return Promise.resolve();
      host.innerHTML = '';
      var wrap = document.createElement('section');
      wrap.id = 'label-archive-wrap';
      wrap.className = 'space-y-4 mt-8';
      wrap.innerHTML = [
        '<div class="flex items-center justify-between border-l-4 border-accent pl-4">',
        '<h2 class="text-sm font-black uppercase tracking-widest text-primary">' + esc(label) + '</h2>',
        '</div>',
        '<div class="grid grid-cols-1 md:grid-cols-3 gap-6 label-items"></div>'
      ].join('');
      host.appendChild(wrap);
      return fetchByLabel(label, 12).then(function(items) {
        renderList(wrap.querySelector('.label-items'), items);
        renderHero(items[0] || null);
      });
    }

    function renderPostPage(item) {
      var host = document.querySelector('#main-section');
      if (!host || !item) return;
      var hasBodyH1 = /<h1\b/i.test(item.content || '');
      var titleBlock = hasBodyH1
        ? ''
        : '<h1 class="text-2xl md:text-4xl font-black text-primary leading-tight">' + esc(item.title) + '</h1>';
      host.className = 'main section';
      host.innerHTML = [
        '<article class="bg-white rounded-2xl p-6 md:p-10 border border-slate-200 shadow-sm">',
        '<header class="mb-6">',
        titleBlock,
        '<p class="mt-3 text-xs text-slate-500">' + TEXT.updated + ': ' + esc(item.updated || item.published) + '</p>',
        '</header>',
        '<div class="post-body prose max-w-none">' + item.content + '</div>',
        '</article>'
      ].join('');
      renderHero(item);
    }

    function renderSinglePost() {
      if (!isPostPage()) return Promise.resolve();
      return fetchByPath(window.location.pathname).then(function(item) {
        if (item) renderPostPage(item);
      });
    }

    function renderStaticHero(item) {
      var hero = document.getElementById('js-auto-hero');
      if (!hero) return;
      var safeTitle = item && item.title ? item.title : 'Donggri Korea';
      var safeUpdated = item && (item.updated || item.published) ? (item.updated || item.published) : '';
      hero.innerHTML = [
        '<div class="absolute inset-0"><img src="' + esc(PROFILE_IMAGE) + '" alt="" class="w-full h-full object-cover"/></div>',
        '<div class="absolute inset-0 bg-gradient-to-t from-black/75 via-black/35 to-transparent"></div>',
        '<div class="absolute left-6 right-6 bottom-6 text-white">',
        '<div class="text-[11px] uppercase tracking-[0.2em] text-white/80">Info Page</div>',
        '<h2 class="mt-2 text-2xl md:text-3xl font-black leading-tight">' + esc(safeTitle) + '</h2>',
        '<p class="mt-3 text-sm text-white/80">' + (safeUpdated ? TEXT.updated + ': ' + esc(safeUpdated) : 'Donggri Korea Japan') + '</p>',
        '</div>'
      ].join('');
    }

    function renderStaticPage(item) {
      var host = document.querySelector('#main-section');
      if (!host || !item) return;
      var hasBodyH1 = /<h1\b/i.test(item.content || '');
      var titleBlock = hasBodyH1
        ? ''
        : '<h1 class="mt-3 text-2xl md:text-4xl font-black text-primary leading-tight">' + esc(item.title) + '</h1>';
      host.className = 'main section';
      host.innerHTML = [
        '<article class="bg-white rounded-2xl p-6 md:p-10 border border-slate-200 shadow-sm">',
        '<header class="mb-6 border-b border-slate-100 pb-5">',
        '<div class="text-[11px] uppercase tracking-[0.2em] text-accent font-black">Static Page</div>',
        titleBlock,
        '<p class="mt-3 text-xs text-slate-500">' + TEXT.updated + ': ' + esc(item.updated || item.published) + '</p>',
        '</header>',
        '<div class="post-body prose max-w-none">' + item.content + '</div>',
        '</article>'
      ].join('');
      renderStaticHero(item);
    }

    function renderSingleStaticPage() {
      if (!isStaticPage()) return Promise.resolve();
      return fetchStaticPageByPath(window.location.pathname).then(function(item) {
        if (item) renderStaticPage(item);
      });
    }

    function renderSidebarTrending() {
      var host = document.getElementById('sidebar-trending-section');
      if (!host) return Promise.resolve();
      return fetchRecent(8).then(function(items) {
        items = items.slice(0, 6);
        if (!items.length) {
          host.innerHTML = '<p class="text-xs text-slate-400">' + TEXT.empty + '</p>';
          return;
        }
        host.innerHTML = items.map(function(item) {
          return [
            '<a href="' + esc(item.href) + '" class="jp-trending-item group">',
            '<img src="' + esc(item.image) + '" alt="" loading="lazy" data-thumb-state="' + (item.image.indexOf('api.dongriarchive.com/assets/travel-blogger/') !== -1 ? 'r2' : 'fallback') + '" onerror="this.onerror=null;this.src=&quot;' + PROFILE_IMAGE + '&quot;"/>',
            '<span class="min-w-0">',
            '<span class="block text-[11px] leading-relaxed text-slate-700 group-hover:text-accent transition-colors line-clamp-2">' + esc(item.title) + '</span>',
            '<span class="block text-[10px] text-slate-400 mt-1">' + esc(item.published) + '</span>',
            '</span>',
            '</a>'
          ].join('');
        }).join('');
      });
    }

    function boot() {
      setActiveNav();
      Promise.all([renderHomepage(), renderLabelArchive(), renderSidebarTrending()])
        .then(renderSinglePost)
        .then(renderSingleStaticPage)
        .catch(function() { renderHero(null); });
    }

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', boot, { once: true });
    } else {
      boot();
    }
  })();
  //]]>
  </script>
</body>
</html>
'''


BLOGGER_MAIN_SECTION_XML = r'''<b:section class='main' id='main-section' showaddelement='yes'>
          <b:widget id='Blog1' locked='false' title='Blog Posts' type='Blog' version='2' visible='true'>
            <b:widget-settings>
              <b:widget-setting name='showDateHeader'>false</b:widget-setting>
              <b:widget-setting name='style.textcolor'>#ffffff</b:widget-setting>
              <b:widget-setting name='showShareButtons'>true</b:widget-setting>
              <b:widget-setting name='showCommentLink'>false</b:widget-setting>
              <b:widget-setting name='style.urlcolor'>#ffffff</b:widget-setting>
              <b:widget-setting name='showAuthor'>false</b:widget-setting>
              <b:widget-setting name='style.linkcolor'>#ffffff</b:widget-setting>
              <b:widget-setting name='style.unittype'>TextAndImage</b:widget-setting>
              <b:widget-setting name='style.bgcolor'>#ffffff</b:widget-setting>
              <b:widget-setting name='timestampLabel'/>
              <b:widget-setting name='reactionsLabel'/>
              <b:widget-setting name='showAuthorProfile'>false</b:widget-setting>
              <b:widget-setting name='style.layout'>1x1</b:widget-setting>
              <b:widget-setting name='showLabels'>true</b:widget-setting>
              <b:widget-setting name='showLocation'>false</b:widget-setting>
              <b:widget-setting name='postLabelsLabel'>Labels</b:widget-setting>
              <b:widget-setting name='showTimestamp'>false</b:widget-setting>
              <b:widget-setting name='postsPerAd'>1</b:widget-setting>
              <b:widget-setting name='showBacklinks'>false</b:widget-setting>
              <b:widget-setting name='style.bordercolor'>#ffffff</b:widget-setting>
              <b:widget-setting name='showInlineAds'>false</b:widget-setting>
              <b:widget-setting name='showReactions'>false</b:widget-setting>
            </b:widget-settings>
            <b:includable id='main' var='top'>
              <b:if cond='data:view.isMultipleItems'>
                <div class='grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6'>
                  <b:loop index='i' values='data:posts' var='post'>
                    <b:if cond='not data:newerPageUrl'>
                      <b:if cond='data:i != 0'><b:include data='post' name='postItem'/></b:if>
                    <b:else/>
                      <b:if cond='data:i &lt; 6'><b:include data='post' name='postItem'/></b:if>
                    </b:if>
                  </b:loop>
                </div>
                <div class='flex justify-between mt-10 pt-6 border-t border-orange-100'>
                  <b:if cond='data:newerPageUrl'><a class='text-xs font-bold uppercase hover:text-accent tracking-widest transition-colors' expr:href='data:newerPageUrl'>&#8592; Newer</a><b:else/><div/></b:if>
                  <b:if cond='data:olderPageUrl'><a class='text-xs font-bold uppercase hover:text-accent tracking-widest transition-colors' expr:href='data:olderPageUrl'>Older &#8594;</a></b:if>
                </div>
              </b:if>

              <b:if cond='data:view.isSingleItem'>
                <b:loop values='data:posts' var='post'>
                  <article class='bg-white rounded-2xl p-6 md:p-10 border border-slate-200 shadow-sm post-body'>
                    <div class='font-body text-slate-700 leading-relaxed article-content'><data:post.body/></div>
                  </article>
                </b:loop>
              </b:if>
            </b:includable>
            <b:includable id='postItem' var='post'>
              <div class='group js-post-card' expr:data-post-url='data:post.url'>
                <div class='relative aspect-[4/5] rounded-xl overflow-hidden bg-light-brown mb-4 shadow-sm'>
                  <a expr:href='data:post.url'>
                    <b:if cond='data:post.featuredImage'>
                      <img class='jp-card-image w-full h-full object-cover group-hover:scale-105 transition-all duration-500' data-thumb-state='loading' expr:src='data:post.featuredImage'/>
                    <b:else/>
                      <img class='jp-card-image w-full h-full object-cover group-hover:scale-105 transition-all duration-500' data-thumb-state='fallback' src='https://api.dongriarchive.com/assets/travel-blogger/profile/donggri-kankoku-about-profile.webp'/>
                    </b:if>
                  </a>
                </div>
                <a expr:href='data:post.url'>
                  <h3 class='font-headline text-sm font-bold text-primary mb-2 group-hover:text-accent transition-colors line-clamp-2 leading-snug'><data:post.title/></h3>
                  <p class='text-slate-500 text-[11px] line-clamp-1'><data:post.snippet/></p>
                </a>
              </div>
            </b:includable>
          </b:widget>
        </b:section>'''


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Japanese Travel Blogger theme and optionally upload the profile image to R2.")
    parser.add_argument("--profile-image", default=str(DEFAULT_PROFILE_IMAGE))
    parser.add_argument("--profile-url", default="")
    parser.add_argument("--object-key", default=DEFAULT_PROFILE_OBJECT_KEY)
    parser.add_argument("--upload-profile", action="store_true")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--report-prefix", default="japanese-travel-theme-full-fixed")
    return parser.parse_args()


def timestamped_path(report_dir: Path, prefix: str, suffix: str) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return report_dir / f"{prefix}-{stamp}.{suffix}"


def render_profile_webp(path: Path) -> bytes:
    with Image.open(path) as img:
      img = img.convert("RGB")
      max_width = 1200
      if img.width > max_width:
          ratio = max_width / float(img.width)
          img = img.resize((max_width, max(1, int(img.height * ratio))), Image.Resampling.LANCZOS)
      output = BytesIO()
      img.save(output, format="WEBP", quality=86, method=6)
      return output.getvalue()


def upload_profile_image(*, image_path: Path, object_key: str) -> dict[str, object]:
    from app.db.session import SessionLocal
    from app.services.integrations.storage_service import upload_binary_to_cloudflare_r2

    content = render_profile_webp(image_path)
    db = SessionLocal()
    try:
        public_url, upload_payload, delivery_meta = upload_binary_to_cloudflare_r2(
            db,
            object_key=object_key,
            filename=Path(object_key).name,
            content=content,
        )
    finally:
        db.close()

    verify = {"ok": False, "status_code": None, "bytes": 0, "sha256": "", "error": ""}
    try:
        response = httpx.get(public_url, timeout=30.0, follow_redirects=True)
        body = response.content
        verify = {
            "ok": response.is_success,
            "status_code": response.status_code,
            "bytes": len(body),
            "sha256": sha256(body).hexdigest().upper() if response.is_success else "",
            "error": "" if response.is_success else response.text[:500],
        }
    except Exception as exc:  # noqa: BLE001
        verify["error"] = str(exc)

    return {
        "source_path": str(image_path),
        "object_key": object_key,
        "public_url": public_url,
        "source_webp_bytes": len(content),
        "source_webp_sha256": sha256(content).hexdigest().upper(),
        "upload_payload": upload_payload,
        "delivery_meta": delivery_meta,
        "verify": verify,
    }


def _js_escape_non_ascii(value: str) -> str:
    chunks: list[str] = []
    for char in value:
        codepoint = ord(char)
        if codepoint <= 0x7F:
            chunks.append(char)
        elif codepoint <= 0xFFFF:
            chunks.append(f"\\u{codepoint:04X}")
        else:
            codepoint -= 0x10000
            high = 0xD800 + (codepoint >> 10)
            low = 0xDC00 + (codepoint & 0x3FF)
            chunks.append(f"\\u{high:04X}\\u{low:04X}")
    return "".join(chunks)


def _xml_escape_non_ascii(value: str) -> str:
    return "".join(char if ord(char) <= 0x7F else f"&#x{ord(char):X};" for char in value)


def _make_blogger_xml_ascii_safe(theme_xml: str) -> str:
    parts = re.split(r"(//<!\[CDATA\[[\s\S]*?//\]\]>)", theme_xml)
    safe_parts: list[str] = []
    for part in parts:
        if part.startswith("//<![CDATA["):
            safe_parts.append(_js_escape_non_ascii(part))
        else:
            safe_parts.append(_xml_escape_non_ascii(part))
    return "".join(safe_parts)


def build_theme(profile_url: str) -> str:
    theme = THEME_TEMPLATE.replace("__PROFILE_IMAGE_URL__", profile_url)
    theme = theme.replace(
        "<b:section class='main' id='main-section' showaddelement='no'/>",
        BLOGGER_MAIN_SECTION_XML,
    )
    return _make_blogger_xml_ascii_safe(theme).strip() + "\n"


def extract_theme_script(theme_xml: str) -> str:
    match = re.search(
        r"<script\s+id='donggri-japanese-travel-theme-script'[^>]*>\s*//<!\[CDATA\[(?P<script>[\s\S]*?)//\]\]>\s*</script>",
        theme_xml,
        flags=re.IGNORECASE,
    )
    if not match:
        raise ValueError("Japanese theme script marker was not found.")
    return match.group("script").strip()


def build_playwright_check(theme_xml: str) -> str:
    script = extract_theme_script(theme_xml)
    script_literal = json.dumps(script)
    urls_literal = json.dumps(VERIFY_URLS, ensure_ascii=False)
    return f"""async (page) => {{
  const urls = {urls_literal};
  const patch = {script_literal};
  const results = [];
  for (const url of urls) {{
    await page.goto(url, {{ waitUntil: "networkidle", timeout: 60000 }});
    await page.addScriptTag({{ content: patch }});
    await page.waitForTimeout(5000);
    results.push(await page.evaluate(() => ({{
      url: location.href,
      activeNav: Array.from(document.querySelectorAll("nav .is-active")).map(a => a.textContent.trim()),
      heroImages: Array.from(document.querySelectorAll("#js-auto-hero img")).map(img => img.src),
      categoryImages: Array.from(document.querySelectorAll("#category-latest img")).map(img => img.src),
      labelImages: Array.from(document.querySelectorAll("#label-archive-wrap img")).map(img => img.src),
      trendingImages: Array.from(document.querySelectorAll("#sidebar-trending-section img")).map(img => img.src),
      profileImages: Array.from(document.querySelectorAll(".jp-profile-image")).map(img => img.src),
      h1Count: document.querySelectorAll("h1").length,
      placeholderCount: Array.from(document.querySelectorAll("img")).filter(img => img.src.includes("placehold.co")).length
    }})));
  }}
  return results;
}}"""


def validate_theme(theme_xml: str, *, profile_url: str) -> dict[str, object]:
    ET.fromstring(theme_xml.encode("utf-8"), parser=ET.XMLParser())
    return {
        "xml_parse_ok": True,
        "theme_marker_present": THEME_MARKER in theme_xml,
        "all_head_content_present": "<b:include data='blog' name='all-head-content'/>" in theme_xml,
        "profile_url_present": profile_url in theme_xml,
        "profile_uses_r2": profile_url.startswith("https://api.dongriarchive.com/assets/travel-blogger/"),
        "blogger_proxy_rejected": "blogger_img_proxy" in theme_xml,
        "static_home_active_removed": "border-b-2" not in re.sub(r"<script[\s\S]*?</script>", "", theme_xml),
    }


def main() -> int:
    args = parse_args()
    report_dir = Path(str(args.report_dir)).resolve()
    profile_image = Path(str(args.profile_image)).resolve()
    profile_url = str(args.profile_url or DEFAULT_PROFILE_URL).strip()
    upload_report: dict[str, object] | None = None

    if args.upload_profile:
        if not profile_image.exists():
            raise FileNotFoundError(profile_image)
        upload_report = upload_profile_image(image_path=profile_image, object_key=str(args.object_key).strip())
        profile_url = str(upload_report["public_url"])

    theme_xml = build_theme(profile_url)
    validation = validate_theme(theme_xml, profile_url=profile_url)

    theme_path = timestamped_path(report_dir, str(args.report_prefix), "xml")
    theme_path.write_text(theme_xml, encoding="utf-8")

    playwright_path = timestamped_path(report_dir, str(args.report_prefix), "playwright.js")
    playwright_path.write_text(build_playwright_check(theme_xml) + "\n", encoding="utf-8")

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "blog_id": 37,
        "language": "ja",
        "theme_path": str(theme_path),
        "playwright_check_path": str(playwright_path),
        "profile_url": profile_url,
        "profile_upload": upload_report,
        "marker": THEME_MARKER,
        "verify_urls": VERIFY_URLS,
        "validation": validation,
        "apply": {
            "method": "Paste the full XML into Blogger Theme > Edit HTML.",
            "post_html_republish": False,
        },
    }
    report_path = timestamped_path(report_dir, str(args.report_prefix), "json")
    report["report_path"] = str(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
