from __future__ import annotations

import hashlib
import io
import re
from datetime import datetime, timezone

from PIL import Image, ImageDraw
from slugify import slugify

from app.models.entities import PublishMode
from app.schemas.ai import ArticleGenerationOutput, FAQItem, TopicDiscoveryItem, TopicDiscoveryPayload


def _is_mystery_prompt(prompt: str, keyword: str) -> bool:
    combined = f"{prompt} {keyword}".lower()
    tokens = ["mystery", "unsolved", "paranormal", "legend", "documentary", "crime", "미스터리", "전설"]
    return any(token in combined for token in tokens)


class MockTopicDiscoveryProvider:
    def discover_topics(self, prompt: str) -> tuple[TopicDiscoveryPayload, dict]:
        month = datetime.now(timezone.utc).strftime("%B")
        if _is_mystery_prompt(prompt, ""):
            topics = TopicDiscoveryPayload(
                topics=[
                    TopicDiscoveryItem(
                        keyword="The Mary Celeste unsolved mystery",
                        reason="Classic disappearance stories keep drawing documentary-style search traffic.",
                        trend_score=91.2,
                    ),
                    TopicDiscoveryItem(
                        keyword="Dyatlov Pass true story explained",
                        reason="Cold-case analysis and survival mystery angles perform strongly across global audiences.",
                        trend_score=88.7,
                    ),
                    TopicDiscoveryItem(
                        keyword="The Roanoke Colony lost settlement mystery",
                        reason="Historical legends with competing theories create high dwell-time potential.",
                        trend_score=85.4,
                    ),
                ]
            )
            return topics, topics.model_dump()

        topics = TopicDiscoveryPayload(
            topics=[
                TopicDiscoveryItem(
                    keyword=f"Korean street food guide {month}",
                    reason="Street food performs consistently well with global travel readers.",
                    trend_score=92.4,
                ),
                TopicDiscoveryItem(
                    keyword="Best cherry blossom spots Korea",
                    reason="Seasonal scenery and itineraries attract search demand from visitors.",
                    trend_score=88.1,
                ),
                TopicDiscoveryItem(
                    keyword="Unique K-pop cafes in Seoul",
                    reason="Pop-culture travel topics match high international curiosity.",
                    trend_score=84.7,
                ),
            ]
        )
        return topics, topics.model_dump()


