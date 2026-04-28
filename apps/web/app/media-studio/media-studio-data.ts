import { getChannels, getWorkspaceContentItems } from "@/lib/api";
import type { ContentItemRead, ManagedChannelRead } from "@/lib/types";

export type MediaStudioMode = "overview" | "instagram" | "youtube" | "review";

export async function loadMediaStudioData(): Promise<{
  channels: ManagedChannelRead[];
  items: ContentItemRead[];
  error: string | null;
}> {
  try {
    const [channels, instagramItems, youtubeItems] = await Promise.all([
      getChannels(true),
      getWorkspaceContentItems({ provider: "instagram", limit: 200 }),
      getWorkspaceContentItems({ provider: "youtube", limit: 200 }),
    ]);
    return {
      channels: channels.filter((channel) => channel.provider === "instagram" || channel.provider === "youtube"),
      items: [...instagramItems, ...youtubeItems],
      error: null,
    };
  } catch (cause) {
    return {
      channels: [],
      items: [],
      error: cause instanceof Error ? cause.message : "Media Studio 데이터를 불러오지 못했습니다.",
    };
  }
}
