from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


DEFAULT_REPORT_DIR = Path(r"D:\Donggri_Runtime\BloggerGent\storage\travel\reports")
THEME_MARKER = "donggri-spanish-travel-theme-script"
DEFAULT_VERIFY_URLS = [
    "https://donggri-corea.blogspot.com/",
    "https://donggri-corea.blogspot.com/search/label/Viajes",
    "https://donggri-corea.blogspot.com/search/label/Cultura",
    "https://donggri-corea.blogspot.com/search/label/Gastronom%C3%ADa",
    "https://donggri-corea.blogspot.com/2026/04/guia-del-festival-de-tulipanes-de-seoul.html",
]


THEME_XML = r'''<?xml version="1.0" encoding="UTF-8" ?>
<!DOCTYPE html>
<html b:css='false' b:defaultwidgetversion='2' b:layoutsVersion='3' b:responsive='true' b:templateUrl='custom' b:templateVersion='1.0.0' expr:dir='data:blog.languageDirection' expr:lang='data:blog.locale' xmlns='http://www.w3.org/1999/xhtml' xmlns:b='http://www.google.com/2005/gml/b' xmlns:data='http://www.google.com/2005/gml/data' xmlns:expr='http://www.google.com/2005/gml/expr'>
<head>
  <b:include data='blog' name='all-head-content'/>
  <title><data:view.title.escaped/></title>
  <meta content='width=device-width, initial-scale=1.0' name='viewport'/>
  <link href='https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&amp;family=Inter:wght@300;400;600&amp;display=swap' rel='stylesheet'/>
  <script src='https://cdn.tailwindcss.com?plugins=forms,container-queries'/>
  <script>
  //<![CDATA[
    tailwind.config = {
      theme: {
        extend: {
          colors: {
            primary: '#2D2424',
            accent: '#E05D5D',
            'light-brown': '#FDF6F0'
          },
          fontFamily: {
            headline: ['Outfit', 'sans-serif'],
            body: ['Inter', 'sans-serif']
          }
        }
      }
    };
  //]]>
  </script>

  <b:skin><![CDATA[
    body { font-family: 'Inter', sans-serif; background: #FDF6F0; margin: 0; padding: 0; color: #1f2937; }
    .editorial-grid { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 2.5rem; align-items: start; }
    @media (max-width: 1024px) { .editorial-grid { grid-template-columns: 1fr; gap: 2rem; } }
    .line-clamp-1 { display: -webkit-box; -webkit-line-clamp: 1; -webkit-box-orient: vertical; overflow: hidden; }
    .line-clamp-2 { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
    .content-stack { display: flex; flex-direction: column; gap: 2rem; }
    .nav-link { border-bottom: 2px solid transparent; padding-bottom: 3px; }
    .nav-link.is-active { color: #2D2424 !important; border-bottom-color: #E05D5D; }
    .ad-shell:has(.ads.no-items), .ad-shell.is-empty, .ads.no-items { display: none !important; }
    .sidebar-box { background: #ffffff; padding: 20px; border-radius: 1rem; box-shadow: 0 4px 20px rgba(45,36,36,0.05); margin-bottom: 12px !important; }
    .sidebar-title { font-size: 11px !important; font-weight: 800; text-transform: uppercase; letter-spacing: 0.2em; color: #E05D5D; margin-bottom: 12px; border-bottom: 2px solid #E05D5D; padding-bottom: 4px; display: inline-block; }
    .sidebar-item { display: flex; gap: 12px; margin-bottom: 10px; align-items: center; justify-content: space-between; }
    .sidebar-item .text-side { flex: 1; min-width: 0; }
    .sidebar-item img { width: 100px; height: 60px; border-radius: 0.75rem; object-fit: cover; background: #FDF6F0; flex-shrink: 0; }
    .sidebar-item a { font-size: 11px !important; font-weight: 700; line-height: 1.35; color: #2D2424; text-decoration: none; }
    .sidebar-item a:hover { color: #E05D5D; }
    .post-card-thumb img[data-thumb-state="loading"],
    .sidebar-item img[data-thumb-state="loading"] { opacity: 0.55; }
    .related-blog-card { display: block; border: 1px solid rgba(224,93,93,0.18); border-radius: 0.9rem; padding: 14px; background: #fff7f3; text-decoration: none; transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease; }
    .related-blog-card:hover { transform: translateY(-1px); border-color: rgba(224,93,93,0.45); box-shadow: 0 8px 18px rgba(45,36,36,0.08); }
    .related-blog-badge { display: inline-flex; align-items: center; justify-content: center; min-width: 34px; height: 22px; padding: 0 8px; border-radius: 999px; background: #E05D5D; color: #ffffff; font-size: 10px; font-weight: 800; letter-spacing: 0.12em; text-transform: uppercase; }
    .related-blog-title { font-family: 'Outfit', sans-serif; font-size: 13px; font-weight: 800; line-height: 1.35; color: #2D2424; margin-top: 10px; }
    .related-blog-desc { font-size: 11px; line-height: 1.55; color: #6b7280; margin-top: 6px; }
    .article-content > h1:first-child {
      font-family: 'Outfit', sans-serif;
      font-size: 2.35rem;
      line-height: 1.12;
      font-weight: 800;
      color: #2D2424;
      margin: 0 0 2rem;
      letter-spacing: -0.01em;
    }
    .post-body img { border-radius: 12px; }
    .post-body h2 { font-family: 'Outfit', sans-serif; font-size: 1.75rem; font-weight: 800; color: #2D2424; margin: 2.5rem 0 1rem 0; border-bottom: 2px solid #FDF6F0; padding-bottom: 0.5rem; }
    .post-body blockquote { background-color: #FDF6F0; border-left: 5px solid #E05D5D; padding: 1.25rem; margin: 2rem 0; border-radius: 0 0.75rem 0.75rem 0; color: #2D2424; }
    .post-body table { width: 100%; border-collapse: collapse; margin: 2rem 0; background: #ffffff; border-radius: 0.5rem; display: block; overflow-x: auto; white-space: nowrap; }
    .post-body th { background-color: #FDF6F0; color: #2D2424; font-weight: 800; padding: 1rem; border-bottom: 2px solid #E05D5D; text-align: left; }
    .post-body td { padding: 1rem; border-bottom: 1px solid #f1f5f9; color: #475569; }
    @media (max-width: 640px) {
      main { padding-left: 1rem !important; padding-right: 1rem !important; }
      .article-content > h1:first-child { font-size: 1.95rem; }
    }
  ]]></b:skin>
</head>

<body class='text-slate-800'>
  <nav class='fixed top-0 w-full z-50 bg-white/90 backdrop-blur-md border-b border-orange-100'>
    <div class='flex justify-between items-center px-8 py-4 max-w-7xl mx-auto w-full'>
      <a class='text-2xl font-black font-headline tracking-tighter text-primary uppercase' expr:href='data:blog.homepageUrl'>Donggri Corea</a>
      <div class='hidden md:flex gap-8 font-headline text-sm font-semibold text-slate-500'>
        <a class='nav-link hover:text-accent transition-colors' data-nav-key='home' expr:href='data:blog.homepageUrl'>Inicio</a>
        <a class='nav-link hover:text-accent transition-colors' data-nav-key='viajes' href='/search/label/Viajes'>Viajes</a>
        <a class='nav-link hover:text-accent transition-colors' data-nav-key='cultura' href='/search/label/Cultura'>Cultura</a>
        <a class='nav-link hover:text-accent transition-colors' data-nav-key='gastronomia' href='/search/label/Gastronom%C3%ADa'>Gastronom&#237;a</a>
        <a class='nav-link hover:text-accent transition-colors' data-nav-key='about' href='/p/sobre-nosotros.html'>Sobre Nosotros</a>
      </div>
    </div>
  </nav>

  <main class='pt-24 max-w-7xl mx-auto px-8 pb-20'>
    <div class='editorial-grid'>
      <div class='content-stack'>
        <b:if cond='data:view.isMultipleItems'>
          <div class='relative w-full h-[500px] rounded-3xl overflow-hidden bg-primary shadow-2xl group' id='js-auto-hero'>
            <div class='absolute inset-0 flex items-center justify-center text-white/20 animate-pulse uppercase tracking-widest'>Cargando Corea...</div>
          </div>
        </b:if>

        <b:if cond='not data:blog.isMobile'>
          <div class='ad-shell rounded-3xl border border-orange-100 bg-white p-4 shadow-sm' id='ad-shell-main-top'>
            <b:section class='ads' id='ads-main-top' maxwidgets='1' showaddelement='yes'/>
          </div>
        </b:if>

        <b:if cond='data:view.isMultipleItems and (data:view.isHomepage or data:view.url == data:blog.homepageUrl) and not data:blog.isMobile'>
          <section class='space-y-10' data-fallback='https://placehold.co/1200x675?text=Donggri' id='category-latest'>
            <div class='space-y-3' data-label='Viajes'>
              <div class='flex items-center justify-between'>
                <h3 class='text-[12px] font-black uppercase tracking-[0.25em] text-slate-500'>Viajes</h3>
                <a class='text-[10px] font-bold uppercase tracking-widest text-accent' href='/search/label/Viajes'>Ver todo</a>
              </div>
              <div class='grid grid-cols-1 md:grid-cols-3 gap-6 category-items'><div class='text-[11px] text-slate-400'>Cargando...</div></div>
            </div>
            <div class='space-y-3' data-label='Cultura'>
              <div class='flex items-center justify-between'>
                <h3 class='text-[12px] font-black uppercase tracking-[0.25em] text-slate-500'>Cultura</h3>
                <a class='text-[10px] font-bold uppercase tracking-widest text-accent' href='/search/label/Cultura'>Ver todo</a>
              </div>
              <div class='grid grid-cols-1 md:grid-cols-3 gap-6 category-items'><div class='text-[11px] text-slate-400'>Cargando...</div></div>
            </div>
            <div class='space-y-3' data-label='Gastronom&#237;a'>
              <div class='flex items-center justify-between'>
                <h3 class='text-[12px] font-black uppercase tracking-[0.25em] text-slate-500'>Gastronom&#237;a</h3>
                <a class='text-[10px] font-bold uppercase tracking-widest text-accent' href='/search/label/Gastronom%C3%ADa'>Ver todo</a>
              </div>
              <div class='grid grid-cols-1 md:grid-cols-3 gap-6 category-items'><div class='text-[11px] text-slate-400'>Cargando...</div></div>
            </div>
          </section>
        </b:if>

        <b:section class='main' id='main-section' showaddelement='yes'>
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
              <b:widget-setting name='postLabelsLabel'>Etiqueta 1, Etiqueta 2</b:widget-setting>
              <b:widget-setting name='showTimestamp'>false</b:widget-setting>
              <b:widget-setting name='postsPerAd'>1</b:widget-setting>
              <b:widget-setting name='showBacklinks'>false</b:widget-setting>
              <b:widget-setting name='style.bordercolor'>#ffffff</b:widget-setting>
              <b:widget-setting name='showInlineAds'>false</b:widget-setting>
              <b:widget-setting name='showReactions'>false</b:widget-setting>
            </b:widget-settings>
            <b:includable id='main' var='top'>
              <b:if cond='data:view.isMultipleItems'>
                <div class='grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8'>
                  <b:loop index='i' values='data:posts' var='post'>
                    <b:if cond='not data:newerPageUrl'>
                      <b:if cond='data:i != 0'><b:include data='post' name='postItem'/></b:if>
                    <b:else/>
                      <b:if cond='data:i &lt; 3'><b:include data='post' name='postItem'/></b:if>
                    </b:if>
                  </b:loop>
                </div>
                <div class='flex justify-between mt-10 pt-6 border-t border-orange-100'>
                  <b:if cond='data:newerPageUrl'><a class='text-xs font-bold uppercase hover:text-accent tracking-widest transition-colors' expr:href='data:newerPageUrl'>&#8592; Nuevos</a><b:else/><div/></b:if>
                  <b:if cond='data:olderPageUrl'><a class='text-xs font-bold uppercase hover:text-accent tracking-widest transition-colors' expr:href='data:olderPageUrl'>Anteriores &#8594;</a></b:if>
                </div>
              </b:if>

              <b:if cond='data:view.isSingleItem'>
                <b:loop values='data:posts' var='post'>
                  <article class='prose prose-slate prose-lg max-w-none pt-10 post-body'>
                    <div class='font-body text-slate-700 leading-relaxed article-content'><data:post.body/></div>
                  </article>
                </b:loop>
              </b:if>
            </b:includable>

            <b:includable id='postItem' var='post'>
              <div class='group js-post-card' expr:data-post-url='data:post.url'>
                <div class='post-card-thumb relative aspect-[4/5] rounded-3xl overflow-hidden bg-[#FDF6F0] mb-4 shadow-sm'>
                  <a expr:href='data:post.url'>
                    <b:if cond='data:post.featuredImage'>
                      <img class='w-full h-full object-cover group-hover:scale-105 transition-all duration-500' data-thumb-state='loading' expr:src='data:post.featuredImage'/>
                    <b:else/>
                      <img class='w-full h-full object-cover group-hover:scale-105 transition-all duration-500' data-thumb-state='fallback' src='https://placehold.co/1200x675?text=Donggri'/>
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
        </b:section>

        <b:if cond='data:view.isMultipleItems and not data:blog.isMobile'>
          <div class='ad-shell rounded-3xl border border-orange-100 bg-white p-4 shadow-sm' id='ad-shell-list-bottom'>
            <b:section class='ads' id='ads-home-mid' maxwidgets='1' showaddelement='yes'/>
          </div>
        </b:if>

        <b:if cond='data:view.isSingleItem and not data:blog.isMobile'>
          <div class='ad-shell rounded-3xl border border-orange-100 bg-white p-4 shadow-sm' id='ad-shell-post-bottom'>
            <b:section class='ads' id='ads-post-bottom' maxwidgets='1' showaddelement='yes'/>
          </div>
        </b:if>
      </div>

      <aside class='hidden lg:flex flex-col gap-4 sticky top-32 h-fit'>
        <div class='sidebar-box'>
          <h3 class='sidebar-title'>Sobre Nosotros</h3>
          <div class='text-center space-y-3'>
            <div class='w-16 h-16 bg-light-brown rounded-full mx-auto flex items-center justify-center text-accent text-xl font-black'>DG</div>
            <p class='text-[11px] leading-relaxed text-slate-600'>Tu gu&#237;a real para descubrir Corea del Sur.</p>
          </div>
        </div>

        <div class='sidebar-box'>
          <h3 class='sidebar-title'>Tendencias</h3>
          <b:section class='sidebar' id='sidebar-trending-section' maxwidgets='1' showaddelement='yes'>
            <b:widget id='PopularPosts1' locked='false' title='' type='PopularPosts' version='2' visible='true'>
              <b:widget-settings>
                <b:widget-setting name='numItemsToShow'>6</b:widget-setting>
                <b:widget-setting name='showThumbnails'>true</b:widget-setting>
                <b:widget-setting name='showSnippets'>false</b:widget-setting>
                <b:widget-setting name='timeRange'>ALL_TIME</b:widget-setting>
              </b:widget-settings>
              <b:includable id='main'>
                <b:loop values='data:posts' var='post'>
                  <div class='sidebar-item' data-thumb-state='loading'>
                    <div class='text-side'><a class='line-clamp-2' expr:href='data:post.url'><data:post.title/></a></div>
                    <a expr:href='data:post.url'><img data-thumb-state='loading' expr:src='data:post.featuredImage'/></a>
                  </div>
                </b:loop>
              </b:includable>
            </b:widget>
          </b:section>
        </div>

        <div class='sidebar-box'>
          <b:section class='ads' id='ads-sidebar' maxwidgets='1' showaddelement='yes'/>
        </div>

        <div class='sidebar-box' id='sidebar-related-blogs'>
          <h3 class='sidebar-title'>Blogs Relacionados</h3>
          <div class='space-y-3'>
            <a class='related-blog-card' href='https://donggri-korea.blogspot.com/'>
              <span class='related-blog-badge'>EN</span>
              <div class='related-blog-title'>Donggri Korea</div>
              <div class='related-blog-desc'>Gu&#237;as locales en ingl&#233;s sobre viajes, cultura y rutas pr&#225;cticas por Corea.</div>
            </a>
            <a class='related-blog-card' href='https://donggri-kankoku.blogspot.com/'>
              <span class='related-blog-badge'>JP</span>
              <div class='related-blog-title'>Donggri Kankoku</div>
              <div class='related-blog-desc'>Versi&#243;n japonesa del blog con gu&#237;as locales, barrios y recorridos de temporada.</div>
            </a>
          </div>
        </div>
      </aside>
    </div>
  </main>

  <footer class='w-full py-16 bg-primary text-white mt-20 text-center'>
    <div class='max-w-7xl mx-auto px-8 space-y-4'>
      <div class='text-2xl font-black font-headline tracking-tighter uppercase'>Donggri Corea</div>
      <div class='flex flex-wrap justify-center gap-6 text-[10px] font-bold uppercase tracking-[0.3em] text-white/70 mt-8'>
        <a class='hover:text-white' href='/p/privacidad.html'>Privacidad</a>
        <a class='hover:text-white' href='/p/terminos.html'>T&#233;rminos</a>
        <a class='hover:text-white' href='/p/contacto.html'>Contacto</a>
        <a class='hover:text-white' href='/p/politica-editorial.html'>Pol&#237;tica Editorial</a>
        <a class='hover:text-white' href='/p/faq.html'>FAQ</a>
      </div>
      <p class='text-[10px] text-white/50 mt-6 tracking-widest'>&#169; 2026 DONGGRI COREA. ALL RIGHTS RESERVED.</p>
    </div>
  </footer>

  <script id='donggri-spanish-travel-theme-script' type='text/javascript'>
  //<![CDATA[
  (function(){
    "use strict";

    var FALLBACK_IMAGE = "https://placehold.co/1200x675?text=Donggri";
    var R2_RE = /https:\/\/api\.dongriarchive\.com\/assets\/travel-blogger\/[^"'<>\\\s)]+?\.webp/ig;
    var htmlCache = new Map();
    var feedCache = new Map();

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

    function currentPath() {
      return (window.location.pathname || "/").replace(/\/+$/, "") || "/";
    }

    function getCurrentLabel() {
      var match = currentPath().match(/^\/search\/label\/(.+)$/i);
      if (!match) return "";
      try {
        return decodeURIComponent(String(match[1] || "").replace(/\+/g, " "));
      } catch (_err) {
        return "";
      }
    }

    function firstR2FromHtml(html) {
      R2_RE.lastIndex = 0;
      var matches = String(html || "").match(R2_RE);
      if (!matches || !matches.length) return "";
      for (var i = 0; i < matches.length; i += 1) {
        var url = String(matches[i] || "");
        if (url.indexOf("blogger_img_proxy") === -1) return url;
      }
      return "";
    }

    function entryHtml(entry) {
      return entry && entry.content ? entry.content.$t : (entry && entry.summary ? entry.summary.$t : "");
    }

    function entryLink(entry) {
      var links = entry && entry.link ? entry.link : [];
      for (var i = 0; i < links.length; i += 1) {
        if (links[i].rel === "alternate") return links[i].href || "#";
      }
      return "#";
    }

    function entryImage(entry) {
      return firstR2FromHtml(entryHtml(entry));
    }

    function fetchJson(url) {
      if (feedCache.has(url)) return Promise.resolve(feedCache.get(url));
      return fetch(url, { credentials: "same-origin" })
        .then(function(response) {
          if (!response.ok) throw new Error("feed_error");
          return response.json();
        })
        .then(function(data) {
          feedCache.set(url, data);
          return data;
        });
    }

    function fetchPostHtml(url) {
      var key = cleanUrl(url);
      if (!key) return Promise.resolve("");
      if (htmlCache.has(key)) return Promise.resolve(htmlCache.get(key));
      return fetch(key, { credentials: "same-origin" })
        .then(function(response) { return response.ok ? response.text() : ""; })
        .then(function(html) {
          htmlCache.set(key, html || "");
          return html || "";
        })
        .catch(function() { return ""; });
    }

    function fetchFirstR2Image(url) {
      return fetchPostHtml(url).then(firstR2FromHtml);
    }

    function setImage(img, src, state) {
      if (!img) return;
      img.removeAttribute("srcset");
      img.src = src || FALLBACK_IMAGE;
      img.setAttribute("data-thumb-state", state || (src ? "r2" : "fallback"));
    }

    function markActiveNav() {
      var path = currentPath();
      var label = getCurrentLabel();
      var activeKey = "home";
      if (label === "Viajes") activeKey = "viajes";
      else if (label === "Cultura") activeKey = "cultura";
      else if (label === "Gastronom\u00eda") activeKey = "gastronomia";
      else if (/\/p\/sobre-nosotros\.html$/i.test(path)) activeKey = "about";

      Array.prototype.slice.call(document.querySelectorAll("nav .nav-link")).forEach(function(link) {
        link.classList.toggle("is-active", link.getAttribute("data-nav-key") === activeKey);
      });
    }

    function hideEmptyAds() {
      Array.prototype.slice.call(document.querySelectorAll(".ad-shell")).forEach(function(shell) {
        var hasContent = cleanText(shell.textContent).length > 0 || !!shell.querySelector("iframe,ins,img,script:not([type])");
        shell.classList.toggle("is-empty", !hasContent);
      });
    }

    function heroFeedUrl() {
      var label = getCurrentLabel();
      if (label) {
        return "/feeds/posts/default/-/" + encodeURIComponent(label) + "?alt=json&max-results=1";
      }
      return "/feeds/posts/default?max-results=1&alt=json";
    }

    function hydrateHero() {
      var hero = document.getElementById("js-auto-hero");
      if (!hero) return;
      fetchJson(heroFeedUrl())
        .then(function(data) {
          var entries = data && data.feed && data.feed.entry ? data.feed.entry : [];
          if (!entries.length) return;
          var entry = entries[0];
          var title = entry && entry.title ? entry.title.$t : "Donggri Corea";
          var link = entryLink(entry);
          var img = entryImage(entry) || FALLBACK_IMAGE;

          hero.innerHTML = "";
          var anchor = document.createElement("a");
          anchor.href = link;
          anchor.className = "block h-full relative";

          var image = document.createElement("img");
          image.className = "absolute inset-0 w-full h-full object-cover";
          image.src = img;
          image.alt = "";
          image.setAttribute("data-thumb-state", img ? "r2" : "fallback");
          image.onerror = function() { setImage(image, FALLBACK_IMAGE, "fallback"); };

          var overlay = document.createElement("div");
          overlay.className = "absolute inset-0 bg-gradient-to-t from-black/70 to-transparent";

          var content = document.createElement("div");
          content.className = "absolute bottom-6 left-6 right-6 text-white";

          var meta = document.createElement("div");
          meta.className = "text-xs uppercase tracking-[0.2em]";
          meta.textContent = "\u00daltimo: " + cleanText(entry && entry.published && entry.published.$t ? entry.published.$t.slice(0, 10) : "");

          var heading = document.createElement("h2");
          heading.className = "text-2xl md:text-4xl font-black mt-2 font-headline leading-tight";
          heading.textContent = title;

          content.appendChild(meta);
          content.appendChild(heading);
          anchor.appendChild(image);
          anchor.appendChild(overlay);
          anchor.appendChild(content);
          hero.appendChild(anchor);
        })
        .catch(function() {
          hero.innerHTML = "";
        });
    }

    function renderEmpty(list, message) {
      list.innerHTML = "";
      var empty = document.createElement("div");
      empty.className = "text-[11px] text-slate-400 col-span-full";
      empty.textContent = message;
      list.appendChild(empty);
    }

    function createCategoryItem(entry, fallback) {
      var title = entry && entry.title ? entry.title.$t : "Sin t\u00edtulo";
      var link = entryLink(entry);
      var imageUrl = entryImage(entry) || fallback || FALLBACK_IMAGE;

      var item = document.createElement("article");
      item.className = "group rounded-3xl border border-orange-100 bg-white overflow-hidden shadow-sm hover:shadow-md transition-shadow";

      var anchor = document.createElement("a");
      anchor.href = link;
      anchor.className = "block";

      var imageWrap = document.createElement("div");
      imageWrap.className = "aspect-[4/3] bg-[#FDF6F0] overflow-hidden";

      var img = document.createElement("img");
      img.className = "w-full h-full object-cover transition-transform duration-500 group-hover:scale-105";
      img.src = imageUrl;
      img.alt = "";
      img.setAttribute("data-thumb-state", imageUrl && imageUrl.indexOf("api.dongriarchive.com/assets/travel-blogger/") === 0 ? "r2" : "fallback");
      img.onerror = function() { setImage(img, fallback || FALLBACK_IMAGE, "fallback"); };

      var textWrap = document.createElement("div");
      textWrap.className = "p-4";

      var titleNode = document.createElement("div");
      titleNode.className = "line-clamp-2 text-[12px] font-bold text-primary group-hover:text-accent transition-colors";
      titleNode.textContent = title;

      imageWrap.appendChild(img);
      textWrap.appendChild(titleNode);
      anchor.appendChild(imageWrap);
      anchor.appendChild(textWrap);
      item.appendChild(anchor);
      return item;
    }

    function hydrateCategoryLatest() {
      var categorySection = document.getElementById("category-latest");
      if (!categorySection) return;
      var fallback = categorySection.getAttribute("data-fallback") || FALLBACK_IMAGE;
      Array.prototype.slice.call(categorySection.querySelectorAll("[data-label]")).forEach(function(card) {
        var label = card.getAttribute("data-label");
        var list = card.querySelector(".category-items");
        if (!label || !list) return;
        fetchJson("/feeds/posts/default/-/" + encodeURIComponent(label) + "?alt=json&max-results=3")
          .then(function(data) {
            var entries = data && data.feed && data.feed.entry ? data.feed.entry : [];
            list.innerHTML = "";
            if (!entries.length) {
              renderEmpty(list, "Sin publicaciones");
              return;
            }
            entries.slice(0, 3).forEach(function(entry) {
              list.appendChild(createCategoryItem(entry, fallback));
            });
          })
          .catch(function() {
            renderEmpty(list, "No se pudo cargar");
          });
      });
    }

    function hydratePostCards() {
      Array.prototype.slice.call(document.querySelectorAll(".js-post-card[data-post-url]")).forEach(function(card) {
        var url = card.getAttribute("data-post-url");
        var img = card.querySelector("img");
        if (!url || !img) return;
        setImage(img, img.src || FALLBACK_IMAGE, "loading");
        fetchFirstR2Image(url).then(function(r2) {
          setImage(img, r2 || FALLBACK_IMAGE, r2 ? "r2" : "fallback");
        });
      });
    }

    function hydrateTrendingNowImages() {
      Array.prototype.slice.call(document.querySelectorAll("#sidebar-trending-section .sidebar-item")).forEach(function(item) {
        var link = item.querySelector(".text-side a[href]") || item.querySelector("a[href]");
        var img = item.querySelector("img");
        if (!link || !img) return;
        item.setAttribute("data-thumb-state", "loading");
        setImage(img, img.src || FALLBACK_IMAGE, "loading");
        fetchFirstR2Image(link.href).then(function(r2) {
          setImage(img, r2 || FALLBACK_IMAGE, r2 ? "r2" : "fallback");
          item.setAttribute("data-thumb-state", r2 ? "r2" : "fallback");
        });
      });
    }

    function boot() {
      markActiveNav();
      hideEmptyAds();
      hydrateHero();
      hydrateCategoryLatest();
      hydratePostCards();
      hydrateTrendingNowImages();
      window.setTimeout(hideEmptyAds, 1500);
    }

    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", boot, { once: true });
    } else {
      boot();
    }
  })();
  //]]>
  </script>
</body>
</html>
'''


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the full fixed Spanish Travel Blogger theme XML.")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--report-prefix", default="spanish-travel-theme-full-fixed")
    return parser.parse_args()


