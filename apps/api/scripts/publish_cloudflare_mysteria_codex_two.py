from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from html import unescape
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from PIL import Image
from slugify import slugify

REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from package_common import CloudflareIntegrationClient, SessionLocal  # noqa: E402
from app.models.entities import ManagedChannel, SyncedCloudflarePost  # noqa: E402
from app.services.cloudflare.cloudflare_asset_policy import (  # noqa: E402
    build_cloudflare_r2_object_key,
    get_cloudflare_asset_policy,
)
from app.services.cloudflare.cloudflare_sync_service import sync_cloudflare_posts  # noqa: E402
from app.services.integrations.storage_service import upload_binary_to_cloudflare_r2  # noqa: E402
from sqlalchemy import select  # noqa: E402


TARGET_CATEGORY_ID = "cat-world-mysteria-story"
TARGET_CATEGORY_SLUG = "미스테리아-스토리"
TARGET_CATEGORY_LEAF = "miseuteria-seutori"
PATTERN_VERSION = 4
REPORT_DIR = Path(r"D:\Donggri_Runtime\BloggerGent\storage\the-midnight-archives\daily-runs")

TAG_RE = re.compile(r"<[^>]+>")
IMG_RE = re.compile(r"""<img\b[^>]*\bsrc=["']([^"']+)["']""", re.IGNORECASE)
MD_IMG_RE = re.compile(r"""!\[[^\]]*]\(([^)]+)\)""")
MD_EXPOSED_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s+|\*\*[^*\n]+?\*\*")
RAW_HTML_TEXT_RE = re.compile(r"&lt;/?(?:div|section|article|h[1-6]|p|img|figure)\b|</?(?:div|section|article)>\s*$", re.IGNORECASE)
SPACE_RE = re.compile(r"\s+")


