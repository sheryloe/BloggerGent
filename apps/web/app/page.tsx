import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

export default function HomePage() {
  if (process.env.NEXT_PUBLIC_MEDIA_STUDIO_STANDALONE === "true") {
    redirect("/media-studio");
  }
  redirect("/dashboard");
}