def timestamped_path(report_dir: Path, prefix: str, suffix: str) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return report_dir / f"{prefix}-{stamp}.{suffix}"


def extract_theme_script(xml: str) -> str:
    match = re.search(
        r"<script\s+id='donggri-spanish-travel-theme-script'[^>]*>\s*//<!\[CDATA\[(?P<script>[\s\S]*?)//\]\]>\s*</script>",
        xml,
        flags=re.IGNORECASE,
    )
    if not match:
        raise ValueError("Theme script marker was not found.")
    return match.group("script").strip()


def build_playwright_check(theme_xml: str) -> str:
    script = extract_theme_script(theme_xml)
    script_literal = json.dumps(script)
    urls_literal = json.dumps(DEFAULT_VERIFY_URLS, ensure_ascii=False)
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
      loadingCount: Array.from(document.querySelectorAll("body *")).filter(el => el.children.length === 0 && /Cargando/i.test(el.textContent || "")).length,
      h1Count: document.querySelectorAll("h1").length,
      activeNav: Array.from(document.querySelectorAll("nav .nav-link.is-active")).map(a => a.textContent.trim()),
      heroImages: Array.from(document.querySelectorAll("#js-auto-hero img")).map(img => img.src),
      categoryImages: Array.from(document.querySelectorAll("#category-latest img")).map(img => img.src),
      postCardImages: Array.from(document.querySelectorAll("#main-section .js-post-card img")).slice(0, 8).map(img => img.src),
      trendingImages: Array.from(document.querySelectorAll("#sidebar-trending-section img")).map(img => img.src),
      relatedBlogCards: Array.from(document.querySelectorAll("#sidebar-related-blogs .related-blog-card")).map(a => a.href),
      visibleEmptyAdShells: Array.from(document.querySelectorAll(".ad-shell")).filter(el => getComputedStyle(el).display !== "none" && !el.textContent.trim() && !el.querySelector("iframe,ins,img")).length
    }})));
  }}
  return results;
}}"""


def validate_theme(xml: str) -> dict[str, object]:
    parser = ET.XMLParser()
    ET.fromstring(xml.encode("utf-8"), parser=parser)
    return {
        "xml_parse_ok": True,
        "theme_marker_present": THEME_MARKER in xml,
        "blog1_present": "id='Blog1'" in xml,
        "main_section_self_closing_removed": "<b:section class='main' id='main-section' showaddelement='yes'/>" not in xml,
        "all_head_content_present": "<b:include data='blog' name='all-head-content'/>" in xml,
        "label_links_present": {
            "viajes": "/search/label/Viajes" in xml,
            "cultura": "/search/label/Cultura" in xml,
            "gastronomia": "/search/label/Gastronom%C3%ADa" in xml,
        },
        "related_blogs_present": {
            "english": "https://donggri-korea.blogspot.com/" in xml,
            "japanese": "https://donggri-kankoku.blogspot.com/" in xml,
        },
        "ads_sections_present": {
            "ads-main-top": "id='ads-main-top'" in xml,
            "ads-home-mid": "id='ads-home-mid'" in xml,
            "ads-post-bottom": "id='ads-post-bottom'" in xml,
            "ads-sidebar": "id='ads-sidebar'" in xml,
        },
    }


def main() -> int:
    args = parse_args()
    report_dir = Path(str(args.report_dir)).resolve()
    theme_xml = THEME_XML.strip() + "\n"

    validation = validate_theme(theme_xml)

    xml_path = timestamped_path(report_dir, str(args.report_prefix), "xml")
    xml_path.write_text(theme_xml, encoding="utf-8")

    playwright_path = timestamped_path(report_dir, str(args.report_prefix), "playwright.js")
    playwright_path.write_text(build_playwright_check(theme_xml) + "\n", encoding="utf-8")

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "theme_path": str(xml_path),
        "playwright_check_path": str(playwright_path),
        "marker": THEME_MARKER,
        "verify_urls": DEFAULT_VERIFY_URLS,
        "validation": validation,
        "apply": {
            "method": "Paste the full XML into Blogger Theme > Edit HTML. Blogger API theme update is not used.",
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