class MockArticleProvider:
    def generate_article(self, keyword: str, prompt: str) -> tuple[ArticleGenerationOutput, dict]:
        if _is_mystery_prompt(prompt, keyword):
            return self._generate_mystery_article(keyword)
        return self._generate_travel_article(keyword)

    def generate_visual_prompt(self, prompt: str) -> tuple[str, dict]:
        keyword_match = re.search(r"\[Topic\]\s*-\s*(.+)", prompt)
        keyword = keyword_match.group(1).strip() if keyword_match else "Korea travel story"
        final_prompt = (
            f"A single high-resolution image divided into an 8-panel grid layout (collage style). "
            f"Each panel shows a different aspect of {keyword}. Panel 1: iconic overview. "
            "Panel 2: seasonal atmosphere. Panel 3: transit arrival moment. Panel 4: local snack close-up. "
            "Panel 5: walking crowd scene. Panel 6: cultural detail. Panel 7: hidden local angle. "
            "Panel 8: memorable closing scene. The collage must clearly show 8 separate rectangular panels with thin white gutters. "
            "Cinematic lighting, ultra-detailed, cohesive Korean travel photography style, realistic Korean atmosphere, "
            "no text overlays, premium editorial composition, vertical aspect ratio preferred."
        )
        return final_prompt, {"mock": True, "source": "mock_visual_prompt"}

    def _generate_travel_article(self, keyword: str) -> tuple[ArticleGenerationOutput, dict]:
        slug = slugify(keyword)
        title = f"{keyword}: A Local Korea Travel Guide for First-Time Visitors"
        meta_description = (
            f"Plan {keyword} with local Korea travel tips, routes, timing, budget ideas, and a foreigner-friendly FAQ."
        )
        html_article = f"""
<h2>Why {keyword} Is Worth Adding to Your Korea Itinerary</h2>
<p>{keyword} works especially well for first-time visitors because it combines atmosphere, easy navigation, and plenty of real local context in one place.</p>
<p>Instead of repeating generic tourist advice, this guide focuses on how people actually move through the area, when it feels best, and what foreigners should prepare in advance.</p>
<h2>Quick Travel Info</h2>
<ul>
  <li><strong>Best for:</strong> first-time Korea visitors, K-culture fans, and travelers building a half-day route</li>
  <li><strong>Typical budget:</strong> KRW 20,000 to 60,000 depending on food, cafes, and transport</li>
  <li><strong>Ideal timing:</strong> weekday mornings or golden hour before dinner</li>
</ul>
<h2>How Locals Usually Enjoy It</h2>
<p>Locals tend to pair one main stop with a nearby cafe, a convenience store break, and one evening-friendly food stop rather than trying to overpack the route.</p>
<p>That rhythm matters because the best memories usually come from how the neighborhood feels between headline attractions.</p>
<h3>Practical local flow</h3>
<ul>
  <li>Arrive earlier than peak photo hours if you want calmer streets and shorter waits.</li>
  <li>Use subway exits tied to landmarks so navigation stays simple on mobile.</li>
  <li>Keep one backup indoor stop in case weather or crowds change the pace.</li>
</ul>
<h2>Budget, Timing, and Small Details That Matter</h2>
<p>Travelers usually underestimate walking time, rest breaks, and snack spending, so it helps to build a route with flexible margins.</p>
<p>For foreigners, the easiest version of the experience is the one that stays practical from transit to payment to meal timing.</p>
<!--RELATED_POSTS-->
<h2>Final Planning Notes</h2>
<p>If you treat {keyword} as one part of a neighborhood journey instead of a single checklist stop, the experience feels much more local and memorable.</p>
<p>That is exactly the kind of structure that keeps readers engaged and makes the article genuinely useful during a Korea trip.</p>
""".strip()
        output = ArticleGenerationOutput(
            title=title,
            meta_description=meta_description,
            labels=["Korea Travel", "Seoul", "Local Guide", "Foreign Visitors"],
            slug=slug,
            excerpt=(
                f"A practical Korea travel guide to {keyword} with local tips, budget expectations, and first-timer advice."
            ),
            html_article=html_article,
            faq_section=[
                FAQItem(
                    question=f"Is {keyword} good for first-time visitors to Korea?",
                    answer="Yes. It becomes much easier if you keep your route near subway lines and save a few nearby landmarks in advance.",
                ),
                FAQItem(
                    question=f"How much budget should I prepare for {keyword}?",
                    answer="Most travelers can plan a light half-day budget and then add extra room for cafes, snacks, and taxis if needed.",
                ),
                FAQItem(
                    question=f"What is the best time of day to enjoy {keyword}?",
                    answer="Weekday mornings and late afternoon usually feel smoother because crowds are lighter and photos look better.",
                ),
            ],
            image_collage_prompt=(
                f"A realistic editorial Korea travel cover image about {keyword}, showing streets, food, transit details, and local atmosphere."
            ),
        )
        return output, output.model_dump()

    def _generate_mystery_article(self, keyword: str) -> tuple[ArticleGenerationOutput, dict]:
        slug = slugify(keyword)
        title = f"{keyword}: The Unsolved Mystery That Still Defies Explanation"
        meta_description = (
            f"Explore {keyword} through key evidence, leading theories, timelines, and the unanswered questions behind the story."
        )
        html_article = f"""
<h2>Quick Overview</h2>
<ul>
  <li><strong>Case focus:</strong> historical mystery and documentary-style analysis</li>
  <li><strong>Status:</strong> unresolved with competing theories</li>
  <li><strong>Why people still search it:</strong> contradictory evidence and enduring cultural fascination</li>
</ul>
<h2>The Inciting Incident</h2>
<p>{keyword} remains compelling because the first known facts already feel wrong: ordinary details give way to a chain of events that still refuses to settle into one clean explanation.</p>
<p>This is why the story survives across documentaries, search traffic, and late-night theory forums. The basics are easy to understand, but the deeper you go, the stranger the evidence becomes.</p>
<h2>The Eerie Details and Unanswered Evidence</h2>
<p>The most persistent mystery usually comes from small inconsistencies rather than one dramatic clue. Dates, testimony, missing objects, or environmental details keep undermining the simplest theory.</p>
<h3>Key points investigators revisit</h3>
<ul>
  <li>What witnesses said at the time versus what was recorded later</li>
  <li>Which physical clues were real, missing, or never fully verified</li>
  <li>Why popular explanations still leave obvious gaps</li>
</ul>
<h2>Prominent Theories and Modern Reassessment</h2>
<p>Most serious discussions split into practical explanations, speculative theories, and newer reinterpretations shaped by better science or historical review.</p>
<p>The real intrigue is not that one theory looks perfect. It is that each theory explains something important while failing somewhere else.</p>
<!--RELATED_POSTS-->
<h2>Why the Story Endures</h2>
<p>{keyword} continues to perform well with readers because it sits between documented fact and narrative uncertainty. That makes it ideal for thoughtful storytelling and repeated reanalysis.</p>
<p>Even now, the case feels unfinished, which is exactly why audiences keep returning to it.</p>
""".strip()
        output = ArticleGenerationOutput(
            title=title,
            meta_description=meta_description,
            labels=["World Mystery", "True Story", "Documentary", "Unsolved"],
            slug=slug,
            excerpt=(
                f"A documentary-style breakdown of {keyword}, covering the timeline, strongest theories, and the evidence that keeps the mystery alive."
            ),
            html_article=html_article,
            faq_section=[
                FAQItem(
                    question=f"What makes {keyword} so difficult to explain?",
                    answer="The challenge is that the most widely repeated theory never accounts for every documented clue at the same time.",
                ),
                FAQItem(
                    question=f"Is there a modern explanation for {keyword}?",
                    answer="Modern reviews often improve parts of the case, but no single explanation has fully closed the biggest gaps in the record.",
                ),
                FAQItem(
                    question=f"Why does {keyword} still attract readers today?",
                    answer="It combines real historical detail with unanswered evidence, which keeps the story relevant to both documentary fans and casual mystery readers.",
                ),
            ],
            image_collage_prompt=(
                f"A realistic cinematic documentary cover image for {keyword}, eerie atmosphere, believable location details, natural shadows, no text."
            ),
        )
        return output, output.model_dump()