POSTS: list[dict[str, Any]] = [
    {
        "topic": "Amber Room disappearance",
        "slug": "amber-room-nazi-loot-records-unclosed-search",
        "title": "사라진 호박방의 금빛 벽: 나치 약탈 기록과 아직 닫히지 않은 추적",
        "pattern": "evidence-breakdown",
        "source_image": Path(
            r"D:\Donggri_Runtime\BloggerGent\storage\cloudflare\미스테리아-스토리\images\source\amber-room-disappearance-history-mystery.png"
        ),
        "excerpt": (
            "호박방은 단순한 보물 전설이 아니라 전시 약탈, 철도 운송, 소련 기록 공백이 겹친 장기 추적 사건이다. "
            "이 글은 확인된 이동 경로와 이후 제기된 가설을 분리해 아직 닫히지 않은 빈칸을 정리한다."
        ),
        "meta": (
            "호박방 실종 사건을 나치 약탈 기록, 쾨니히스베르크 이동, 전후 수색 기록 중심으로 재검토하고 "
            "확인된 증거와 반복된 전설을 분리해 정리합니다."
        ),
        "labels": ["미스테리아 스토리", "호박방", "전쟁 약탈", "실종 보물", "기록 미스터리"],
        "body": """
## 사건 개요

호박방은 한때 프로이센 왕실의 장식 공간으로 만들어졌고, 이후 러시아 황실의 여름 궁전 안에서 가장 화려한 방으로 기억됐다. 벽면은 호박 조각과 금박, 거울 장식으로 채워졌고, 방 전체가 하나의 보석 상자처럼 보였다는 기록이 남아 있다. 그러나 이 사건을 흥미롭게 만드는 것은 값비싼 재료의 규모가 아니라, 전쟁이 끝난 뒤에도 이동 경로가 완전히 닫히지 않았다는 점이다.

1941년 독일군이 레닌그라드 인근으로 진격했을 때, 호박방은 해체되어 쾨니히스베르크 성으로 옮겨졌다고 알려져 있다. 이 지점까지는 비교적 견고한 기록이 있다. 문제는 이후다. 성은 폭격과 전투를 겪었고, 전후 도시 자체가 칼리닌그라드로 바뀌었다. 원래 방을 구성하던 패널이 불에 탔는지, 더 이른 시점에 다른 장소로 반출됐는지, 혹은 일부만 살아남았는지는 지금도 단정하기 어렵다.

그래서 호박방의 실종은 보물찾기 이야기가 아니라 기록 보존의 실패 사례로 읽을 필요가 있다. 전시 행정 문서, 박물관 목록, 목격담, 전후 수색 보고서가 서로 다른 속도로 남았고, 그 사이를 대중적 상상력이 메웠다. 이 글은 “어디에 숨겨져 있는가”보다 “어떤 증거가 아직 유효한가”를 중심으로 사건을 다시 정리한다.

## 증거 목록

첫 번째 핵심 증거는 쾨니히스베르크 성 전시 기록이다. 호박방 패널이 독일군에 의해 해체되어 동프로이센으로 이동했고, 성 안에서 공개 전시 또는 보관 상태에 있었다는 기록은 사건의 중심축이다. 이 기록이 있기 때문에 호박방 실종은 처음부터 허공에서 만들어진 전설이 아니다. 실제 물건이 이동했고, 실제 장소에 도착했으며, 그 뒤의 행방이 끊겼다는 구조가 성립한다.

두 번째 증거는 전쟁 말기의 파괴 상황이다. 쾨니히스베르크는 연합군 폭격과 지상전, 화재를 겪었다. 이 때문에 “성 안에서 소실됐다”는 설명은 가장 현실적인 가설 가운데 하나다. 장식 패널은 습도와 충격에 약했고, 보관 조건이 나빠지면 균열과 박리가 생길 수 있었다. 화재까지 겹쳤다면 원형 보존은 매우 어려웠을 것이다.

세 번째 증거는 전후에 발견된 일부 조각과 관련 문서다. 완전한 호박방은 발견되지 않았지만, 장식 일부로 추정되는 조각과 관련 유물은 간헐적으로 등장했다. 이런 단편은 전체가 살아 있다는 증거가 아니라, 적어도 해체와 이동 과정에서 일부가 분산됐을 가능성을 보여 준다. 그래서 “전부 소실”과 “전부 은닉” 사이에는 여러 중간 시나리오가 존재한다.

네 번째 증거는 반복되는 수색 지점이다. 지하 벙커, 폐광, 침몰 선박, 철도 터널, 귀족 저택이 후보로 언급돼 왔다. 그러나 많은 후보는 실제 문서보다 전후 소문과 지역 전승에 기대고 있다. 수색 자체가 이어졌다는 사실과 그 수색이 성과를 냈다는 주장은 구분해야 한다. 미스테리아 스토리에서 중요한 기준은 바로 이 분리다.

## 반론과 한계

가장 큰 한계는 전쟁 말기의 행정 기록이 완전하지 않다는 점이다. 물품 이동 명령이 있었더라도 마지막 보관 장소가 기록되지 않았을 수 있고, 반대로 반출 기록이 남지 않았다고 해서 반출이 없었다고 단정할 수도 없다. 전쟁 말기의 혼란은 기록의 부재를 곧바로 결론으로 바꾸기 어렵게 만든다.

또 하나의 문제는 “발견 직전” 보도가 반복됐다는 점이다. 호박방은 워낙 상징성이 커서 작은 단서도 큰 뉴스가 되기 쉽다. 특정 터널이나 지하 공간에서 금속 반응이 나왔다거나, 누군가의 회고록에 비슷한 묘사가 있다는 이유만으로 사건 전체가 다시 흔들렸다. 하지만 이런 단서는 검증 절차를 통과해야 한다. 현장 접근, 물질 분석, 문서 대조, 소유 경로 확인이 함께 이뤄지지 않으면 흥미로운 이야기로만 남는다.

소실설도 완벽하지는 않다. 성이 파괴됐다는 사실은 강력하지만, 패널이 그 직전 다른 장소로 옮겨졌다면 화재 설명은 핵심을 비껴간다. 반대로 은닉설도 결정적 증거가 없다. 어딘가에 숨겨졌다면 왜 관리 기록, 운송 책임자, 회수 시도 문서가 더 뚜렷하게 남지 않았는지 설명해야 한다. 결국 두 설명은 모두 가능한 범위를 갖지만, 어느 쪽도 사건을 완전히 닫지는 못한다.

따라서 호박방은 “사라진 보물”이라는 낭만적 제목보다 “전쟁이 물건의 출처와 책임을 어떻게 파괴하는가”라는 질문에 더 가깝다. 물건이 귀중할수록 기록은 많아야 하지만, 전쟁은 그 기록을 가장 먼저 찢어 놓는다. 이 모순 때문에 사건은 지금도 끝나지 않는다.

## 마무리 기록

현재 가장 신중한 결론은 호박방이 쾨니히스베르크까지 이동했다는 점, 그 뒤에는 소실과 분산 가능성이 모두 남아 있다는 점이다. 완전한 방이 어딘가에 온전하게 보관돼 있다는 주장은 매력적이지만, 입증 부담이 크다. 반면 성 안에서 대부분 소실됐다는 설명은 현실적이지만, 일부 조각과 전후 증언의 빈칸까지 모두 지우지는 못한다.

이 사건을 다시 볼 때 중요한 것은 보물의 가격이 아니라 증거의 층위다. 확인된 이동, 확인되지 않은 반출, 반복된 수색, 검증되지 않은 목격담을 같은 무게로 놓으면 이야기는 금방 흐려진다. 호박방은 금빛 벽을 잃어버린 사건이면서 동시에 전쟁 기록의 가장 어두운 한계를 보여 주는 사례다.

그렇기 때문에 앞으로 새로운 단서가 나오더라도 핵심 질문은 단순하다. 그 단서가 실제 패널과 물질적으로 연결되는가. 전쟁 전후의 소유 경로를 설명하는가. 독립적인 문서와 현장 증거가 서로 맞물리는가. 이 세 질문을 통과하지 못하면 호박방은 다시 전설의 무대로 돌아간다.

### 자주 묻는 질문

**Q1. 호박방은 완전히 불탔다고 봐야 하나?**
가장 현실적인 설명 중 하나지만 확정은 아니다. 쾨니히스베르크 성 파괴가 강력한 근거이지만, 일부 반출이나 분산 가능성을 완전히 배제할 자료도 부족하다.

**Q2. 지금 발견되는 후보지는 믿을 만한가?**
후보지는 검토할 수 있지만, 물질 분석과 문서 대조가 없으면 신뢰하기 어렵다. 많은 보도는 현장 추정이나 지역 전승에 머무른다.

**Q3. 복원된 호박방은 원본인가?**
현재 볼 수 있는 호박방은 복원물이다. 원본의 행방 문제와 복원된 공간의 예술적 가치는 분리해서 봐야 한다.
""",
    },
    {
        "topic": "Bell Island Boom 1978",
        "slug": "bell-island-boom-1978-newfoundland-shock-record",
        "title": "벨 아일랜드 폭발음: 하늘도 땅도 설명하지 못한 1978년의 충격",
        "pattern": "scene-investigation",
        "source_image": Path(r"D:\Donggri_Runtime\BloggerGent\storage\images\mystery\the-legend-and-reality-of-bell-island.webp"),
        "excerpt": (
            "1978년 뉴펀들랜드 벨 아일랜드에서 보고된 폭발음은 번개, 지반, 군사 실험, 전자기 현상이 뒤섞인 사건으로 남았다. "
            "이 글은 현장 피해와 조사 기록을 따라가며 왜 단순한 소문으로 정리되지 않는지 살핀다."
        ),
        "meta": (
            "벨 아일랜드 폭발음 사건을 현장 피해, 전자기 이상 보고, 기상 가설, 군사 실험 의혹으로 나누어 "
            "확인된 기록과 과장된 해석을 분리합니다."
        ),
        "labels": ["미스테리아 스토리", "벨 아일랜드", "뉴펀들랜드", "폭발음", "현장 미스터리"],
        "body": """
## 현장 묘사

1978년 4월, 캐나다 뉴펀들랜드의 벨 아일랜드에서는 갑작스러운 폭발음과 진동이 보고됐다. 주민들은 집이 흔들렸고, 전기 설비가 손상됐으며, 땅과 하늘 중 어디에서 충격이 왔는지 판단하기 어려웠다고 말했다. 이 사건은 규모가 큰 재난은 아니었지만 이상한 점이 많았다. 짧은 순간의 충격이었는데도 사람들의 기억에는 오래 남았고, 지역 신문과 조사 기록을 거치며 하나의 미스터리로 굳어졌다.

벨 아일랜드는 대도시 한복판이 아니라 바다와 광산, 작은 주거지가 맞물린 장소다. 이런 환경은 사건을 더 복잡하게 만든다. 천둥이나 번개 같은 자연 현상도 가능하고, 오래된 지반이나 광산 구조가 영향을 줬을 가능성도 있다. 동시에 외딴 섬이라는 조건 때문에 군사 실험, 전자기 무기, 비밀 관측 같은 해석이 쉽게 덧붙었다.

사건의 핵심은 “무엇이 터졌는가”보다 “왜 피해 양상이 애매했는가”에 있다. 일반적인 폭발이라면 파편, 화재, 충격 중심점이 더 분명해야 한다. 그러나 벨 아일랜드 사건은 소리, 흔들림, 전기 이상, 동물 반응 같은 주변 증언이 강하고 물리적 원점은 상대적으로 흐리다. 그래서 이 사건은 현장 조사형 미스터리로 읽는 것이 적합하다.

## 동선과 시간

사건은 짧은 시간 안에 발생했지만, 그 전후의 기록이 중요하다. 주민들은 큰 굉음과 함께 진동을 느꼈고, 일부 집에서는 전기 계통 손상이나 금속 물체 주변의 이상이 언급됐다. 전선, 텔레비전, 퓨즈, 가축 반응 같은 요소가 이야기 안에 들어오면서 사건은 단순한 기상 현상만으로 설명하기 어려운 분위기를 갖게 됐다.

조사자들이 주목한 것은 충격의 방향과 피해의 종류였다. 만약 낙뢰라면 전기 손상과 소리가 동시에 설명될 수 있다. 특히 바다 근처의 기상 조건과 지형은 강한 전기적 현상을 만들 수 있다. 그러나 주민들이 기억한 진동의 강도와 특정 물체 주변의 반응은 일반적인 번개 경험과 다르게 느껴졌고, 이 차이가 사건을 계속 열어 두었다.

시간표를 복원할 때는 목격담의 순서를 조심해야 한다. 굉음이 먼저였는지, 진동이 먼저였는지, 전기 손상이 같은 순간에 발생했는지, 이후에 발견됐는지는 증언마다 다를 수 있다. 미스터리 사건은 한 문장으로 압축될수록 더 극적으로 보이지만, 실제 검토에서는 각 보고가 언제 확인됐는지 나눠야 한다.

벨 아일랜드의 경우 현장 소문이 빠르게 확산됐고, 외부 조사자가 찾아오면서 사건은 더 넓은 이야기로 바뀌었다. 이때부터 자연 현상 설명과 비밀 실험 설명이 경쟁하기 시작했다. 그러나 경쟁하는 설명이 많다는 사실은 곧바로 초자연적 결론을 뜻하지 않는다. 오히려 기본 자료가 부족할수록 설명이 많이 생긴다는 점을 보여 준다.

## 이상한 지점

가장 이상한 지점은 전기적 손상과 폭발음이 함께 언급된다는 점이다. 낙뢰 가설은 이 조합을 비교적 잘 설명한다. 강한 번개나 구상번개, 드문 대기 전기 현상이 있었다면 소리와 전자기적 피해가 동시에 나타날 수 있다. 하지만 구상번개 자체가 관측과 재현이 어려운 현상이라, 그것을 설명으로 삼아도 사건이 완전히 닫히지는 않는다.

두 번째 지점은 군사 실험 의혹이다. 냉전기에는 비밀 장비와 전파 실험에 대한 상상이 쉽게 퍼졌다. 일부 이야기에서는 고출력 전자기 장치나 대기 실험이 사건의 배후로 거론된다. 그러나 이 주장은 흥미로운 만큼 증거 부담이 크다. 실험 주체, 장비 위치, 당시 운용 기록, 피해와의 물리적 연결이 확인되어야 하는데, 공개적으로 확정된 자료는 충분하지 않다.

세 번째 지점은 지반과 광산의 영향이다. 벨 아일랜드는 광산 역사와 연결된 지역이기 때문에 지하 구조가 충격을 증폭했을 가능성도 검토할 수 있다. 하지만 지진이나 붕괴라면 지질 기록과 피해 분포가 더 분명해야 한다. 이 가설은 장소의 특성을 설명하지만 전기 손상 보고까지 매끄럽게 묶기는 어렵다.

결국 사건의 이상함은 하나의 거대한 단서보다 작은 단서들의 조합에서 나온다. 소리만 있었다면 천둥이었을 수 있고, 전기 손상만 있었다면 낙뢰였을 수 있으며, 진동만 있었다면 지반 문제였을 수 있다. 그런데 세 요소가 한꺼번에 이야기되면서 사건은 단일 원인으로 정리되기 어려워졌다.

## 마무리 기록

벨 아일랜드 폭발음 사건을 가장 신중하게 정리하면, 드문 대기 전기 현상 또는 강한 낙뢰 계열 설명이 가장 현실적인 출발점이다. 다만 이 설명도 주민들이 보고한 모든 세부를 완벽하게 닫지는 못한다. 그래서 사건은 과학적 설명과 지역 전설 사이에 걸쳐 있다.

이 사건을 음모론으로만 보거나, 반대로 단순한 천둥으로만 축소하면 기록의 흥미로운 부분을 놓치게 된다. 중요한 것은 당시 사람들이 실제로 어떤 피해를 확인했는지, 어떤 설명이 이후에 덧붙었는지, 어떤 부분이 독립적으로 검증됐는지 나누는 일이다. 벨 아일랜드는 바로 그 경계선이 선명한 사례다.

오늘 이 사건을 다시 읽는 이유도 여기에 있다. 미스터리는 항상 답이 없어서 남는 것이 아니다. 때로는 답이 여러 개 가능해 보이지만, 각각의 답이 마지막 한 조각을 놓치기 때문에 남는다. 벨 아일랜드의 폭발음은 하늘과 땅 사이에서 발생한 기록의 빈칸으로 남아 있으며, 그 빈칸이 사건을 아직도 살아 있게 만든다.

### 자주 묻는 질문

**Q1. 벨 아일랜드 사건은 낙뢰였나?**
가장 현실적인 설명 중 하나는 강한 낙뢰나 대기 전기 현상이다. 다만 일부 피해와 증언이 일반적인 번개 경험과 다르게 정리되어 논쟁이 이어졌다.

**Q2. 군사 실험 가능성은 확인됐나?**
공개적으로 확정된 증거는 부족하다. 비밀 실험설은 유명하지만, 장비와 위치, 피해를 연결하는 검증 자료가 충분하지 않다.

**Q3. 왜 지금도 미스터리로 남았나?**
사건 자체가 짧고 현장 자료가 제한적이기 때문이다. 소리, 진동, 전기 손상이 함께 보고됐지만 각각을 하나의 원인으로 완전히 설명하기 어렵다.
""",
    },
]

