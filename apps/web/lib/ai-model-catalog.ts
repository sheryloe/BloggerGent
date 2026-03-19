export type ModelGroup = {
  id: string;
  title: string;
  description: string;
  models: string[];
};

export const OPENAI_DATA_SHARING_FREE_TIERS: ModelGroup[] = [
  {
    id: "shared-1m",
    title: "무료 1M 토큰/일 그룹",
    description: "데이터 공유 활성화 계정 기준. 입력/출력 토큰 합산으로 계산됩니다.",
    models: [
      "gpt-5.4",
      "gpt-5.2",
      "gpt-5.1",
      "gpt-5.1-codex",
      "gpt-5",
      "gpt-5-codex",
      "gpt-5-chat-latest",
      "gpt-4.1",
      "gpt-4o",
      "o1",
      "o3",
    ],
  },
  {
    id: "shared-10m",
    title: "무료 10M 토큰/일 그룹",
    description: "데이터 공유 활성화 계정 기준. 소형 모델 위주라 대량 생성 워크로드에 유리합니다.",
    models: [
      "gpt-5.4-mini",
      "gpt-5.4-nano",
      "gpt-5.1-codex-mini",
      "gpt-5-mini",
      "gpt-5-nano",
      "gpt-4.1-mini",
      "gpt-4.1-nano",
      "gpt-4o-mini",
      "o1-mini",
      "o3-mini",
      "o4-mini",
      "codex-mini-latest",
    ],
  },
];

const CHAT_COMPLETIONS_UNSUPPORTED_MODELS = new Set([
  "gpt-5-codex",
  "gpt-5.1-codex",
  "gpt-5.1-codex-mini",
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
  "gpt-image-1.5",
  "gpt-image-1-mini",
  "gpt-image-1",
  "dall-e-3",
];

export const GEMINI_MODEL_SUGGESTIONS = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"];

export const OPENAI_DATA_SHARING_NOTICE =
  "공식 도움말 기준으로 평가 공유는 주 7회까지 무료이며, 무료 토큰은 데이터 공유가 켜진 프로젝트 트래픽에만 적용됩니다.";

export const OPENAI_DATA_SHARING_COMPATIBILITY_NOTE =
  "현재 앱의 본문 생성기는 Chat Completions 기반이라 codex 계열은 무료 대상 안내에만 표시하고 추천 입력값에서는 제외했습니다.";
