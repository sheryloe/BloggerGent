"use client";

import { useState } from "react";

const LOCAL_PRIMARY = "marketing/dashboard-main.png";
const LOCAL_FALLBACK = "marketing/hero-collage.svg";

export function HeroCollageImage() {
  const remoteUrl = process.env.NEXT_PUBLIC_MARKETING_HERO_URL?.trim() ?? "";
  const imageCandidates = [remoteUrl, LOCAL_PRIMARY, LOCAL_FALLBACK].filter((value) => value.length > 0);
  const [index, setIndex] = useState(0);
  const src = imageCandidates[index] ?? LOCAL_FALLBACK;

  return (
    <img
      src={src}
      alt="Bloggent 대시보드 운영 화면"
      className="h-full w-full rounded-[28px] object-cover"
      loading="eager"
      decoding="async"
      onError={() => {
        if (index < imageCandidates.length - 1) {
          setIndex((prev) => prev + 1);
        }
      }}
    />
  );
}