POSTS[0]["body"] = POSTS[0]["body"].replace(
    "### 자주 묻는 질문",
    """전후 수색이 계속된 이유도 이 구조와 연결된다. 한쪽에서는 성의 화재와 붕괴가 사실상 사건을 끝냈다고 본다. 다른 쪽에서는 철도 이동과 지하 보관 가능성을 끝까지 추적해야 한다고 본다. 두 입장은 서로 반대처럼 보이지만, 실제로는 같은 빈칸을 다른 방식으로 읽는다. 마지막 운송 문서, 마지막 보관 책임자, 마지막 목격 지점이 완전하지 않기 때문에 양쪽 모두 일정한 설득력을 얻는다.

호박방 이야기가 오래 살아남은 또 다른 이유는 원본과 복원본이 동시에 존재하기 때문이다. 복원된 공간은 관람객에게 사건이 끝난 것처럼 보이게 만들지만, 원본 패널의 행방은 여전히 별개의 문제다. 복원은 문화재 기억을 되살리는 작업이고, 실종 수사는 사라진 물건의 이동 경로를 묻는 작업이다. 이 둘을 섞으면 “이미 되찾았다”는 오해와 “어딘가에 반드시 온전하다”는 기대가 동시에 생긴다.

따라서 앞으로의 검토는 낭만적 보물찾기보다 출처 추적에 가까워야 한다. 후보지가 제시되면 먼저 그 장소가 1944년부터 1945년 사이 실제 운송망과 연결되는지 확인해야 한다. 그다음 보관 책임자나 군 행정 문서가 있는지 살펴야 한다. 마지막으로 발견 물질이 원본 호박방의 제작 방식, 장식 패턴, 보수 흔적과 맞는지 검증해야 한다. 이 순서가 무너지면 사건은 다시 소문으로 돌아간다.

또 하나 놓치기 쉬운 부분은 정치적 기억의 문제다. 호박방은 러시아, 독일, 폴란드, 발트 지역의 전쟁 기억과 동시에 연결된다. 누가 약탈했고, 누가 잃어버렸고, 누가 복원했는지를 둘러싼 서사는 단순한 문화재 관리 기록을 넘어선다. 그래서 어떤 단서가 나올 때마다 사건은 역사 논쟁과 외교적 감정까지 끌어들인다. 이 배경을 이해해야 왜 작은 파편 하나가 큰 기사로 번지는지 설명할 수 있다.

현실적인 수색은 화려한 탐험보다 지루한 대조 작업에 가깝다. 보관 창고 목록, 철도 운송표, 군 행정 문서, 전후 압수 목록, 개인 회고록의 날짜를 서로 맞춰야 한다. 같은 장소가 여러 이름으로 기록됐을 수 있고, 같은 물건이 다른 분류명으로 적혔을 수도 있다. 호박방 사건의 난점은 물건이 사라졌다는 데만 있지 않다. 물건을 설명하는 언어와 행정 체계까지 전쟁 속에서 흩어졌다는 데 있다.

### 자주 묻는 질문""",
)

