"""단일 기간 감사시간 표에서 합계 칸을 고르는 순수 함수.

unknown을 무조건 당기(current)로 보지 않는다.
가드는 아래 여덟 조건을 모두 만족할 때만 참이다.
가드가 거짓이면 master와 같다.

1. 당기/전기 표시가 없다. 모든 칸의 period가 unknown이고 period_raw가 비어 있다.
2. 기간이 섞여 있지 않다. current 또는 prior 칸이 없다.
3. 역할당 열이 하나다. (role, role_raw, metric) 키가 각각 한 번만 나온다.
4. 역할을 모르는 열이 없다. role이 other인 칸이 하나라도 있으면 거짓이다.
   metric이 other인 행 하나는 합계 칸 선택에 영향이 없어 조건 4에 넣지 않는다.
   같은 역할에서 모르는 지표 행이 둘 이상이면 키가 겹쳐 조건 3으로 거짓이다.
5. 합계 열이 하나다. role이 total인 칸의 role_raw가 2종류 이상이면 거짓이다.
6. 키 값이 문자열이다. role·role_raw·metric·period·period_raw 중 하나라도
   str도 None도 아니면 거짓이다. 0·False·[]는 빈 값으로 보지 않는다.
7. 역할 원문·행 라벨·칸 원문에 기수가 없다. 공백(compact와 같은 \\s)과
   서식 문자(Cf: U+00AD·U+200B–U+200F·U+2060–U+2064·U+FEFF 등)를 지운 뒤
   (제|第)?숫자(기|期)가 하나라도 있으면 거짓이다. 기수가 한 종류여도 거절한다.
8. 역할 원문·행 라벨·칸 원문에 당기/전기가 없다. role_raw·metric_raw·raw에서
   공백과 서식 문자를 지운 뒤 당기 또는 전기가 있으면 거짓이다. 보이는
   당기/전기는 추출기가 이미 기간으로 읽으므로, 이 검사는 서식 문자가 끼어
   추출기가 못 읽은 경우를 잡는다.

한계:

1. colspan으로 역할당 열이 2개인 무라벨 표는 가드가 거짓이다. 당기 합계가
   없으므로 hours_total_missing이다. 어느 열이 당기인지 정할 근거가 없어
   사람 검토로 보내는 것이 의도다.
2. 단일 기간(unknown) 표에서 role_raw가 다른 합계 열 2개는 가드가 거짓이고
   hours_total_missing이다. 골드 키는 (None, None)이다. 어느 열이 당기인지
   근거가 없다. 두 열이 모두 current이면 조건 1로 거짓이고 종전대로
   hours_total_duplicate(skip)이다.
3. 역할을 모르는 열(role이 other)이 있으면 개수와 상관없이 가드가 거짓이고
   hours_total_missing이다.
4. 구조로 구분할 수 없는 남은 경우는 새 서식인데 당기/전기 표시를 하나도
   읽지 못했고, 역할 헤더는 열마다 하나씩 읽힌 표다. 이 표는 옛 서식과
   칸 구조가 같아서 가드가 참이다. 헤더가 아예 없는 6값 열은 키가 겹쳐
   가드가 거짓(missing)이다. 연도 조건은 넣지 않았다. 서식 변경 시점
   (2016년 7–8월경)이 딱 떨어지지 않고, 구조상 단일 기간인 새 fact 2건이
   2017-04 접수다(원문 대조 전). 컷을 넣으면 그런 문서를 잘라낼 수 있다.
   「전기」가 역할 열의 헤더나 값 칸에 있으면 period가 prior가 되어 가드가
   거짓이다. 라벨 열(모서리)에만 있으면 추출기가 그 원문을 period_raw로
   남겨 가드가 거짓이다(한계 7). 「제47기」처럼 기수만 있는 표는 소제목·제목
   행의 기수를 period_raw로 남겨 가드가 거짓이다(한계 5).
5. 소제목·표 안 제목 행의 기수는 추출기가 period_raw로 남겨 가드가
   거짓이다(R20/EXT). 역할 헤더 아래 소제목 행에만 기수가 있고 역할마다
   열이 하나인 표(제47기, 열마다 다른 제48기/제47기/제48기)와 표 안 제목
   행(「제47기 감사참여자 구분별 인원수 및 감사시간」, N50)이 해당한다.
   칸의 role_raw에는 기수가 남지 않고 period는 unknown이다. period_raw에
   기수 원문이 있어 조건 1이 거짓이고 합계를 당기로 쓰지 않는다. R20
   이전에 저장된 v19 fact는 재추출 전까지 종전과 같다. 실측: 골드 원문
   캐시의 옛 서식 249건 중 헤더 행에 제N기가 있는 표는 0건이다(2026-11-17
   8:16 PM CT). 최소 지점은 activity_hours._match_period이다. 당기/전기가
   없을 때 헤더에 제N기가 있으면 ("unknown", 원문)을 돌려 조건 1이
   거절한다. 이렇게 바꿔도 기존 782 테스트는 통과했다(Zucchini 시험, 커밋
   안 함, 2026-11-17). EXTRACTOR_VERSION은 audit_opinion.v19로 유지한다.
   재추출·버전 올림은 별도 승인이다. 후속 후보는 헤더의 제N기 등으로
   기간을 판별할 수 있는지 조사하는 것이다. 원문 헤더 조사가 먼저이고,
   네트워크와 live DB가 필요한 별도 결정이다. 같은 v19 이름 아래
   period_raw가 다른 fact가 섞일 수 있다(희귀 표, 가드만 영향).
6. 역할 원문·행 라벨·칸 원문에 (제|第)?숫자(기|期)가 있으면(「(47기)」,
   「第47期」 포함) 개수와 상관없이 가드가 거짓이고 missing이다. 공백과
   서식 문자(Cf)는 비교 전에 지운다.
7. 라벨 열(모서리)의 당기/전기·기수는 추출기가 period_raw로 남겨 가드가
   거짓이다. 기간 단어(「전기」「당기」)가 모서리에만 있어도 칸의 period는
   unknown이고 period_raw에 그 원문이 남아 조건 1이 거짓이다. 합계를
   당기로 쓰지 않는다. 저장된 v19 fact는 재추출 전까지 종전이다. 박스
   실측: 골드 원문 캐시 443건 중 모서리에 당기/전기가 있는 표 0건
   (2026-11-18). 모서리 「전기」 표 뒤에 비교표가 있어도 추출기는 첫 표만
   반환한다. 첫 표 칸의 period_raw가 「전기」라 가드가 거짓이다(N47).
8. 투입인원수 표가 여러 개면 추출기는 첫 표만 반환하고, 표 밖 캡션의 기간
   표시는 칸에 없다. 첫 표가 단일 기간 구조면 가드가 참이다. 한계 4의 한
   형태이고 추출기 동작이다. 모서리가 「구분」인 첫 표 뒤에 비교표가 있으면
   첫 표 합계(예: 80)가 당기로 쓰인다(N48). 추출기 복수 표 처리가 필요한
   별도 사안이다.
9. 기간처럼 보이는 행 라벨은 보수적으로 거절한다. 「※ 제47기 기준」
   「12기간 누적」(12기), 「전기간」(전기), 「해당 기간」(당기)이 행 라벨에
   있으면 감사 합계가 있어도 가드가 거짓이고 missing이다(master와 같음).
   예외 규칙은 다른 모호함을 만들고 박스 실측(골드 446건)에 0건이라 두지
   않는다(N42).

다음은 추출기 동작이라 가드와 무관하게 master와 같은 missing이다. 첫 헤더
행이 기수뿐이면 모든 열이 role other(N43), 「기타」 열·잎 없는 「감사업무
담당 회계사」 열은 role other(N44, 한계 3), 행 라벨 「감사시간」은 metric
other라 감사 키가 없음(N45. 가드는 참이라 골드 키는 (None, 인원)이고 신호는
missing). 고치려면 추출기 후속(PR15-EXT)이다.

r5 확장 조건: 골드 스냅샷 446건에서 판정 변화 0건, 넓은 기수·행 라벨 당기/전기
0건(박스 사본, 2026-11-18). live 카탈로그의 metric_raw·raw는 재지 않았다.
r6: 골드 스냅샷 446건의 role_raw·metric_raw·raw·period_raw와 골드 원문 캐시
443건의 헤더에서 서식 문자(Cf) 0건, 숨은 당기/전기 0건, r5→r6 판정 변화
0건(박스 사본, 2026-11-18). live 카탈로그는 재지 않았다.
"""