class MockImageProvider:
    def generate_image(self, prompt: str, slug: str) -> tuple[bytes, dict]:
        width, height = 1536, 1024
        image = Image.new("RGB", (width, height), "#f6efe7")
        draw = ImageDraw.Draw(image)
        panel_width = width // 5
        panel_height = height // 2
        seed = int(hashlib.md5(prompt.encode("utf-8")).hexdigest(), 16)
        palette = ["#0f4c5c", "#e36414", "#fb8b24", "#9a031e", "#5f0f40", "#335c67", "#4d9078", "#ffba08"]

        for row in range(2):
            for col in range(5):
                idx = row * 5 + col
                x0 = col * panel_width
                y0 = row * panel_height
                x1 = x0 + panel_width
                y1 = y0 + panel_height
                color = palette[(seed + idx) % len(palette)]
                draw.rounded_rectangle((x0 + 14, y0 + 14, x1 - 14, y1 - 14), radius=28, fill=color)
                draw.ellipse((x0 + 36, y0 + 32, x0 + 180, y0 + 176), fill="#fef3c7")
                draw.rectangle((x0 + 60, y0 + 188, x1 - 60, y1 - 60), fill="#ffffff20", outline="#ffffff40", width=3)

        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue(), {"mock": True, "prompt_hash": str(seed), "width": width, "height": height}


class MockBloggerProvider:
    def publish(
        self,
        *,
        title: str,
        content: str,
        labels: list[str],
        meta_description: str,
        slug: str,
        publish_mode: PublishMode,
    ) -> tuple[dict, dict]:
        mode = "draft" if publish_mode == PublishMode.DRAFT else "published"
        fake_id = slugify(f"{slug}-{mode}")
        summary = {
            "id": fake_id,
            "url": f"https://mock-blogger.local/{slug}",
            "published": datetime.now(timezone.utc).isoformat(),
            "isDraft": publish_mode == PublishMode.DRAFT,
            "labels": labels,
            "meta_description": meta_description,
            "content_length": len(content),
            "title": title,
        }
        return summary, summary

    def update_post(
        self,
        *,
        post_id: str,
        title: str,
        content: str,
        labels: list[str],
        meta_description: str,
    ) -> tuple[dict, dict]:
        summary = {
            "id": post_id,
            "url": f"https://mock-blogger.local/{post_id}",
            "published": datetime.now(timezone.utc).isoformat(),
            "isDraft": False,
            "labels": labels,
            "meta_description": meta_description,
            "content_length": len(content),
            "title": title,
        }
        return summary, summary

    def publish_draft(self, post_id: str) -> tuple[dict, dict]:
        summary = {
            "id": post_id,
            "url": f"https://mock-blogger.local/{post_id}",
            "published": datetime.now(timezone.utc).isoformat(),
            "isDraft": False,
        }
        return summary, summary

    def delete_post(self, post_id: str) -> None:
        return None