POSTS[1].update(
    {
        "topic": "Taos Hum acoustic mystery",
        "slug": "taos-hum-acoustic-studies-local-testimony-record",
        "title": "타오스 험: 들리는 사람에게만 남는 저주파 소리의 기록",
        "pattern": "evidence-breakdown",
        "source_image": Path(
            r"D:\Donggri_Runtime\BloggerGent\storage\images\taos-hum-acoustic-studies-local-testimony-environmental-explanations.png"
        ),
        "excerpt": (
            "타오스 험은 모두에게 들리지 않지만 일부 주민에게는 지속적인 저주파 소리로 보고된 현상이다. "
            "이 글은 청각 증언, 환경 소음, 심리 생리학적 설명을 나누어 왜 사건이 쉽게 닫히지 않는지 정리한다."
        ),
        "meta": (
            "타오스 험 현상을 주민 증언, 저주파 소음 가설, 산업·전력 설비 가능성, 청각 민감도와 심리 생리학적 설명으로 "
            "나누어 검토합니다."
        ),
        "labels": ["미스테리아 스토리", "타오스 험", "저주파 소음", "청각 미스터리", "환경 기록"],
        "body": """
## 사건 개요

타오스 험은 미국 뉴멕시코 타오스 일대에서 일부 주민들이 지속적인 낮은 윙윙거림을 들었다고 보고하면서 유명해진 현상이다. 흥미로운 점은 모두가 같은 소리를 듣는 것이 아니라는 데 있다. 어떤 사람에게는 밤마다 이어지는 저주파 진동처럼 느껴지고, 어떤 사람에게는 전혀 감지되지 않는다. 이 차이 때문에 사건은 환경 소음 문제이면서 동시에 청각 경험의 문제로 남았다.

이 현상은 단순한 도시 괴담으로만 보기 어렵다. 주민 증언이 반복됐고, 언론과 연구자들이 원인 조사를 시도했으며, 비슷한 “험” 현상이 다른 지역에서도 보고됐다. 그러나 소리의 정확한 위치와 주파수, 발생 시간이 안정적으로 고정되지 않으면서 조사 결과는 명쾌한 결론에 이르지 못했다. 소리를 듣는 사람의 고통은 실제였지만, 외부 장비가 항상 같은 원인을 잡아내지는 못했다.

타오스 험을 다룰 때 가장 중요한 기준은 “들렸는가”와 “외부 음원이 확인됐는가”를 분리하는 일이다. 사람이 실제로 고통을 느꼈다는 사실이 곧 외부 장치의 존재를 증명하지는 않는다. 반대로 장비가 특정 순간에 원인을 찾지 못했다고 해서 경험 자체를 무시할 수도 없다. 이 글은 두 층위를 나누어 확인 가능한 증거와 남은 공백을 정리한다.

## 증거 목록

첫 번째 증거는 주민 증언의 지속성이다. 타오스 험을 들었다고 말한 사람들은 대체로 낮고 지속적인 진동, 멀리서 도는 엔진, 전기 장치의 울림 같은 표현을 사용했다. 특히 밤이나 조용한 실내에서 더 강하게 느껴진다는 보고가 많았다. 이 패턴은 주변 소음이 줄어들 때 특정 주파수나 내부 청각 감각이 더 두드러질 수 있음을 시사한다.

두 번째 증거는 환경 소음 가설이다. 산업 설비, 송전선, 펌프, 환기 장치, 장거리 교통 소음, 지형을 타고 전달되는 기계음이 후보로 제시됐다. 저주파 소리는 방향을 특정하기 어렵고 건물 구조를 통해 증폭되거나 약해질 수 있다. 그래서 실제 음원이 존재하더라도 주민이 느끼는 위치와 장비가 측정하는 위치가 다르게 나타날 수 있다.

세 번째 증거는 생리학적 설명이다. 일부 사람은 이명, 혈류 소리, 근육 긴장, 청각 과민, 스트레스 반응 때문에 외부 음원 없이도 낮은 소리를 경험할 수 있다. 이 설명은 “왜 모두가 듣지 못하는가”를 설명하는 데 유용하다. 그러나 같은 지역에서 비슷한 표현의 증언이 반복됐다는 점까지 모두 개인 문제로 돌리기에는 조심스러운 부분이 있다.

네 번째 증거는 다른 지역의 유사 사례다. 브리스톨 험, 윈저 험처럼 지역명과 함께 불리는 사례가 여러 차례 보고됐다. 어떤 경우에는 산업 설비나 공장 소음이 원인으로 좁혀졌고, 어떤 경우에는 뚜렷한 결론이 남지 않았다. 타오스 험도 이 넓은 계열 안에서 봐야 한다. 지역 전설이 아니라 저주파 소음 조사와 인간 청각의 경계 사례에 가깝다.

## 반론과 한계

가장 큰 한계는 측정의 재현성이다. 특정 주민이 소리를 듣는 시간에 장비가 같은 현상을 기록해야 원인 추적이 쉬워진다. 그러나 실제 현장은 그렇게 단순하지 않다. 소리는 날씨, 지형, 건물 구조, 시간대, 전력 사용량, 교통량에 따라 바뀔 수 있다. 짧은 조사 기간에 모든 조건을 포착하기 어렵다.

또 다른 한계는 증언의 언어가 물리량과 바로 대응하지 않는다는 점이다. 한 사람이 “엔진 소리 같다”고 말해도 그것이 실제 엔진이라는 뜻은 아니다. “진동”이라고 표현해도 공기 중 소리인지, 몸의 감각인지, 건물의 미세 흔들림인지 구분해야 한다. 미스터리 사건에서 증언은 출발점이지만 최종 결론은 아니다.

음모론적 설명도 반복된다. 비밀 군사 장비, 지하 시설, 전파 실험 같은 주장이 대표적이다. 그러나 이런 설명은 원인을 크게 보이게 만드는 대신 검증 가능한 연결고리가 약한 경우가 많다. 어떤 장비가 언제 어디서 어떤 출력으로 작동했고, 그 신호가 왜 일부 주민에게만 들렸는지 설명해야 한다. 그 단계가 없으면 의혹은 흥미로운 이야기일 뿐이다.

반대로 “전부 이명”이라고 단정하는 것도 위험하다. 일부 사례는 개인 청각 문제로 설명될 수 있지만, 지역적으로 비슷한 호소가 이어졌다면 외부 환경을 함께 살펴야 한다. 타오스 험은 외부 소음과 내부 청각 경험이 서로 배타적인 설명이 아니라, 동시에 작동할 수 있다는 점에서 더 까다롭다.

## 마무리 기록

타오스 험의 가장 신중한 결론은 단일 원인으로 닫기 어렵다는 것이다. 일부는 환경 저주파 소음, 일부는 건물 공진, 일부는 개인 청각 조건, 일부는 지역적 기대와 불안이 겹쳤을 가능성이 있다. 이 설명은 화려하지 않지만 현상 전체를 가장 덜 왜곡한다.

이 사건이 지금도 흥미로운 이유는 초자연적 결론 때문이 아니다. 사람의 감각과 측정 장비, 지역 환경이 서로 어긋날 때 어떤 일이 벌어지는지 보여 주기 때문이다. 소리를 듣는 사람에게는 고통이 실제이고, 원인을 찾는 사람에게는 증거가 불완전하다. 그 사이에서 사건은 계속 미스터리로 남는다.

앞으로 비슷한 현상을 조사하려면 증언 기록과 장기 측정을 함께 해야 한다. 날짜, 시간, 날씨, 전력 사용, 교통량, 실내 위치, 신체 상태를 같은 형식으로 남겨야 한다. 그런 데이터가 쌓여야 특정 음원인지, 건물 공진인지, 개인 청각 조건인지 분리할 수 있다. 타오스 험은 답이 없는 소문이 아니라, 조사 방법이 얼마나 정밀해야 하는지를 보여 주는 사례다.

### 자주 묻는 질문

**Q1. 타오스 험은 실제 소리였나?**
일부 주민의 경험은 실제였다고 볼 수 있다. 다만 그 경험이 모두 하나의 외부 음원에서 왔는지는 확정되지 않았다.

**Q2. 왜 어떤 사람만 들었나?**
저주파 민감도, 이명, 건물 구조, 시간대, 심리적 긴장 등이 영향을 줄 수 있다. 이 차이가 사건을 단순한 소음 민원보다 복잡하게 만든다.

**Q3. 가장 설득력 있는 설명은 무엇인가?**
환경 저주파 소음과 개인 청각 조건이 함께 작동했을 가능성이 가장 신중하다. 단일한 비밀 장치나 초자연 현상으로 단정할 증거는 부족하다.
""",
    }
)

