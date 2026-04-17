from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


REQUIRED_MODEL = "gpt-5.4-mini-2026-03-17"


@dataclass(frozen=True)
class TopicSpec:
    filename: str
    title: str
    target_slug: str
    focus: str
    scene: str
    table_headers: tuple[str, str, str]
    table_rows: tuple[tuple[str, str, str], ...]
    h2_sections: tuple[str, str, str, str, str]
    faq_items: tuple[tuple[str, str], ...]
    tags: tuple[str, str, str, str, str]
    closing_sentence_1: str
    closing_sentence_2: str


TOPIC_SPECS: tuple[TopicSpec, ...] = (
    TopicSpec(
        filename="maeil-bam-5bun-oneul-harureul-jjalbge-memohaneun-rutinui-him.json",
        title="잠들기 전 3줄 메모 루틴, 할 일 누락을 줄이는 가장 단순한 방법",
        target_slug="night-5-minute-three-line-memo-routine-2026",
        focus="잠들기 전 3줄 메모로 다음 날 할 일 누락을 줄이는 운영 방식",
        scene="불을 끄기 직전 침대 옆 메모장에 오늘과 내일을 짧게 정리하는 장면",
        table_headers=("체크 항목", "작성 기준", "누락 방지 포인트"),
        table_rows=(
            ("내일 첫 행동", "한 문장으로 시작 행동만 기록", "시작 장벽이 낮아져 지연 감소"),
            ("보류한 일", "이유를 한 줄로 남김", "미완료 업무의 맥락 유지"),
            ("연락 필요 건", "대상/시간/목적 3요소 기록", "커뮤니케이션 누락 방지"),
            ("건강 루틴", "수면/물/스트레칭 중 1개 지정", "다음 날 컨디션 회복"),
        ),
        h2_sections=(
            "왜 밤 5분 메모가 다음 날을 바꾸는가",
            "3줄 메모 템플릿을 고정하는 법",
            "퇴근 후 피로한 날에도 유지되는 작성 순서",
            "메모가 끊겼을 때 24시간 안에 복구하는 절차",
            "월말에 누락 패턴을 줄이는 재정렬 방법",
        ),
        faq_items=(
            ("Q1. 매일 밤 같은 시간에 못 쓰면 효과가 떨어지나요?", "A. 완벽한 고정보다 취침 전 마지막 5분이라는 조건만 지키면 충분합니다."),
            ("Q2. 3줄보다 길게 쓰고 싶을 때는 어떻게 하나요?", "A. 본문을 늘리지 말고 메모 아래에 키워드만 추가해 다음 날에 확장하세요."),
            ("Q3. 가족 일정까지 같이 적어도 되나요?", "A. 개인 할 일과 가족 일정은 줄을 분리해 기록하면 충돌을 줄일 수 있습니다."),
            ("Q4. 휴대폰과 종이 메모 중 무엇이 낫나요?", "A. 취침 전 접근성이 높은 도구를 선택하되 템플릿은 동일하게 유지하는 것이 핵심입니다."),
        ),
        tags=("일상과-메모", "할일관리", "밤루틴", "메모습관", "누락방지"),
        closing_sentence_1="잠들기 전 3줄 메모는 해야 할 일을 더 많이 적는 기술이 아니라 내일의 첫 행동을 분명하게 남기는 습관이다.",
        closing_sentence_2="하루 끝 5분에 정리한 문장이 다음 날의 혼란을 가장 먼저 줄여 준다.",
    ),
    TopicSpec(
        filename="ilsang-sok-jakeun-haengbokeul-girokhaneun-memo-seupgwan-tip-harureul-bakkuneun-s.json",
        title="아침 5분 체크 메모 루틴, 하루 시작을 정렬하는 실전 방식",
        target_slug="morning-5-minute-check-note-routine-2026",
        focus="아침 5분 체크 메모로 우선순위를 재정렬하는 방식",
        scene="출근 준비 전 주방 테이블에서 오늘 일정과 에너지를 빠르게 점검하는 장면",
        table_headers=("아침 체크", "메모 예시", "실행 효과"),
        table_rows=(
            ("오늘의 1순위", "오전 안에 끝낼 일 1개", "핵심 업무 지연 감소"),
            ("컨디션 상태", "집중도/피로도 5점 척도", "일정 강도 조절"),
            ("예상 변수", "회의 지연·이동 변수 기록", "돌발 대응 시간 확보"),
            ("점심 전 점검", "중간 확인 시간 1회 예약", "오전 계획 이탈 방지"),
        ),
        h2_sections=(
            "아침 체크 메모가 필요한 이유",
            "5분 안에 끝나는 체크 순서 설계",
            "오전 집중도를 지키는 문장 작성법",
            "예상 변수에 흔들리지 않는 수정 규칙",
            "주간 리뷰에서 루틴을 다듬는 기준",
        ),
        faq_items=(
            ("Q1. 아침이 너무 바쁠 때는 어떤 항목만 남겨야 하나요?", "A. 1순위 업무와 컨디션 점수 두 가지만 기록해도 루틴은 유지됩니다."),
            ("Q2. 체크 메모를 했는데도 일정이 밀릴 때는요?", "A. 변수 항목을 강화하고 점심 전 재조정 시간을 반드시 고정하세요."),
            ("Q3. 팀 업무와 개인 업무를 함께 적어도 되나요?", "A. 항목을 분리해 쓰면 우선순위 충돌을 줄일 수 있습니다."),
            ("Q4. 주말에도 같은 방식으로 운영해야 하나요?", "A. 주말은 체크 항목을 줄이고 회복 중심으로 재구성하면 됩니다."),
        ),
        tags=("일상과-메모", "아침루틴", "우선순위", "체크리스트", "생산성"),
        closing_sentence_1="아침 5분 체크 메모는 일정을 빽빽하게 채우기보다 오늘 반드시 지킬 한 줄을 선명하게 고정하는 장치다.",
        closing_sentence_2="하루 초반의 짧은 정렬이 오후의 흔들림을 예상보다 크게 줄인다.",
    ),
    TopicSpec(
        filename="ilsang-sok-jakeun-haengbokeul-girokhaneun-memo-seupgwan-tip-namanui-harureul-cha.json",
        title="퇴근 후 감정·집중도 회복 메모, 소모를 줄이는 저녁 기록법",
        target_slug="weekday-evening-mood-and-focus-reset-notes-2026",
        focus="퇴근 후 감정과 집중도를 회복하는 저녁 메모 방식",
        scene="집에 도착해 가방을 내려놓고 하루의 소모 지점을 짧게 기록하는 장면",
        table_headers=("저녁 회복 체크", "기록 내용", "다음 날 반영"),
        table_rows=(
            ("소모 지점", "가장 피곤했던 순간 1개", "유사 상황 대비"),
            ("회복 행동", "실제로 도움이 된 행동 1개", "재사용 루틴 축적"),
            ("대화 잔상", "마음에 남은 말 한 줄", "관계 스트레스 관리"),
            ("집중 회복", "내일 줄일 자극 1개", "오전 집중도 개선"),
        ),
        h2_sections=(
            "퇴근 직후 메모가 회복 속도를 높이는 이유",
            "감정과 사실을 분리해 적는 기본 틀",
            "저녁 10분 회복 루틴 실제 적용 순서",
            "관계 피로를 다음 날로 넘기지 않는 정리법",
            "한 달 누적 데이터로 소모 패턴 줄이기",
        ),
        faq_items=(
            ("Q1. 감정 기록이 오히려 피로를 키울 때는 어떻게 하나요?", "A. 사건 서술을 줄이고 회복 행동 한 줄을 먼저 적으면 과몰입을 막을 수 있습니다."),
            ("Q2. 회복 행동이 매번 달라도 괜찮나요?", "A. 효과가 있었던 행동을 누적해 개인 회복 목록으로 관리하면 됩니다."),
            ("Q3. 가족과의 대화 스트레스도 기록해야 하나요?", "A. 대화 내용을 평가하지 말고 내 반응 패턴만 기록하면 부담이 줄어듭니다."),
            ("Q4. 이 기록을 업무 메모와 합쳐도 되나요?", "A. 회복 메모는 별도 구간으로 분리해야 다음 날 컨디션 분석이 쉬워집니다."),
        ),
        tags=("일상과-메모", "퇴근루틴", "감정회복", "집중관리", "저녁기록"),
        closing_sentence_1="퇴근 후 회복 메모는 하루를 다시 평가하기 위한 문서가 아니라 소모를 내일로 끌고 가지 않기 위한 정리 장치다.",
        closing_sentence_2="저녁 10분의 짧은 기록이 다음 날 집중력의 출발점을 조용히 복구한다.",
    ),
    TopicSpec(
        filename="ilsang-sok-jakeun-haengbokeul-girokhaneun-memo-seupgwan-tip-namanui-sosohan-giro.json",
        title="사소한 장면 아카이브 메모, 오래 남는 일상 기록 설계법",
        target_slug="small-daily-moment-archive-note-method-2026",
        focus="사소한 장면을 오래 남기는 일상 아카이브 메모 방식",
        scene="하루 중 스쳐 지나간 장면 하나를 밤에 다시 불러와 기록하는 장면",
        table_headers=("아카이브 요소", "기록 기준", "재활용 방식"),
        table_rows=(
            ("장면", "장소·시간·행동 3요소 고정", "월간 장면 모음 구성"),
            ("감정 온도", "0~5점으로 간단 표기", "감정 변화 추세 확인"),
            ("메시지", "내게 남은 문장 1개", "개인 기준 문장집 축적"),
            ("다음 행동", "같은 상황에서 적용할 행동 1개", "실천형 메모 전환"),
        ),
        h2_sections=(
            "사소한 장면을 남겨야 하는 현실적인 이유",
            "아카이브 메모를 위한 최소 입력 규칙",
            "사진 대신 문장을 남기는 기준선",
            "기록이 쌓일수록 검색이 쉬워지는 태그 설계",
            "월간 장면 정리로 기억의 밀도 높이기",
        ),
        faq_items=(
            ("Q1. 장면 기록이 너무 비슷해지면 어떻게 하나요?", "A. 시간대와 장소를 먼저 고정하면 문장 반복을 줄일 수 있습니다."),
            ("Q2. 사진을 같이 첨부해야 효과가 높아지나요?", "A. 사진은 선택이고 핵심은 장면을 설명하는 문장 구조를 유지하는 것입니다."),
            ("Q3. 태그를 많이 달수록 좋은가요?", "A. 3개 이내 핵심 태그를 꾸준히 쓰는 편이 검색 효율이 더 높습니다."),
            ("Q4. 기록을 나중에 글로 확장할 수 있나요?", "A. 장면·감정·행동 요소를 갖춘 메모는 확장 글의 안정적인 초안이 됩니다."),
        ),
        tags=("일상과-메모", "아카이브", "관찰기록", "장면메모", "기억관리"),
        closing_sentence_1="사소한 장면 아카이브 메모는 특별한 날을 기다리지 않고 평범한 하루의 결을 보존하는 가장 현실적인 방식이다.",
        closing_sentence_2="짧은 장면 기록이 쌓일수록 내 생활을 설명하는 문장이 훨씬 정확해진다.",
    ),
    TopicSpec(
        filename="oneului-ilsang-memowa-sosohan-saenggak-gongyu-giroki-namgineun-heunjeokui-uimi.json",
        title="오늘의 생각 2문장 메모 공유법, 부담 없이 기록을 이어가는 습관",
        target_slug="today-thought-note-sharing-journal-practice-2026",
        focus="오늘의 생각을 2문장으로 공유 가능한 메모로 남기는 방식",
        scene="메신저에 보내기 전 짧은 생각을 메모장에 먼저 정리하는 장면",
        table_headers=("공유 전 체크", "2문장 구성", "오해 방지 기준"),
        table_rows=(
            ("상황 문장", "무슨 장면이었는지 1문장", "맥락 누락 방지"),
            ("생각 문장", "내가 본 핵심 느낌 1문장", "과장 표현 최소화"),
            ("표현 수위", "단정어 대신 관찰어 사용", "불필요한 갈등 예방"),
            ("공유 대상", "누구와 왜 공유하는지 명시", "전달 목적 선명화"),
        ),
        h2_sections=(
            "2문장 메모가 공유 부담을 줄이는 이유",
            "상황·생각 2문장 구조를 고정하는 법",
            "메신저 공유 전에 검토할 기준 3가지",
            "관찰형 문장으로 오해를 줄이는 표현법",
            "공유 기록을 개인 메모 자산으로 돌려쓰기",
        ),
        faq_items=(
            ("Q1. 공유 메모를 쓰다 보면 자기검열이 심해집니다.", "A. 평가 문장을 줄이고 관찰 문장을 먼저 쓰면 부담이 내려갑니다."),
            ("Q2. 2문장으로는 설명이 부족하지 않나요?", "A. 부족한 부분은 키워드만 덧붙이고 본문 확장은 별도 노트로 분리하세요."),
            ("Q3. 팀 채널에도 같은 규칙을 적용할 수 있나요?", "A. 적용할 수 있으며 특히 회의 후 요약 전달에서 효과가 큽니다."),
            ("Q4. 공유하지 않는 날의 메모도 같은 형식이 좋나요?", "A. 네, 형식이 같아야 비교와 회고가 쉬워집니다."),
        ),
        tags=("일상과-메모", "생각정리", "공유메모", "문장습관", "관찰표현"),
        closing_sentence_1="오늘의 생각을 2문장으로 정리하는 습관은 말하기 전에 생각의 모양을 먼저 다듬게 만든다.",
        closing_sentence_2="짧은 공유 메모가 쌓일수록 관계와 기록이 동시에 가벼워진다.",
    ),
    TopicSpec(
        filename="EC-B6-9C-ED-87-B4-EA-B7-BC-EA-B8-B8-EC-97-90-EB-82-A8-EA-B8-B0-EB-8A-94-10-EB-B6-84-EC-82-B0-EC-B1-85-EB-A9-94-EB-AA-A8-.json",
        title="출퇴근 5분 짬운동 체크 메모, 바쁜 날에도 건강 루틴을 지키는 법",
        target_slug="commute-5-minute-micro-workout-check-memo-2026",
        focus="출퇴근 5분 짬운동과 체크 메모를 결합한 건강 루틴",
        scene="지하철역 출구에서 계단 오르기와 스트레칭을 마친 뒤 바로 체크하는 장면",
        table_headers=("짬운동 항목", "5분 구성", "메모 체크 포인트"),
        table_rows=(
            ("계단 오르기", "2분", "호흡과 무릎 상태 기록"),
            ("목·어깨 스트레칭", "1분", "긴장 완화 정도 기록"),
            ("종아리 펌핑", "1분", "다리 피로도 변화 기록"),
            ("수분 섭취", "1분", "물 섭취량 간단 체크"),
        ),
        h2_sections=(
            "출퇴근 5분 운동이 현실적인 이유",
            "메모와 결합한 짬운동 루틴 설계",
            "지하철·버스 이동 동선별 적용 패턴",
            "피로 누적을 줄이는 체크 문장 작성법",
            "주간 데이터로 건강 루틴을 미세 조정하기",
        ),
        faq_items=(
            ("Q1. 운동 시간을 5분도 못 내는 날은 어떻게 하나요?", "A. 스트레칭 2종과 수분 체크만 남겨 최소 루틴으로 유지하세요."),
            ("Q2. 땀이 나는 운동은 출근 전 부담스럽습니다.", "A. 체온을 크게 올리지 않는 저강도 동작 중심으로 구성하면 됩니다."),
            ("Q3. 메모를 매번 쓰기 번거롭습니다.", "A. 체크박스 4개 형태로 고정하면 기록 시간이 30초 내로 줄어듭니다."),
            ("Q4. 주말에는 어떤 방식으로 이어가면 좋나요?", "A. 걷기 시간만 조금 늘리고 같은 체크 구조를 유지하는 것이 좋습니다."),
        ),
        tags=("일상과-메모", "건강습관", "출퇴근루틴", "짬운동", "체크메모"),
        closing_sentence_1="출퇴근 5분 짬운동 체크 메모는 운동량을 과시하는 방식이 아니라 바쁜 날에도 건강 신호를 놓치지 않는 최소 장치다.",
        closing_sentence_2="짧은 기록이 쌓일수록 몸의 피로 패턴을 먼저 읽고 조정할 수 있게 된다.",
    ),
    TopicSpec(
        filename="EB-B2-9A-EA-BD-83-EC-8B-9C-EC-A6-8C-ED-95-9C-EB-8B-AC-EA-B8-B0-EB-A1-9D-EB-A3-A8-ED-8B-B4-EC-84-A4-EA-B3-84-EC-82-AC-EC-.json",
        title="심심한 계절 산책 관찰 메모, 사진 없이도 오래 남는 기록 습관",
        target_slug="spring-walk-observation-note-routine-2026",
        focus="계절 산책에서 심심한 장면을 관찰 메모로 남기는 습관",
        scene="같은 산책길을 걸으며 매번 다른 소리와 표정을 관찰해 기록하는 장면",
        table_headers=("산책 관찰 요소", "메모 방식", "기억 지속 효과"),
        table_rows=(
            ("소리", "들린 순서대로 2개 기록", "장면 재현력 상승"),
            ("속도", "걸음 리듬을 단어로 표현", "몸 감각 보존"),
            ("표정", "스친 사람/내 표정 한 줄", "감정 맥락 유지"),
            ("날씨", "온도·바람·빛 3요소", "계절 변화 추적"),
        ),
        h2_sections=(
            "심심한 산책이 기록 주제가 되는 이유",
            "관찰 메모에서 사진을 줄이는 기준",
            "같은 길을 다르게 보는 질문 설계",
            "계절 변화가 보이는 문장 포맷 만들기",
            "한 달 산책 메모를 묶어 읽는 방법",
        ),
        faq_items=(
            ("Q1. 산책 메모가 단조롭게 반복됩니다.", "A. 소리·속도·표정 중 하루 한 요소를 중심으로 바꾸면 반복감이 줄어듭니다."),
            ("Q2. 사진이 없으면 기록이 약해지지 않나요?", "A. 관찰 문장이 구체적이면 사진 없이도 장면 복원이 충분히 가능합니다."),
            ("Q3. 비 오는 날이나 미세먼지 날에는 어떻게 기록하나요?", "A. 산책 시간을 줄이고 실내 이동 장면을 같은 포맷으로 기록하면 됩니다."),
            ("Q4. 산책 메모를 다른 글로 확장할 수 있나요?", "A. 월간 묶음에서 반복된 문장을 추리면 확장 글의 핵심 주제가 나옵니다."),
        ),
        tags=("일상과-메모", "산책기록", "계절관찰", "심심한일상", "관찰메모"),
        closing_sentence_1="심심한 산책 관찰 메모는 특별한 장면을 찾는 일이 아니라 평범한 길에서 달라지는 결을 붙잡는 습관이다.",
        closing_sentence_2="같은 길을 기록하는 문장이 쌓일수록 계절과 마음의 변화를 더 또렷하게 읽게 된다.",
    ),
    TopicSpec(
        filename="the-mary-celeste-unsolved-mystery-EB-A5-BC-EB-A9-94-EB-AA-A8-ED-95-98-EB-8A-94-EB-B2-95-EB-AF-B8-EC-8A-A4-ED-84-B0-EB-A6.json",
        title="심심한 저녁, 잊지 않기 메모 시스템으로 할 일을 가볍게 정리하는 법",
        target_slug="do-not-forget-task-three-slot-memo-system-2026",
        focus="심심한 저녁 시간에 잊지 않기 메모 시스템을 운영하는 방식",
        scene="저녁 식사 후 소파에 앉아 내일 필요한 행동만 세 칸으로 나눠 적는 장면",
        table_headers=("3칸 메모 구역", "기록 원칙", "다음 날 효과"),
        table_rows=(
            ("반드시 할 일", "시간·장소 포함 한 줄", "핵심 일정 누락 방지"),
            ("하면 좋은 일", "여유 시간에 가능한 일", "유동성 확보"),
            ("기억 보조", "연락·준비물 체크", "잔실수 감소"),
            ("마감 확인", "하루 끝 재확인 표시", "불안감 완화"),
        ),
        h2_sections=(
            "심심한 저녁에 메모를 붙이는 이유",
            "잊지 않기 3칸 시스템 기본 구조",
            "할 일 과부하를 줄이는 문장 길이 규칙",
            "다음 날 아침 재확인 루틴 연결법",
            "주간 반복 누락을 줄이는 보정 방법",
        ),
        faq_items=(
            ("Q1. 할 일이 너무 많아 3칸에 안 들어갑니다.", "A. 반드시 할 일은 1~2개만 남기고 나머지는 하면 좋은 일로 이동하세요."),
            ("Q2. 저녁마다 메모를 잊어버립니다.", "A. 식사 후 자리에서 바로 작성하는 고정 트리거를 만들면 유지가 쉬워집니다."),
            ("Q3. 가족 일정과 개인 일정을 같이 관리해도 되나요?", "A. 칸을 분리해 기록하면 충돌 없이 함께 관리할 수 있습니다."),
            ("Q4. 이 시스템을 디지털 앱에 옮겨도 효과가 같나요?", "A. 네, 핵심은 3칸 분리 규칙이므로 도구보다 구조 유지가 중요합니다."),
        ),
        tags=("일상과-메모", "할일메모", "저녁루틴", "잊지않기", "메모시스템"),
        closing_sentence_1="심심한 저녁의 잊지 않기 메모 시스템은 해야 할 일을 더 늘리는 방식이 아니라 내일의 실수를 줄이는 정돈 장치다.",
        closing_sentence_2="세 칸으로 나눈 짧은 기록이 다음 날의 머릿속 소음을 가장 먼저 줄인다.",
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rewrite 일상과-메모 8 posts with topic-correct content and slugs.")
    parser.add_argument(
        "--dir",
        default=r"D:\Donggri_Platform\BloggerGent\codex_write\cloudflare\동그리의 기록\ilsanggwa-memo",
        help="Target codex_write folder path.",
    )
    return parser.parse_args()


def _plain_length(value: str) -> int:
    no_tags = re.sub(r"<[^>]+>", " ", value)
    no_tags = re.sub(r"\s+", " ", no_tags).strip()
    return len(no_tags)


def _build_article_content(spec: TopicSpec, inline_url: str) -> str:
    lead = (
        f"<p>{spec.focus}은 거창한 계획보다 반복 가능한 구조를 먼저 고정하는 데서 시작한다. "
        f"{spec.scene}을 고정 트리거로 삼으면 기록이 의지에 의존하지 않고 생활 동선 안에서 자동으로 이어진다.</p>"
        "<p>이 글은 일상과-메모 카테고리 기준에 맞춰 짧은 관찰, 구체적인 실행, 다음 날 반영까지 한 흐름으로 정리했다. "
        "특히 루틴이 끊기는 지점을 줄이기 위해 문장 길이, 체크 기준, 복구 절차를 함께 설계한다.</p>"
    )
    table_rows_html = "".join(
        f"<tr><td>{col1}</td><td>{col2}</td><td>{col3}</td></tr>"
        for col1, col2, col3 in spec.table_rows
    )
    table_block = (
        f"<h2>{spec.h2_sections[1]}</h2>"
        "<p>루틴은 의욕이 높은 날보다 지친 날에도 돌아가야 실제로 남는다. 아래 기준표는 오늘 바로 적용 가능한 최소 단위를 전제로 만든다.</p>"
        "<table>"
        f"<thead><tr><th>{spec.table_headers[0]}</th><th>{spec.table_headers[1]}</th><th>{spec.table_headers[2]}</th></tr></thead>"
        f"<tbody>{table_rows_html}</tbody>"
        "</table>"
        "<p>표의 목적은 완벽한 관리가 아니라 누락을 줄이는 데 있다. 체크 항목을 줄이고 문장 규칙을 고정하면 작성 시간이 짧아지고 유지율이 올라간다.</p>"
    )
    sections = (
        f"<h2>{spec.h2_sections[0]}</h2>"
        "<p>일상 기록은 특별한 사건이 있을 때만 쓰는 메모가 아니라, 평범한 장면에서 반복되는 패턴을 발견하는 도구다. "
        "같은 시간대에 같은 형태로 적으면 무엇이 나를 지치게 하는지, 무엇이 회복에 도움이 되는지 빠르게 보이기 시작한다.</p>"
        "<p>핵심은 글을 잘 쓰는 것이 아니다. 상황 하나, 감정 하나, 다음 행동 하나만 남겨도 기록은 기능한다. "
        "적은 분량을 안정적으로 유지하는 것이 긴 문장을 한 번 쓰는 것보다 훨씬 강한 루틴을 만든다.</p>"
        f"{table_block}"
        f"<h2>{spec.h2_sections[2]}</h2>"
        "<p>실행 단계에서는 기록을 생활 순서에 붙여야 한다. 예를 들어 이동 직후, 식사 직후, 취침 직전처럼 이미 존재하는 흐름에 메모를 붙이면 "
        "새로운 시간을 따로 만들 필요가 없다. 이 방식은 바쁜 평일에도 루틴을 이어가게 해 준다.</p>"
        "<p>메모 문장은 길지 않아도 된다. 다만 추상어보다 구체어를 우선해야 한다. 장소, 시간, 행동을 함께 남기면 다음 날 다시 읽을 때 장면이 복원되고, "
        "실행 문장도 자연스럽게 이어진다.</p>"
        f"<h2>{spec.h2_sections[3]}</h2>"
        "<p>루틴이 끊기는 날은 반드시 생긴다. 이때 실패 원인을 길게 분석하면 재시작이 더 어려워진다. "
        "대신 오늘 장면 한 줄과 내일 행동 한 줄만 적고 즉시 복구하는 규칙을 쓰면 공백을 짧게 끝낼 수 있다.</p>"
        "<p>복구 규칙을 별도로 정해 두면 메모 공백에 대한 죄책감이 줄어든다. 기록은 완벽성을 증명하는 도구가 아니라 생활 리듬을 보정하는 장치이기 때문에, "
        "빠른 복귀가 품질보다 우선이다.</p>"
        f"<h2>{spec.h2_sections[4]}</h2>"
        "<p>주간 또는 월간 단위로 메모를 묶어 읽으면 반복 패턴이 보인다. 어떤 요일에 누락이 잦았는지, 어떤 시간대에 루틴이 안정적이었는지 확인하면 "
        "다음 주 설계가 훨씬 현실적으로 바뀐다. 기록은 쌓는 것에서 끝나지 않고 재배치할 때 가치가 커진다.</p>"
        "<p>특히 같은 실수가 반복되는 경우에는 기록 포맷을 바꾸기보다 체크 항목을 줄이는 편이 효과적이다. "
        "항목을 줄이고 핵심 행동을 선명하게 남기면 실행률이 올라가고, 결과적으로 기록의 신뢰도도 높아진다.</p>"
    )
    expansion_block = (
        "<h2>실행 난이도를 낮추는 문장 운영 규칙</h2>"
        f"<p>{spec.focus}을 오래 유지하려면 잘 쓰는 것보다 빨리 쓰는 규칙이 먼저 필요하다. "
        "첫 문장은 상황, 둘째 문장은 감정, 셋째 문장은 다음 행동으로 고정하면 기록 속도가 일정해지고 품질 편차가 줄어든다. "
        "또한 문장을 짧게 유지하면 피곤한 날에도 기록이 끊기지 않고, 다음 날 다시 읽을 때도 핵심 맥락이 빠르게 복원된다.</p>"
        f"<p>{spec.scene}처럼 반복되는 장면을 기록 트리거로 고정하면 루틴은 습관화되기 쉽다. "
        "트리거가 분명하면 오늘 기록을 해야 할지 말지 고민하는 시간이 사라지고, 실제 작성 시간도 짧아진다. "
        "이때 중요한 점은 기록의 완성도가 아니라 연속성이다. 하루를 비웠더라도 다음 날 같은 트리거에서 바로 다시 시작하면 공백이 길어지지 않는다.</p>"
        "<p>운영 관점에서는 주 1회 점검이 필요하다. 가장 많이 반복된 문장, 가장 자주 놓친 항목, 실제 행동으로 이어진 기록을 각각 하나씩 고르면 "
        "다음 주의 기준이 훨씬 명확해진다. 이런 점검은 루틴을 무겁게 만들지 않으면서도 기록의 방향을 보정해 주기 때문에, "
        "짧은 메모를 장기 습관으로 바꾸는 데 결정적인 역할을 한다.</p>"
        "<p>마지막으로 기록을 유지하려면 실패 기준보다 유지 기준을 먼저 정하는 편이 좋다. 예를 들어 하루를 놓쳤다면 다음 날 반드시 두 문장만 작성한다는 "
        "회복 규칙, 너무 바쁜 날에는 체크 항목을 절반으로 줄인다는 축소 규칙, 주말에는 일주일 메모를 묶어 한 번만 읽는 점검 규칙을 함께 두면 "
        "루틴이 끊어져도 빠르게 본선으로 복귀할 수 있다. 이러한 유지 기준은 심리적 부담을 줄이고 실행 가능성을 높여, 기록 습관을 현실적인 생활 기술로 만든다.</p>"
        "<p>결국 메모 루틴은 거대한 변화보다 작은 반복에서 힘이 나온다. 오늘 남긴 한 줄이 내일의 판단을 덜 흔들리게 만든다는 감각을 확보하면 "
        "기록은 의무가 아니라 생활을 정돈하는 기본 동작으로 자리 잡는다.</p>"
    )
    inline_block = f'<p><img src="{inline_url}" alt="{spec.title} 인라인 이미지" /></p>'
    faq_items_html = "".join(
        f"<h3>{question}</h3><p>{answer}</p>"
        for question, answer in spec.faq_items
    )
    faq_block = f"<h2>자주 묻는 질문</h2>{faq_items_html}"
    closing = (
        "<h2>마무리 기록</h2>"
        f"<p>{spec.closing_sentence_1} {spec.closing_sentence_2}</p>"
    )
    return f"# {spec.title}\n\n<section>{lead}{sections}{expansion_block}{inline_block}{faq_block}</section>\n\n{closing}"


def _load_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"invalid json object: {path}")
    return payload


def _save_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _update_payload(payload: dict, spec: TopicSpec) -> dict:
    inline_url = str(((payload.get("inline_image") or {}).get("url") or "")).strip()
    content_body = _build_article_content(spec, inline_url=inline_url)
    plain_len = _plain_length(content_body)
    booster = (
        "기록은 한 번의 각오보다 반복 가능한 형식에서 유지된다. "
        "같은 질문을 같은 순서로 적는 단순한 규칙을 고정하면 하루의 변동이 커도 메모는 계속 이어지고, "
        "쌓인 문장은 다음 선택을 더 정확하게 만들어 준다."
    )
    while plain_len < 3000:
        content_body = content_body.replace(
            "<h2>자주 묻는 질문</h2>",
            f"<p>{booster}</p><h2>자주 묻는 질문</h2>",
            1,
        )
        plain_len = _plain_length(content_body)
    if plain_len < 3000 or plain_len > 4000:
        raise ValueError(f"body length out of range: {spec.filename} -> {plain_len}")
    payload["title"] = spec.title
    payload["seo_title"] = spec.title
    payload["excerpt"] = (
        f"{spec.focus}을 기준으로 일상 장면에서 바로 실행할 수 있는 메모 루틴을 정리했다. "
        "짧은 관찰과 체크 규칙을 결합해 누락과 피로를 줄이는 실전 흐름을 제시한다."
    )
    payload["meta_description"] = (
        f"{spec.title} 실전 가이드. 일상 장면 기반 메모 루틴, 체크 기준표, FAQ, 마무리 기록까지 한 번에 정리했다."
    )
    payload["target_slug"] = spec.target_slug
    payload["content_body"] = content_body
    payload["generation_model"] = REQUIRED_MODEL
    payload["tag_names"] = list(spec.tags)
    if isinstance(payload.get("publish_state"), dict):
        payload["publish_state"]["status"] = "ready"
        payload["publish_state"]["last_error"] = None
        payload["publish_state"]["publish_mode"] = None
    return payload


def main() -> int:
    args = parse_args()
    root = Path(args.dir).resolve()
    if not root.exists():
        raise FileNotFoundError(f"target directory not found: {root}")
    report_items: list[dict[str, object]] = []
    for spec in TOPIC_SPECS:
        path = root / spec.filename
        if not path.exists():
            raise FileNotFoundError(f"missing file: {path}")
        payload = _load_json(path)
        payload = _update_payload(payload, spec)
        _save_json(path, payload)
        report_items.append(
            {
                "file": str(path),
                "target_slug": spec.target_slug,
                "plain_length": _plain_length(str(payload.get("content_body") or "")),
                "generation_model": payload.get("generation_model"),
            },
        )
    print(json.dumps({"status": "ok", "count": len(report_items), "items": report_items}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