from __future__ import annotations

import re
import unicodedata

# 추출기 compact와 같은 공백 패턴. 비교 전에 이것과 서식 문자(Cf)를 지운다.
# Cf에는 U+00AD·U+200B–U+200F·U+2060–U+2064·U+FEFF가 들어간다.
# \d는 전각 숫자도 잡는다.
_SPACE = re.compile(r"\s+")
_FISCAL_MARK = re.compile(r"(?:제|第)?\d+(?:기|期)")
_PERIOD_WORD = re.compile(r"당기|전기")


def _plain(value: object) -> str:
    """비교 전에 공백(compact와 같음)과 서식 문자(Cf)를 지운다. 문자열이 아니면 빈 문자열이다."""
    if not isinstance(value, str):
        return ""
    return "".join(ch for ch in _SPACE.sub("", value) if unicodedata.category(ch) != "Cf")


def is_single_period_hours(hours: object) -> bool:
    """단일 기간 표인지 본다.

    unknown을 무조건 current로 보지 않는다.
    리스트이고 dict 칸이 하나 이상이며, 가드 여덟 조건을 모두 만족할 때만 True다.
    가드가 거짓이면 master와 같다.
    """
    if not isinstance(hours, list) or not hours:
        return False
    keys: list[tuple[object, object, object]] = []
    total_raws: set[object] = set()
    for item in hours:
        if not isinstance(item, dict):
            return False
        period = item.get("period")
        period_raw = item.get("period_raw")
        # 6. 기간 값도 문자열. 0·False·[]를 빈 값으로 보기 전에 확인한다.
        if not all(isinstance(value, str) or value is None for value in (period, period_raw)):
            return False
        period_raw = period_raw or ""
        # 2. 섞임 없음. current·prior가 있으면 단일 기간이 아니다.
        if period in {"current", "prior"}:
            return False
        # 1. 당기/전기 표시 없음. unknown이 아니거나 기간 원문이 있으면 거절한다.
        if period != "unknown" or period_raw != "":
            return False
        role = item.get("role")
        role_raw = item.get("role_raw")
        metric = item.get("metric")
        # 6. 키 값이 문자열. set 비교 전에 확인해 TypeError를 막는다.
        if not all(isinstance(value, str) or value is None for value in (role, role_raw, metric)):
            return False
        metric_raw = item.get("metric_raw")
        raw = item.get("raw")
        # 7. 역할 원문·행 라벨·칸 원문의 기수. 한 종류여도 거절한다.
        #    숫자가 없는 「기」(분·반기검토, 현장감사수행시기)는 거절하지 않는다.
        if any(_FISCAL_MARK.search(_plain(value)) for value in (role_raw, metric_raw, raw)):
            return False
        # 8. 역할 원문·행 라벨·칸 원문의 당기/전기. 추출기가 못 본 숨은 문자 변형도 잡는다.
        if any(_PERIOD_WORD.search(_plain(value)) for value in (role_raw, metric_raw, raw)):
            return False
        # 4. 역할을 모르는 열. unmapped가 아니라 role로 판단한다.
        if role == "other":
            return False
        # 5. 합계 열의 role_raw는 한 종류여야 한다.
        if role == "total":
            total_raws.add(role_raw)
        keys.append((role, role_raw, metric))
    if len(total_raws) > 1:
        return False
    # 3. 역할당 열 1개. colspan 복제는 같은 키가 두 번 나온다.
    return len(keys) == len(set(keys))


def total_cells(hours: object, metric: str) -> list[dict[str, object]] | None:
    """합계 칸을 고른다.

    리스트가 아니면 None이다.
    가드가 참이면 role이 total이고 metric이 일치하며 period가 unknown인 칸을 돌려준다.
    가드가 거짓이면 지금처럼 period가 current인 칸만 돌려준다.
    unknown을 무조건 current로 보지 않는다.
    """
    if not isinstance(hours, list):
        return None
    period = "unknown" if is_single_period_hours(hours) else "current"
    cells: list[dict[str, object]] = []
    for item in hours:
        if not isinstance(item, dict):
            continue
        if (
            item.get("role") == "total"
            and item.get("metric") == metric
            and item.get("period") == period
        ):
            cells.append(item)
    return cells