POSTS[1]["body"] = POSTS[1]["body"].replace(
    "### 자주 묻는 질문",
    """타오스 험을 둘러싼 논쟁에서 자주 빠지는 것은 생활 환경의 미세한 변화다. 같은 집에서도 방 위치, 벽 두께, 배관 상태, 전기 장치 배치, 창문 방향에 따라 저주파가 다르게 느껴질 수 있다. 그래서 한 가족 안에서도 누군가는 소리를 듣고 누군가는 듣지 못하는 일이 가능하다. 이런 차이는 증언을 약하게 만드는 요소가 아니라, 오히려 현상을 제대로 측정하려면 생활 공간 전체를 기록해야 한다는 신호다.

또한 지역 사회의 반응도 사건을 키웠다. 설명되지 않는 소리를 들은 사람이 혼자라고 느낄 때는 개인 문제로 숨기기 쉽다. 그러나 비슷한 증언이 모이면 현상은 공적 문제가 된다. 이때 언론 보도는 도움과 위험을 동시에 만든다. 더 많은 증언을 모으게 하지만, 동시에 사람들이 자신의 경험을 이미 알려진 표현에 맞춰 설명하게 만들 수 있다. 그래서 타오스 험의 자료를 볼 때는 최초 증언과 보도 이후 증언을 분리해야 한다.

측정 방식에서도 장기성이 중요하다. 하루나 이틀 동안 장비를 놓고 아무것도 잡히지 않았다고 해서 현상이 없었다고 말하기 어렵다. 반대로 특정 밤에 낮은 주파수가 측정됐다고 해서 그것이 모든 주민 경험의 원인이라고 단정할 수도 없다. 필요한 것은 여러 계절, 여러 시간대, 여러 건물에서 같은 형식으로 누적한 데이터다. 타오스 험은 답보다 방법론을 요구하는 미스터리다.

이 점에서 사건은 현대적인 의미가 있다. 도시와 교외에는 모터, 송풍기, 변압기, 냉난방 장치, 장거리 교통 소음이 늘어났다. 인간은 그 모든 소리를 뚜렷하게 듣지는 못하지만, 일부 주파수는 몸의 피로와 불안을 통해 감지될 수 있다. 타오스 험은 괴담처럼 소비되기 쉽지만, 실제로는 보이지 않는 소음 환경을 어떻게 기록하고 설명할 것인가라는 질문을 남긴다.

마지막으로, 이 사건은 “증명되지 않았다”와 “존재하지 않는다”를 구분하게 만든다. 주민의 경험은 가볍게 지울 수 없지만, 그 경험을 설명하는 가설은 검증을 통과해야 한다. 타오스 험은 과학과 증언이 충돌하는 사건이라기보다, 서로 다른 종류의 증거를 같은 표에 올려놓을 때 얼마나 조심해야 하는지를 보여 주는 사례다. 그래서 결론은 단정이 아니라 기록 방식의 개선으로 이어져야 한다.

그 점에서 이 사건은 작은 소리의 문제가 아니라 기록되지 않는 생활 감각의 문제로 남는다.

### 자주 묻는 질문""",
)



