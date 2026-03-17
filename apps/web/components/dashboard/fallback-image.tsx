"use client";

import { useEffect, useMemo, useState } from "react";

import { buildLocalStorageImageUrl } from "@/lib/public-assets";

type FallbackImageProps = {
  src: string;
  alt: string;
  className?: string;
};

export function FallbackImage({ src, alt, className }: FallbackImageProps) {
  const fallbackSrc = useMemo(() => buildLocalStorageImageUrl(src), [src]);
  const [currentSrc, setCurrentSrc] = useState(src);

  useEffect(() => {
    setCurrentSrc(src);
  }, [src]);

  return (
    <img
      src={currentSrc}
      alt={alt}
      className={className}
      onError={() => {
        if (fallbackSrc && currentSrc !== fallbackSrc) {
          setCurrentSrc(fallbackSrc);
        }
      }}
    />
  );
}
