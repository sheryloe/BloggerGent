export type ModelGroup = {
  id: string;
  title: string;
  description: string;
  models: string[];
};

export const OPENAI_DATA_SHARING_FREE_TIERS: ModelGroup[] = [
  {
    id: "shared-1m",
    title: "Free tier 1M token group",
    description:
      "Input + output combined. Usage tiers 1-2: 250K tokens. Deprecated: gpt-4.5-preview-2025-02-27 (shut down 2025-07-14).",
    models: [
      "gpt-5.4-2026-03-05",
      "gpt-5-codex",
      "gpt-5-2025-08-07",
      "gpt-5-chat-latest",
      "gpt-4.5-preview-2025-02-27",
      "gpt-4.1-2025-04-14",
      "gpt-4o-2024-05-13",
      "gpt-4o-2024-08-06",
      "gpt-4o-2024-11-20",
      "o3-2025-04-16",
      "o1-preview-2024-09-12",
      "o1-2024-12-17",
    ],
  },
  {
    id: "shared-10m",
    title: "Free tier 10M token group",
    description: "Input + output combined. Usage tiers 1-2: 2.5M tokens.",
    models: [
      "gpt-5.4-mini-2026-03-17",
      "gpt-5-mini-2025-08-07",
      "gpt-5-nano-2025-08-07",
      "gpt-4.1-mini-2025-04-14",
      "gpt-4.1-nano-2025-04-14",
      "gpt-4o-mini-2024-07-18",
      "o4-mini-2025-04-16",
      "o1-mini-2024-09-12",
      "codex-mini-latest",
    ],
  },
];

const CHAT_COMPLETIONS_UNSUPPORTED_MODELS = new Set([
  "gpt-5-codex",
  "codex-mini-latest",
]);

export const OPENAI_TEXT_MODEL_SUGGESTIONS = Array.from(
  new Set(
    OPENAI_DATA_SHARING_FREE_TIERS.flatMap((group) => group.models).filter(
      (model) => !CHAT_COMPLETIONS_UNSUPPORTED_MODELS.has(model),
    ),
  ),
);

export const OPENAI_IMAGE_MODEL_SUGGESTIONS = [
  "gpt-image-1",
];

export const GEMINI_MODEL_SUGGESTIONS = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"];

export const OPENAI_DATA_SHARING_NOTICE =
  "Free tier usage is calculated from the combined input/output token count. These lists reflect the shared usage tiers.";

export const OPENAI_DATA_SHARING_COMPATIBILITY_NOTE =
  "Chat Completions does not accept codex-family models. They are listed for reference only.";