def _strip_tags(text: str) -> str:
    return SPACE_RE.sub(" ", unescape(TAG_RE.sub(" ", text or ""))).strip()


def _plain_length(content: str) -> int:
    no_figures = re.sub(r"<figure\b.*?</figure>", " ", content or "", flags=re.IGNORECASE | re.DOTALL)
    no_md_imgs = MD_IMG_RE.sub(" ", no_figures)
    return len(SPACE_RE.sub("", _strip_tags(no_md_imgs)))


def _hangul_count(content: str) -> int:
    return len(re.findall(r"[가-힣]", _strip_tags(content)))


def _duplicate_sentence_ratio(content: str) -> float:
    text = _strip_tags(content)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?。！？다요죠음임까])\s+", text) if len(s.strip()) >= 20]
    if not sentences:
        return 0.0
    normalized = [SPACE_RE.sub(" ", s).strip().casefold() for s in sentences]
    duplicate_count = len(normalized) - len(set(normalized))
    return round(duplicate_count / max(len(normalized), 1), 4)


def _to_webp_bytes(path: Path) -> bytes:
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() == ".webp":
        return path.read_bytes()
    with Image.open(path) as image:
        image = image.convert("RGB")
        buffer = BytesIO()
        image.save(buffer, format="WEBP", quality=88, method=6)
        return buffer.getvalue()


