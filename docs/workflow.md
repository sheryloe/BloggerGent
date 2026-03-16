---
title: Workflow Model
---

# Workflow Model

Bloggent uses a guided workflow model where each blog can have its own content pipeline.

## Quick Answer

The workflow is split so operators can control the stages that matter while the system still handles assembly and publishing mechanics behind the scenes.

## At a Glance

User-facing stages:

1. Topic discovery
2. Article generation
3. Image generation

Optional advanced stage:

4. Image prompt refinement

System stages:

- HTML assembly
- publish queue

## Why the workflow is blog-specific

One blog may be travel-focused and another may be mystery-focused.
They should not share the same voice, structure, metadata style, or image guidance.

That is why Bloggent stores workflow and prompt logic per imported blog instead of forcing one global pipeline.

## Operator-visible flow

In the current product, the most important operator loop is:

1. Choose a blog
2. Enter a topic or run topic discovery
3. Generate the article package
4. Review the article in `/articles`
5. Publish manually
6. Verify public metadata

## System-managed flow

Several stages still happen as part of the pipeline even when the operator does not interact with them directly:

- prompt rendering
- content generation
- image generation
- HTML assembly
- publish-state tracking

## Why publishing stays separate

Publishing is intentionally not the same step as generation.
That design protects against:

- accidental publication of weak drafts
- accidental overwrite of already public Blogger posts
- operators losing the chance to review metadata and preview layout

## GEO + SEO in the workflow

The current article prompts are written for both search engines and answer engines.
That means the workflow now expects:

- a direct answer early in the article
- clear section-level sub-questions
- aligned `meta_description` and `excerpt`
- metadata that can be verified on the public page

## Current UI surfaces that map to the workflow

- `/` for the action panel, queue, preview, and summary state
- `/articles` for review, publish, and metadata verification
- `/jobs` for pipeline status
- `/settings` for credentials, imports, and per-blog mappings
- `/google` for reporting connections and visibility

## Example paths

Basic path:

```text
Topic Discovery -> Article Generation -> Image Generation -> HTML Assembly -> Manual Publish -> Meta Verification
```

Advanced path:

```text
Topic Discovery -> Article Generation -> Image Prompt Refinement -> Image Generation -> HTML Assembly -> Manual Publish -> Meta Verification
```
