---
title: Workflow Model
---

# Workflow Model

Bloggent uses a guided workflow model.
The important idea is that the workflow is blog-specific, not global.

## User-visible stages

These are the stages that matter most to operators:

1. Topic discovery
2. Writing package
3. Image generation

Optional advanced stage:

4. Image prompt refinement

## System stages

These are executed as part of the pipeline but are treated as service steps:

- HTML assembly
- publish queue

## Why the model is split this way

Different users want different levels of control.
Some only want a two-step flow.
Others want full stage-by-stage prompt editing.

Bloggent supports both by separating:

- user-editable stages
- system execution stages

## Manual publish by design

Publishing is intentionally not the same thing as generation.
The pipeline generates the article first, then leaves the final release action in the article list.

That design reduces the two biggest Blogger risks:

- accidental publication of weak drafts
- accidental overwrite of already-public posts

## Example path

```text
Topic Discovery -> Writing Package -> Image Generation -> HTML Assembly -> Publish Queue
```

Advanced path:

```text
Topic Discovery -> Writing Package -> Image Prompt Refinement -> Image Generation -> HTML Assembly -> Publish Queue
```