def _content_with_hero(cover_url: str, title: str, body: str) -> str:
    return (
        f'<figure data-media-block="true"><img src="{cover_url}" alt="{title}" '
        f'loading="eager" decoding="async" /></figure>\n\n'
        f"{body.strip()}\n"
    )


def _post_url_slug(url: str) -> str:
    path = urlparse(url or "").path.strip("/")
    return path.split("/")[-1] if path else ""


def _find_duplicate(posts: list[dict[str, Any]], post: dict[str, Any]) -> list[dict[str, str]]:
    slug = str(post["slug"]).strip().lower()
    topic = str(post["topic"]).strip().lower()
    distinctive = [token for token in re.split(r"[^a-z0-9]+", topic) if len(token) >= 4]
    hits: list[dict[str, str]] = []
    for item in posts:
        category = item.get("category") if isinstance(item.get("category"), dict) else {}
        if str(category.get("id") or item.get("categoryId") or "") != TARGET_CATEGORY_ID:
            continue
        text = " ".join(str(item.get(key) or "") for key in ("title", "slug", "publicUrl", "url")).lower()
        if slug in text or (distinctive and all(token in text for token in distinctive[:2])):
            hits.append(
                {
                    "title": str(item.get("title") or ""),
                    "slug": str(item.get("slug") or ""),
                    "url": str(item.get("publicUrl") or item.get("url") or ""),
                }
            )
    return hits


def _normalize_seo_description(value: str, *, fallback: str) -> str:
    text = SPACE_RE.sub(" ", str(value or "").strip())
    if len(text) < 90:
        text = SPACE_RE.sub(" ", f"{text} {fallback}".strip())
    if len(text) > 170:
        text = text[:169].rstrip(" ,.;") + "."
    if len(text) < 90:
        text = (text + " 기록과 증거를 분리해 독자가 사건의 핵심을 빠르게 이해하도록 정리합니다.")[:170]
    return text


def _find_existing_slug_post(posts: list[dict[str, Any]], slug: str) -> dict[str, Any] | None:
    normalized = str(slug or "").strip()
    for item in posts:
        if str(item.get("slug") or "").strip() == normalized:
            return item
    return None


def _create_or_publish(
    client: CloudflareIntegrationClient,
    payload: dict[str, Any],
    *,
    category_id: str,
    existing_post_id: str = "",
) -> dict[str, Any]:
    post_id = str(existing_post_id or "").strip()
    if not post_id:
        draft_payload = dict(payload)
        draft_payload["status"] = "draft"
        draft_payload["categorySlug"] = TARGET_CATEGORY_LEAF
        draft_payload.pop("categoryId", None)
        created = client._request("POST", "/api/integrations/posts", json_payload=draft_payload, timeout=120.0)
        if not isinstance(created, dict) or not str(created.get("id") or "").strip():
            raise RuntimeError(f"invalid_create_response:{created}")
        post_id = str(created["id"]).strip()
    final_payload = dict(payload)
    final_payload["status"] = "published"
    final_payload["categoryId"] = category_id
    final_payload.pop("categorySlug", None)
    published = client._request("PUT", f"/api/integrations/posts/{post_id}", json_payload=final_payload, timeout=120.0)
    if not isinstance(published, dict):
        raise RuntimeError(f"invalid_publish_response:{published}")
    return published


def _verify_live(url: str, hero_url: str, *, timeout: float) -> dict[str, Any]:
    page = httpx.get(url, timeout=timeout, follow_redirects=True)
    html = page.text if page.status_code < 500 else ""
    imgs = IMG_RE.findall(html)
    hero = httpx.get(hero_url, timeout=timeout, follow_redirects=True)
    plain_text_length = _plain_length(html)
    return {
        "url": url,
        "live_status": page.status_code,
        "hero_status": hero.status_code,
        "hero_content_type": str(hero.headers.get("content-type") or ""),
        "plain_text_length": plain_text_length,
        "image_count": len(imgs),
        "markdown_exposed": bool(MD_EXPOSED_RE.search(_strip_tags(html))),
        "raw_html_exposed": bool(RAW_HTML_TEXT_RE.search(_strip_tags(html))),
        "duplicate_sentence_ratio": _duplicate_sentence_ratio(html),
        "pass": (
            page.status_code == 200
            and hero.status_code == 200
            and "image/webp" in str(hero.headers.get("content-type") or "").lower()
            and plain_text_length >= 3000
            and len(imgs) == 1
            and not bool(MD_EXPOSED_RE.search(_strip_tags(html)))
            and not bool(RAW_HTML_TEXT_RE.search(_strip_tags(html)))
        ),
    }


