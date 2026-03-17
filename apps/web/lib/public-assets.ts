const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

function resolvePublicApiBase() {
  return apiBase.replace(/\/api\/v1\/?$/, "");
}

export function buildLocalStorageImageUrl(originalUrl?: string | null) {
  if (!originalUrl) return null;

  try {
    const parsed = new URL(originalUrl);
    const filename = parsed.pathname.split("/").filter(Boolean).pop();
    if (!filename) return null;
    return `${resolvePublicApiBase()}/storage/images/${filename}`;
  } catch {
    const filename = originalUrl.split("/").filter(Boolean).pop();
    if (!filename) return null;
    return `${resolvePublicApiBase()}/storage/images/${filename}`;
  }
}

export function injectImageFallbacks(html: string) {
  return html.replace(/<img\b([^>]*?)\ssrc=(["'])(.*?)\2([^>]*)>/gi, (full, before, quote, src, after) => {
    const fallback = buildLocalStorageImageUrl(src);
    if (!fallback || fallback === src) {
      return full;
    }

    if (/onerror=/i.test(full)) {
      return full;
    }

    const onError = ` onerror="if(!this.dataset.fallbackApplied){this.dataset.fallbackApplied='1';this.src='${fallback}';}"`;
    return `<img${before} src=${quote}${src}${quote}${onError}${after}>`;
  });
}
