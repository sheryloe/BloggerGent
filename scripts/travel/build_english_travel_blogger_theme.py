from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


DEFAULT_REPORT_DIR = Path(r"D:\Donggri_Runtime\BloggerGent\storage\travel\reports")
THEME_MARKER = "donggri-travel-theme-script"
DEFAULT_VERIFY_URLS = [
    "https://donggri-korea.blogspot.com/",
    "https://donggri-korea.blogspot.com/search/label/Travel",
    "https://donggri-korea.blogspot.com/search/label/Culture",
    "https://donggri-korea.blogspot.com/search/label/Food",
    "https://donggri-korea.blogspot.com/2026/03/jeonju-dawn-hanok-alley-transit-loop.html",
]


THEME_XML = r'''<?xml version="1.0" encoding="UTF-8" ?>
<!DOCTYPE html>
<html b:css='false' b:defaultwidgetversion='2' b:layoutsVersion='3' b:responsive='true' b:templateUrl='custom' b:templateVersion='1.0.1' expr:dir='data:blog.languageDirection' lang='en' xml:lang='en' xmlns='http://www.w3.org/1999/xhtml' xmlns:b='http://www.google.com/2005/gml/b' xmlns:data='http://www.google.com/2005/gml/data' xmlns:expr='http://www.google.com/2005/gml/expr'>
<head>
  <!-- Google tag (gtag.js) -->
  <script async='async' src='https://www.googletagmanager.com/gtag/js?id=G-5T125DHEDY'/>
  <script>
  //<![CDATA[
    window.dataLayer = window.dataLayer || [];
    function gtag(){dataLayer.push(arguments);}
    gtag('js', new Date());
    gtag('config', 'G-5T125DHEDY');
  //]]>
  </script>

  <meta content='width=device-width, initial-scale=1.0' name='viewport'/>
  <title><data:view.title.escaped/></title>
  <b:include data='blog' name='all-head-content'/>
  <b:if cond='data:view.description'>
    <meta expr:content='data:view.description.escaped' name='description'/>
  <b:elseif cond='data:blog.metaDescription'/>
    <meta expr:content='data:blog.metaDescription.escaped' name='description'/>
  <b:else/>
    <meta content='Practical Korea travel routes, local timing, culture, food, and itinerary decisions from Donggri Korea.' name='description'/>
  </b:if>
  <meta content='0e57cc63efae83ad8bebac4098cc6a19ec56aad7' name='naver-site-verification'/>

  <link href='https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&amp;family=Be+Vietnam+Pro:wght@300;400;500;600&amp;display=swap' rel='stylesheet'/>

  <b:skin><![CDATA[
    :root { --primary:#1a1a1a; --accent:#fe932c; --surface:#ffffff; --muted:#64748b; --border:#e2e8f0; --light-brown:#f7f2ed; }
    * { box-sizing: border-box; }
    body { font-family: 'Be Vietnam Pro', sans-serif; background: #f8f9ff; margin:0; padding:0; color:#0f172a; }
    a { color: inherit; }
    img { max-width: 100%; display: block; }
    nav { position: fixed; top: 0; left: 0; width: 100%; z-index: 50; background: rgba(255,255,255,0.86); backdrop-filter: blur(12px); box-shadow: 0 1px 4px rgba(15,23,42,0.08); border-bottom: 1px solid #f1f5f9; }
    nav > div { display: flex; justify-content: space-between; align-items: center; width: 100%; max-width: 80rem; margin-left: auto; margin-right: auto; padding: 1rem 2rem; }
    nav a { text-decoration: none; }
    nav > div > a { font-family: 'Plus Jakarta Sans', sans-serif; font-size: 1.5rem; line-height: 2rem; font-weight: 900; letter-spacing: -0.04em; color: var(--primary); }
    nav .nav-link { font-family: 'Plus Jakarta Sans', sans-serif; font-size: .875rem; line-height: 1.25rem; font-weight: 600; color: #475569; transition: color .18s ease; }
    nav .nav-link:hover { color: var(--primary); }
    main { padding-top: 6rem; max-width: 80rem; margin-left: auto; margin-right: auto; padding-left: 2rem; padding-right: 2rem; padding-bottom: 5rem; }
    footer { width: 100%; padding: 4rem 0; background: #fff; border-top: 1px solid var(--border); margin-top: 5rem; text-align: center; }
    footer > div { max-width: 80rem; margin-left: auto; margin-right: auto; padding-left: 2rem; padding-right: 2rem; }
    footer a { text-decoration: none; }
    .font-headline { font-family: 'Plus Jakarta Sans', sans-serif; }
    .font-body { font-family: 'Be Vietnam Pro', sans-serif; }
    .text-primary { color: var(--primary); }
    .text-accent { color: var(--accent); }
    .text-slate-900 { color:#0f172a; }
    .text-slate-700 { color:#334155; }
    .text-slate-500 { color:#475569; }
    .text-slate-400 { color:#64748b; }
    .text-slate-300 { color:#94a3b8; }
    .text-white { color:#fff; }
    .text-white\/20 { color:rgba(255,255,255,.2); }
    .bg-white { background:#fff; }
    .bg-slate-900 { background:#0f172a; }
    .bg-slate-200 { background:#e2e8f0; }
    .bg-slate-100 { background:#f1f5f9; }
    .relative { position: relative; }
    .absolute { position: absolute; }
    .inset-0 { inset: 0; }
    .hidden { display: none !important; }
    .flex { display:flex; }
    .grid { display:grid; }
    .block { display:block; }
    .items-center { align-items:center; }
    .justify-between { justify-content:space-between; }
    .justify-center { justify-content:center; }
    .flex-col { flex-direction:column; }
    .gap-2 { gap:.5rem; }
    .gap-4 { gap:1rem; }
    .gap-8 { gap:2rem; }
    .space-y-3 > * + * { margin-top:.75rem; }
    .space-y-6 > * + * { margin-top:1.5rem; }
    .space-y-10 > * + * { margin-top:2.5rem; }
    .p-3 { padding:.75rem; }
    .p-4 { padding:1rem; }
    .p-10 { padding:2.5rem; }
    .px-8 { padding-left:2rem; padding-right:2rem; }
    .py-4 { padding-top:1rem; padding-bottom:1rem; }
    .py-16 { padding-top:4rem; padding-bottom:4rem; }
    .pt-6 { padding-top:1.5rem; }
    .pt-10 { padding-top:2.5rem; }
    .pt-24 { padding-top:6rem; }
    .pb-20 { padding-bottom:5rem; }
    .mt-10 { margin-top:2.5rem; }
    .mt-20 { margin-top:5rem; }
    .mb-2 { margin-bottom:.5rem; }
    .mb-4 { margin-bottom:1rem; }
    .mx-auto { margin-left:auto; margin-right:auto; }
    .max-w-7xl { max-width:80rem; }
    .max-w-none { max-width:none; }
    .w-full { width:100%; }
    .h-full { height:100%; }
    .h-\[450px\] { height:450px; }
    .aspect-\[4\/5\] { aspect-ratio:4/5; }
    .aspect-\[4\/3\] { aspect-ratio:4/3; }
    .overflow-hidden { overflow:hidden; }
    .rounded-xl { border-radius:.75rem; }
    .rounded-2xl { border-radius:1rem; }
    .border { border:1px solid var(--border); }
    .border-t { border-top:1px solid var(--border); }
    .border-b { border-bottom:1px solid var(--border); }
    .border-slate-100 { border-color:#f1f5f9; }
    .border-slate-200 { border-color:#e2e8f0; }
    .shadow-sm { box-shadow:0 1px 3px rgba(15,23,42,.08); }
    .shadow-xl { box-shadow:0 20px 45px rgba(15,23,42,.18); }
    .sticky { position:sticky; }
    .top-32 { top:8rem; }
    .h-fit { height:fit-content; }
    .object-cover { object-fit:cover; }
    .opacity-60 { opacity:.6; }
    .leading-tight { line-height:1.15; }
    .leading-snug { line-height:1.35; }
    .leading-relaxed { line-height:1.75; }
    .tracking-tighter { letter-spacing:-.04em; }
    .tracking-widest { letter-spacing:.14em; }
    .tracking-\[0\.25em\] { letter-spacing:.25em; }
    .uppercase { text-transform:uppercase; }
    .font-medium { font-weight:500; }
    .font-bold { font-weight:700; }
    .font-black { font-weight:900; }
    .text-\[10px\] { font-size:10px; }
    .text-\[11px\] { font-size:11px; }
    .text-\[12px\] { font-size:12px; }
    .text-sm { font-size:.875rem; }
    .text-lg { font-size:1.125rem; }
    .text-2xl { font-size:1.5rem; line-height:2rem; }
    .text-3xl { font-size:1.875rem; line-height:2.25rem; }
    .transition-colors { transition: color .18s ease, border-color .18s ease; }
    .transition-shadow { transition: box-shadow .18s ease; }
    .transition-transform { transition: transform .5s ease; }
    .transition-all { transition: all .5s ease; }
    .duration-500 { transition-duration:.5s; }
    .duration-700 { transition-duration:.7s; }
    .hover\:shadow-md:hover { box-shadow:0 8px 20px rgba(15,23,42,.12); }
    .hover\:text-accent:hover { color:var(--accent); }
    .hover\:text-primary:hover { color:var(--primary); }
    .group:hover .group-hover\:scale-105 { transform:scale(1.05); }
    .group:hover .group-hover\:scale-110 { transform:scale(1.10); }
    .group:hover .group-hover\:text-accent { color:var(--accent); }
    .bg-gradient-to-t { background:linear-gradient(to top, rgba(0,0,0,.90), rgba(0,0,0,0)); }
    .from-black\/90, .via-transparent, .to-transparent { }
    .prose { color:#334155; }
    .prose-lg { font-size:1.06rem; }
    .animate-pulse { animation:pulse 1.6s ease-in-out infinite; }
    @keyframes pulse { 0%,100%{opacity:.45} 50%{opacity:1} }
    .editorial-grid { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 2.25rem; align-items: start; }
    .grid-cols-1 { grid-template-columns:repeat(1,minmax(0,1fr)); }
    .grid-cols-3 { grid-template-columns:repeat(3,minmax(0,1fr)); }
    @media (min-width: 768px) { .md\:flex { display:flex !important; } .md\:grid-cols-2 { grid-template-columns:repeat(2,minmax(0,1fr)); } .md\:h-\[550px\] { height:550px; } .md\:text-5xl { font-size:3rem; line-height:1.05; } }
    @media (min-width: 1024px) { .lg\:grid-cols-3 { grid-template-columns:repeat(3,minmax(0,1fr)); } .lg\:flex { display:flex !important; } }
    @media (max-width: 1024px) { .editorial-grid { grid-template-columns: 1fr; gap: 2rem; } }
    .line-clamp-1 { display: -webkit-box; -webkit-line-clamp: 1; -webkit-box-orient: vertical; overflow: hidden; }
    .line-clamp-2 { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
    .post-body .related-posts { display: none !important; }
    .nav-link.is-active { color: #1a1a1a !important; border-bottom: 2px solid #1a1a1a; }
    .nav-link { border-bottom: 2px solid transparent; padding-bottom: 2px; }
    .ad-shell:has(.ads.no-items), .ad-shell.is-empty, .ads.no-items { display: none !important; }
    .content-stack { display: flex; flex-direction: column; gap: 2rem; }
    .sidebar-box { padding: 16px; border-radius: 0.75rem; border: 1px solid rgba(0,0,0,0.06); margin-bottom: 8px !important; }
    .box-white { background: #ffffff; }
    .box-brown { background: #f7f2ed; }
    .sidebar-title { font-size: 10px !important; font-weight: 900; text-transform: uppercase; letter-spacing: 0.15em; color: #475569; margin-bottom: 12px; border-bottom: 1px solid rgba(0,0,0,0.08); padding-bottom: 8px; }
    .sidebar-item { display: flex; gap: 12px; margin-bottom: 10px; align-items: center; justify-content: space-between; }
    .sidebar-item .text-side { flex: 1; min-width: 0; }
    .sidebar-item img { width: 100px; height: 60px; border-radius: 0.35rem; object-fit: cover; background: #eee; flex-shrink: 0; }
    .sidebar-item a { font-size: 11px !important; font-weight: 700; line-height: 1.35; color: #1e293b; text-decoration: none; }
    .sidebar-item a:hover { color: #fe932c; }
    .post-card-thumb img[data-thumb-state="loading"],
    .sidebar-item img[data-thumb-state="loading"] { opacity: 0.55; }
    .article-content > h1:first-child {
      font-family: 'Plus Jakarta Sans', sans-serif;
      font-size: 2.25rem;
      line-height: 1.12;
      font-weight: 900;
      color: #1a1a1a;
      margin: 0 0 2rem;
      letter-spacing: -0.01em;
    }
    @media (max-width: 640px) {
      main { padding-left: 1rem !important; padding-right: 1rem !important; }
      .article-content > h1:first-child { font-size: 1.9rem; }
    }
  ]]></b:skin>
</head>

<body class='text-slate-900'>
  <nav class='fixed top-0 w-full z-50 bg-white/80 backdrop-blur-md shadow-sm border-b border-slate-100'>
    <div class='flex justify-between items-center px-8 py-4 max-w-7xl mx-auto w-full'>
      <a class='text-2xl font-black font-headline tracking-tighter text-primary' expr:href='data:blog.homepageUrl'>Donggri Korea</a>
      <div class='hidden md:flex gap-8 font-headline text-sm font-medium text-slate-500'>
        <a class='nav-link hover:text-primary transition-colors' data-nav-key='home' expr:href='data:blog.homepageUrl'>Home</a>
        <a class='nav-link hover:text-primary transition-colors' data-nav-key='travel' href='/search/label/Travel'>Travel</a>
        <a class='nav-link hover:text-primary transition-colors' data-nav-key='culture' href='/search/label/Culture'>Culture</a>
        <a class='nav-link hover:text-primary transition-colors' data-nav-key='food' href='/search/label/Food'>Food</a>
        <a class='nav-link hover:text-primary transition-colors' data-nav-key='about' href='/p/about-us.html'>About</a>
        <a class='nav-link hover:text-primary transition-colors' data-nav-key='contact' href='/p/contact.html'>Contact</a>
      </div>
    </div>
  </nav>

  <main class='pt-24 max-w-7xl mx-auto px-8 pb-20'>
    <div class='editorial-grid'>
      <div class='content-stack'>
        <b:if cond='data:view.isMultipleItems'>
          <div class='relative w-full h-[450px] md:h-[550px] rounded-2xl overflow-hidden bg-slate-900 shadow-xl group' id='js-auto-hero'>
            <div class='absolute inset-0 flex items-center justify-center text-white/20 animate-pulse'>DONGGRI KOREA...</div>
          </div>
        </b:if>

        <b:if cond='not data:blog.isMobile'>
          <div class='ad-shell rounded-2xl border border-slate-100 bg-white p-4 shadow-sm' id='ad-shell-main-top'>
            <b:section class='ads' id='ads-main-top' maxwidgets='1' showaddelement='yes'/>
          </div>
        </b:if>

        <b:if cond='data:view.isMultipleItems and (data:view.isHomepage or data:view.url == data:blog.homepageUrl) and not data:blog.isMobile'>
          <section class='space-y-10' data-fallback='https://images.unsplash.com/photo-1517154421773-0529f29ea451?q=80&amp;w=1200' id='category-latest'>
            <div class='space-y-3' data-label='Travel'>
              <div class='flex items-center justify-between'>
                <h3 class='text-[12px] font-black uppercase tracking-[0.25em] text-slate-400'>Travel</h3>
                <a class='text-[10px] font-bold uppercase tracking-widest text-accent' href='/search/label/Travel'>View All</a>
              </div>
              <div class='grid grid-cols-3 gap-4 category-items'><div class='text-[11px] text-slate-400'>Loading...</div></div>
            </div>
            <div class='space-y-3' data-label='Culture'>
              <div class='flex items-center justify-between'>
                <h3 class='text-[12px] font-black uppercase tracking-[0.25em] text-slate-400'>Culture</h3>
                <a class='text-[10px] font-bold uppercase tracking-widest text-accent' href='/search/label/Culture'>View All</a>
              </div>
              <div class='grid grid-cols-3 gap-4 category-items'><div class='text-[11px] text-slate-400'>Loading...</div></div>
            </div>
            <div class='space-y-3' data-label='Food'>
              <div class='flex items-center justify-between'>
                <h3 class='text-[12px] font-black uppercase tracking-[0.25em] text-slate-400'>Food</h3>
                <a class='text-[10px] font-bold uppercase tracking-widest text-accent' href='/search/label/Food'>View All</a>
              </div>
              <div class='grid grid-cols-3 gap-4 category-items'><div class='text-[11px] text-slate-400'>Loading...</div></div>
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
              <b:widget-setting name='postLabelsLabel'>라벨1, 라벨2</b:widget-setting>
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
                <div class='flex justify-between mt-10 pt-6 border-t border-slate-200'>
                  <b:if cond='data:newerPageUrl'><a class='text-xs font-bold uppercase hover:text-accent tracking-widest transition-colors' expr:href='data:newerPageUrl'>&#8592; Newer</a><b:else/><div/></b:if>
                  <b:if cond='data:olderPageUrl'><a class='text-xs font-bold uppercase hover:text-accent tracking-widest transition-colors' expr:href='data:olderPageUrl'>Older &#8594;</a></b:if>
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
                <div class='post-card-thumb relative aspect-[4/5] rounded-xl overflow-hidden bg-slate-200 mb-4 shadow-sm'>
                    <a expr:aria-label='data:post.title' expr:href='data:post.url'>
                    <b:if cond='data:post.featuredImage'>
                      <img class='w-full h-full object-cover group-hover:scale-110 transition-all duration-500' data-thumb-state='loading' decoding='async' expr:alt='data:post.title' expr:src='data:post.featuredImage' loading='lazy'/>
                    <b:else/>
                      <img class='w-full h-full object-cover group-hover:scale-110 transition-all duration-500' data-thumb-state='fallback' decoding='async' expr:alt='data:post.title' loading='lazy' src='https://images.unsplash.com/photo-1517154421773-0529f29ea451?q=80&amp;w=900'/>
                    </b:if>
                  </a>
                </div>
                <a expr:href='data:post.url'>
                  <h3 class='font-headline text-sm font-bold text-on-surface mb-2 group-hover:text-accent transition-colors line-clamp-2 leading-snug'><data:post.title/></h3>
                  <p class='text-slate-500 text-[11px] line-clamp-1'><data:post.snippet/></p>
                </a>
              </div>
            </b:includable>
          </b:widget>
        </b:section>

        <b:if cond='data:view.isMultipleItems and not data:blog.isMobile'>
          <div class='ad-shell rounded-2xl border border-slate-100 bg-white p-4 shadow-sm' id='ad-shell-list-bottom'>
            <b:section class='ads' id='ads-home-mid' maxwidgets='1' showaddelement='yes'/>
          </div>
        </b:if>

        <b:if cond='data:view.isSingleItem and not data:blog.isMobile'>
          <div class='ad-shell rounded-2xl border border-slate-100 bg-white p-4 shadow-sm' id='ad-shell-post-bottom'>
            <b:section class='ads' id='ads-post-bottom' maxwidgets='1' showaddelement='yes'/>
          </div>
        </b:if>
      </div>

      <aside class='hidden lg:flex flex-col gap-2 sticky top-32 h-fit'>
        <div class='sidebar-box box-white'>
          <h3 class='sidebar-title'>Trending Now</h3>
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
                    <a expr:aria-label='data:post.title' expr:href='data:post.url'><img data-thumb-state='loading' decoding='async' expr:alt='data:post.title' expr:src='data:post.featuredImage' loading='lazy'/></a>
                  </div>
                </b:loop>
              </b:includable>
            </b:widget>
          </b:section>
        </div>

        <div class='sidebar-box box-white'>
          <b:section class='ads' id='ads-sidebar' maxwidgets='1' showaddelement='yes'/>
        </div>

        <b:if cond='data:view.isPost'>
          <div class='sidebar-box box-brown hidden' id='sidebar-related-target'>
            <h3 class='sidebar-title'>Related Travel Reads</h3>
            <div class='space-y-6' id='related-posts-content'/>
          </div>
        </b:if>
      </aside>
    </div>
  </main>

  <footer class='w-full py-16 bg-white border-t mt-20 text-center'>
    <div class='max-w-7xl mx-auto px-8 space-y-6'>
      <div class='text-lg font-black font-headline tracking-tighter uppercase'>Donggri Korea</div>
      <div class='flex justify-center gap-8 text-[10px] font-bold uppercase tracking-widest text-slate-400'>
        <a href='/p/privacy-policy-disclaime.html'>Privacy</a>
        <a href='/p/terms-of-service.html'>Terms</a>
        <a href='https://donggri-korea.blogspot.com/p/editorial-policy.html'>Affiliate</a>
      </div>
      <p class='text-[10px] text-slate-300'>&#169; 2026 DONGGRI KOREA. ALL RIGHTS RESERVED.</p>
    </div>
  </footer>

  <script id='donggri-travel-theme-script' type='text/javascript'>
  //<![CDATA[
  (function(){
    "use strict";

    var FALLBACK_IMAGE = "https://images.unsplash.com/photo-1517154421773-0529f29ea451?q=80&w=1200";
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
      var path = window.location.pathname.replace(/\/+$/, "") || "/";
      var activeKey = "home";
      if (/\/search\/label\/Travel$/i.test(path)) activeKey = "travel";
      else if (/\/search\/label\/Culture$/i.test(path)) activeKey = "culture";
      else if (/\/search\/label\/Food$/i.test(path)) activeKey = "food";
      else if (/\/p\/about-us\.html$/i.test(path)) activeKey = "about";
      else if (/\/p\/contact\.html$/i.test(path)) activeKey = "contact";

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

    function hydrateHero() {
      var hero = document.getElementById("js-auto-hero");
      if (!hero) return;
      fetchJson("/feeds/posts/default?max-results=1&alt=json")
        .then(function(data) {
          var entries = data && data.feed && data.feed.entry ? data.feed.entry : [];
          if (!entries.length) return;
          var entry = entries[0];
          var title = entry && entry.title ? entry.title.$t : "Donggri Korea";
          var link = entryLink(entry);
          var img = entryImage(entry) || FALLBACK_IMAGE;

          hero.innerHTML = "";
          var anchor = document.createElement("a");
          anchor.href = link;
          anchor.setAttribute("aria-label", title);

          var image = document.createElement("img");
          image.className = "absolute inset-0 w-full h-full object-cover opacity-60 transition-transform duration-700 group-hover:scale-105";
          image.src = img;
          image.alt = title;
          image.decoding = "async";
          image.loading = "eager";
          image.setAttribute("fetchpriority", "high");
          image.setAttribute("data-thumb-state", img ? "r2" : "fallback");
          image.onerror = function() { setImage(image, FALLBACK_IMAGE, "fallback"); };

          var overlay = document.createElement("div");
          overlay.className = "absolute inset-0 bg-gradient-to-t from-black/90 via-transparent to-transparent";

          var content = document.createElement("div");
          content.className = "relative h-full p-10 flex flex-col justify-end";

          var heading = document.createElement("h2");
          heading.className = "text-white text-3xl md:text-5xl font-black font-headline leading-tight mb-4 line-clamp-2";
          heading.textContent = title;

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
      var title = entry && entry.title ? entry.title.$t : "Untitled";
      var link = entryLink(entry);
      var imageUrl = entryImage(entry) || fallback || FALLBACK_IMAGE;

      var item = document.createElement("article");
      item.className = "group rounded-xl border border-slate-100 bg-white overflow-hidden shadow-sm hover:shadow-md transition-shadow";

      var anchor = document.createElement("a");
      anchor.href = link;
      anchor.className = "block";
      anchor.setAttribute("aria-label", title);

      var imageWrap = document.createElement("div");
      imageWrap.className = "aspect-[4/3] bg-slate-100 overflow-hidden";

      var img = document.createElement("img");
      img.className = "w-full h-full object-cover transition-transform duration-500 group-hover:scale-105";
      img.src = imageUrl;
      img.alt = title;
      img.loading = "lazy";
      img.decoding = "async";
      img.setAttribute("data-thumb-state", imageUrl && imageUrl.indexOf("api.dongriarchive.com/assets/travel-blogger/") === 0 ? "r2" : "fallback");
      img.onerror = function() { setImage(img, fallback || FALLBACK_IMAGE, "fallback"); };

      var textWrap = document.createElement("div");
      textWrap.className = "p-3";
      var titleNode = document.createElement("div");
      titleNode.className = "line-clamp-2 text-[11px] font-bold text-slate-800 group-hover:text-accent transition-colors";
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
              renderEmpty(list, "No posts yet");
              return;
            }
            entries.slice(0, 3).forEach(function(entry) {
              list.appendChild(createCategoryItem(entry, fallback));
            });
          })
          .catch(function() {
            renderEmpty(list, "Failed to load");
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

    function titleFromAnchor(anchor) {
      if (!anchor) return "Untitled";
      var titleNode = anchor.querySelector("h3,h2,.title,.entry-title");
      return cleanText((titleNode && titleNode.textContent) || anchor.getAttribute("aria-label") || anchor.getAttribute("title") || anchor.textContent || "Untitled");
    }

    function createSidebarItem(item) {
      return fetchFirstR2Image(item.href).then(function(r2) {
        var row = document.createElement("div");
        row.className = "sidebar-item";
        row.setAttribute("data-thumb-state", r2 ? "r2" : "fallback");

        var textSide = document.createElement("div");
        textSide.className = "text-side";
        var textLink = document.createElement("a");
        textLink.className = "line-clamp-2";
        textLink.href = item.href;
        textLink.textContent = item.title || "Untitled";
        textLink.setAttribute("aria-label", item.title || "Related travel read");
        textSide.appendChild(textLink);

        var imageLink = document.createElement("a");
        imageLink.href = item.href;
        imageLink.setAttribute("aria-label", item.title || "Related travel read");
        var img = document.createElement("img");
        img.loading = "lazy";
        img.decoding = "async";
        img.alt = item.title || "Related travel read";
        setImage(img, r2 || FALLBACK_IMAGE, r2 ? "r2" : "fallback");
        imageLink.appendChild(img);

        row.appendChild(textSide);
        row.appendChild(imageLink);
        return row;
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
        rows.push({ href: href, title: titleFromAnchor(anchor) });
      });
      return rows.slice(0, 3);
    }

    function loadFeedRelatedLinks() {
      return fetchJson("/feeds/posts/default/-/Travel?alt=json&max-results=8")
        .then(function(data) {
          var entries = data && data.feed && data.feed.entry ? data.feed.entry : [];
          var currentUrl = cleanUrl(window.location.href);
          var rows = [];
          entries.forEach(function(entry) {
            var href = cleanUrl(entryLink(entry));
            if (!href || href === currentUrl) return;
            rows.push({ href: href, title: entry && entry.title ? cleanText(entry.title.$t) : "Untitled" });
          });
          return rows.slice(0, 3);
        })
        .catch(function() { return []; });
    }

    function hydrateRelatedReads() {
      var source = document.querySelector(".post-body .related-posts");
      var relTarget = document.getElementById("related-posts-content");
      var relBox = document.getElementById("sidebar-related-target");
      if (!relTarget || !relBox) return;
      var links = collectSourceRelatedLinks(source);
      var promise = links.length ? Promise.resolve(links) : loadFeedRelatedLinks();
      promise.then(function(rows) {
        rows = rows.slice(0, 3);
        relTarget.innerHTML = "";
        if (!rows.length) {
          relBox.classList.add("hidden");
          return;
        }
        Promise.all(rows.map(createSidebarItem)).then(function(nodes) {
          nodes.forEach(function(node) { relTarget.appendChild(node); });
          relBox.classList.remove("hidden");
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
      hydrateRelatedReads();
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
    parser = argparse.ArgumentParser(description="Build the full fixed English Travel Blogger theme XML.")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--report-prefix", default="english-travel-theme-full-fixed")
    return parser.parse_args()


def timestamped_path(report_dir: Path, prefix: str, suffix: str) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return report_dir / f"{prefix}-{stamp}.{suffix}"


def extract_theme_script(xml: str) -> str:
    match = re.search(
        r"<script\s+id='donggri-travel-theme-script'[^>]*>\s*//<!\[CDATA\[(?P<script>[\s\S]*?)//\]\]>\s*</script>",
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
      loadingCount: Array.from(document.querySelectorAll("body *")).filter(el => el.children.length === 0 && /Loading\\.\\.\\./.test(el.textContent || "")).length,
      h1Count: document.querySelectorAll("h1").length,
      activeNav: Array.from(document.querySelectorAll("nav .nav-link.is-active")).map(a => a.textContent.trim()),
      heroImages: Array.from(document.querySelectorAll("#js-auto-hero img")).map(img => img.src),
      categoryImages: Array.from(document.querySelectorAll("#category-latest img")).map(img => img.src),
      postCardImages: Array.from(document.querySelectorAll("#main-section .js-post-card img")).slice(0, 8).map(img => img.src),
      trendingImages: Array.from(document.querySelectorAll("#sidebar-trending-section img")).map(img => img.src),
      relatedImages: Array.from(document.querySelectorAll("#related-posts-content img")).map(img => img.src),
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
        "theme_h1_removed": "text-4xl font-black font-headline tracking-tighter mb-8 text-primary font-headline" not in xml,
        "all_head_content_present": "<b:include data='blog' name='all-head-content'/>" in xml,
        "gtag_present": "G-5T125DHEDY" in xml,
        "tailwind_cdn_removed": "cdn.tailwindcss.com" not in xml,
        "nav_active_static_removed": "text-primary border-b-2 border-primary" not in xml,
        "blogger_proxy_in_script": "blogger_img_proxy" in xml,
        "required_sections": {
            "main-section": "id='main-section'" in xml,
            "sidebar-trending-section": "id='sidebar-trending-section'" in xml,
            "ads-sidebar": "id='ads-sidebar'" in xml,
            "ads-home-mid": "id='ads-home-mid'" in xml,
            "ads-post-bottom": "id='ads-post-bottom'" in xml,
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