def run(*, mode: str, timeout: float) -> dict[str, Any]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    artifact_root = REPORT_DIR / f"codex-two-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    artifact_root.mkdir(parents=True, exist_ok=True)

    with SessionLocal() as db:
        client = CloudflareIntegrationClient.from_db(db)
        categories = client.list_categories()
        category = next((item for item in categories if str(item.get("id") or "") == TARGET_CATEGORY_ID), None)
        if not category:
            raise RuntimeError("target_category_not_found")
        posts = client.list_posts()
        channel = db.execute(
            select(ManagedChannel).where(
                ManagedChannel.provider == "cloudflare",
                ManagedChannel.channel_id == "cloudflare:dongriarchive",
            )
        ).scalar_one_or_none()
        policy = get_cloudflare_asset_policy(channel)

        results: list[dict[str, Any]] = []
        for post in POSTS:
            duplicates = _find_duplicate(posts, post)
            local_metrics = {
                "plain_text_length": _plain_length(post["body"]),
                "hangul_count": _hangul_count(post["body"]),
                "duplicate_sentence_ratio": _duplicate_sentence_ratio(post["body"]),
            }
            item_result: dict[str, Any] = {
                "topic": post["topic"],
                "title": post["title"],
                "slug": post["slug"],
                "article_pattern_id": post["pattern"],
                "article_pattern_version": PATTERN_VERSION,
                "duplicates": duplicates,
                "local_metrics": local_metrics,
                "source_image": str(post["source_image"]),
                "status": "planned",
            }
            if duplicates:
                item_result["status"] = "blocked_duplicate"
                results.append(item_result)
                continue
            if local_metrics["plain_text_length"] < 3000 or local_metrics["duplicate_sentence_ratio"] >= 0.5:
                item_result["status"] = "blocked_local_quality"
                results.append(item_result)
                continue

            object_key = build_cloudflare_r2_object_key(
                policy=policy,
                category_slug=TARGET_CATEGORY_SLUG,
                post_slug=post["slug"],
                published_at=datetime.now(timezone.utc),
            )
            webp_bytes = _to_webp_bytes(post["source_image"])
            backup_dir = artifact_root / post["slug"]
            backup_dir.mkdir(parents=True, exist_ok=True)
            (backup_dir / f"{post['slug']}.webp").write_bytes(webp_bytes)
            (backup_dir / "article.md").write_text(post["body"].strip() + "\n", encoding="utf-8")
            (backup_dir / "image-prompt.txt").write_text(
                "3x4 panel grid collage, exactly 12 visible panels, visible white gutters, clean grid layout, "
                f"realistic documentary scenes for {post['topic']}, archival evidence, locations, records, "
                "balanced 1024x1024 hero image, no text, no logo, no watermark.",
                encoding="utf-8",
            )

            if mode == "dry-run":
                item_result["status"] = "dry_run_ok"
                item_result["object_key"] = object_key
                results.append(item_result)
                continue

            cover_url, upload_payload, _delivery_meta = upload_binary_to_cloudflare_r2(
                db,
                object_key=object_key,
                filename=f"{post['slug']}.webp",
                content=webp_bytes,
            )
            content = _content_with_hero(cover_url, post["title"], post["body"])
            payload = {
                "title": post["title"],
                "slug": post["slug"],
                "content": content,
                "excerpt": post["excerpt"],
                "seoTitle": post["title"],
                "seoDescription": _normalize_seo_description(post["meta"], fallback=post["excerpt"]),
                "tagNames": post["labels"],
                "coverImage": cover_url,
                "coverAlt": post["title"],
                "status": "published",
                "categoryId": TARGET_CATEGORY_ID,
                "metadata": {
                    "article_pattern_id": post["pattern"],
                    "article_pattern_version": PATTERN_VERSION,
                    "generator": "codex-chat-script",
                    "scope": "cloudflare-mysteria",
                    "hero_image_policy": "single 3x4 panel grid collage source reused from existing archive image",
                },
            }
            existing_slug_post = _find_existing_slug_post(posts, post["slug"])
            existing_post_id = ""
            if existing_slug_post and str(existing_slug_post.get("status") or "").strip().lower() == "draft":
                existing_post_id = str(existing_slug_post.get("id") or "").strip()
            created = _create_or_publish(
                client,
                payload,
                category_id=TARGET_CATEGORY_ID,
                existing_post_id=existing_post_id,
            )
            public_url = str(created.get("publicUrl") or created.get("url") or "").strip()
            if not public_url:
                public_url = f"https://dongriarchive.com/ko/post/{_post_url_slug(post['slug']) or post['slug']}"
            live = _verify_live(public_url, cover_url, timeout=timeout)
            item_result.update(
                {
                    "status": "published" if live["pass"] else "published_audit_failed",
                    "post_id": str(created.get("id") or ""),
                    "public_url": public_url,
                    "hero_image_url": cover_url,
                    "object_key": object_key,
                    "upload": {
                        "bucket": upload_payload.get("bucket"),
                        "object_key": upload_payload.get("object_key"),
                        "public_url": upload_payload.get("public_url"),
                    },
                    "live_verify": live,
                }
            )
            results.append(item_result)

        sync_result: dict[str, Any] | None = None
        if mode == "apply" and any(item.get("status") in {"published", "published_audit_failed"} for item in results):
            sync_result = sync_cloudflare_posts(db, include_non_published=True)
            created_ids = [str(item.get("post_id") or "").strip() for item in results if str(item.get("post_id") or "").strip()]
            if created_ids:
                rows = (
                    db.execute(
                        select(SyncedCloudflarePost).where(SyncedCloudflarePost.remote_post_id.in_(created_ids))
                    )
                    .scalars()
                    .all()
                )
                for row in rows:
                    match = next((item for item in results if item.get("post_id") == row.remote_post_id), None)
                    if not match:
                        continue
                    row.article_pattern_id = str(match.get("article_pattern_id") or "")
                    row.article_pattern_version = PATTERN_VERSION
                    row.render_metadata = {
                        "article_pattern_id": row.article_pattern_id,
                        "article_pattern_version": PATTERN_VERSION,
                        "live_verify": match.get("live_verify") or {},
                        "finalized_after_live_verify": bool((match.get("live_verify") or {}).get("pass")),
                    }
                    row.quality_status = "pass" if bool((match.get("live_verify") or {}).get("pass")) else "audit_failed"
                    db.add(row)
                db.commit()

    summary = {
        "mode": mode,
        "target_category_id": TARGET_CATEGORY_ID,
        "target_category_slug": TARGET_CATEGORY_SLUG,
        "planned": len(POSTS),
        "published": len([item for item in results if item.get("status") == "published"]),
        "failed_or_blocked": len([item for item in results if item.get("status") != "published"]),
        "sync_result": sync_result,
        "artifact_root": str(artifact_root),
        "items": results,
    }
    report_path = artifact_root / "result.json"
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    summary["report_path"] = str(report_path)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish two Codex-authored Cloudflare Mysteria posts.")
    parser.add_argument("--mode", choices=("dry-run", "apply"), default="dry-run")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    result = run(mode=args.mode, timeout=args.timeout)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("failed_or_blocked") == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
