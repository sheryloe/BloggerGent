import { MediaStudioWorkspace } from "@/components/media-studio/media-studio-workspace";

import { loadMediaStudioData } from "../media-studio-data";

export const dynamic = "force-dynamic";

export default async function MediaStudioYoutubePage() {
  const payload = await loadMediaStudioData();
  return <MediaStudioWorkspace initialMode="youtube" channels={payload.channels} initialItems={payload.items} initialError={payload.error} />;
}
