# Workflow

Bloggent keeps the workflow blog-specific and review-first.

## Quick Answer

Generation and publishing are different steps on purpose.
The system can automate the heavy pipeline work, but the operator still chooses when something becomes public.

## Main stages

User-facing:

1. Topic Discovery
2. Article Generation
3. Image Generation

Optional:

4. Image Prompt Refinement

System-managed:

- HTML Assembly
- Publish Queue
- Meta Verification Support

## Why it is split this way

- different blogs need different prompts
- review should happen before publishing
- metadata verification should happen after publishing
- the operator should not have to wade through low-level pipeline details to approve a post
