"""골드 검수 화면. 블라인드에서는 추출값을 템플릿에 넘기지 않는다."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings
from research.api.admin.reviews import _has_valid_token
from research.api.deps import get_research_settings_dep, get_settings_dep
from research.config import ResearchSettings
from research.extracting.constants import EXTRACTOR_VERSION
from research.extracting.field_bundles import BUNDLE_KEYS, DART_DOCUMENT_VIEW
from research.gold.cache import load_section_html
from research.gold.db import migrate, open_gold
from research.gold.evidence import annotate_cells, evidence_for
from research.gold.labels import complete_doc, exclude_doc, next_doc, save_label
from research.gold.scoring import metrics
from research.gold.snapshots import load_snapshot
from research.gold.subjects import TABLE_BUNDLES, extract_predicted, subjects_for
from research.templating import create_templates

templates = create_templates()
router = APIRouter(prefix="/admin/gold", tags=["Admin Gold"], include_in_schema=False)


class LabelBody(BaseModel):
    """라벨 저장 요청."""

    model_config = ConfigDict(populate_by_name=True)

    rcept_no: str
    dcm_no: str
    bundle: str
    subject: str
    pass_: str = Field(alias="pass")
    verdict: str
    gold_value: Any = None
    shown_value: Any = None
    shown_version: str | None = None
    evidence: Any = None
    error_tag: str | None = None
    note: str = ""
    seconds: int | None = None
    bulk_accept: bool = False


def _catalog_path(settings: Settings) -> Path | None:
    """web-api DB URL에서 카탈로그 파일 경로를 읽는다."""
    marker = ":///"
    if marker not in settings.database_url:
        return None
    raw = settings.database_url.split(marker, 1)[1].split("?", 1)[0]
    if not raw or raw == ":memory:":
        return None
    return Path(raw)


def get_gold_conn(
    settings: Settings = Depends(get_settings_dep),
    research_settings: ResearchSettings = Depends(get_research_settings_dep),
):
    """gold.db를 열고 카탈로그는 파일이 있을 때만 읽기 전용으로 붙인다."""
    catalog = _catalog_path(settings)
    catalog_path = catalog if catalog is not None and catalog.is_file() else None
    conn = open_gold(Path(research_settings.gold_db_path), catalog_path)
    try:
        migrate(conn)
        yield conn
    finally:
        conn.close()


def _redirect_token() -> RedirectResponse:
    """토큰 화면으로 보낸다."""
    return RedirectResponse("/admin/token", status_code=303)


def _group(bundle: str) -> str:
    """키보드 그룹. 기본, 표, 계정."""
    if bundle in TABLE_BUNDLES:
        return "table"
    if bundle == "accounts":
        return "accounts"
    return "basic"


def _display(value: Any) -> str:
    """화면에 그대로 보여줄 추출값."""
    if value is None:
        return ""
    if isinstance(value, dict):
        raw = value.get("raw")
        if raw not in (None, ""):
            return str(raw)
    return str(value)


def _sample(
    conn: sqlite3.Connection, run_id: str, rcept_no: str, dcm_no: str
) -> sqlite3.Row | None:
    """실행 안의 표본 한 행."""
    return conn.execute(
        """
        SELECT * FROM gold_samples
        WHERE run_id = ? AND rcept_no = ? AND dcm_no = ?
        """,
        (run_id, rcept_no, dcm_no),
    ).fetchone()


def _saved_verdicts(
    conn: sqlite3.Connection, rcept_no: str, dcm_no: str, pass_mode: str
) -> dict[tuple[str, str], str]:
    """이미 저장한 판정."""
    rows = conn.execute(
        """
        SELECT bundle, subject, verdict FROM gold_labels
        WHERE rcept_no = ? AND dcm_no = ? AND pass = ?
        """,
        (rcept_no, dcm_no, pass_mode),
    ).fetchall()
    return {(row["bundle"], row["subject"]): row["verdict"] for row in rows}


def _field_rows(
    snapshot: dict[str, Any] | None,
    *,
    show_values: bool,
    saved: dict[tuple[str, str], str],
) -> list[dict[str, str]]:
    """필드 행. 블라인드면 display 키 자체를 만들지 않는다."""
    rows: list[dict[str, str]] = []
    for bundle in BUNDLE_KEYS:
        for subject in subjects_for(bundle):
            item = {
                "bundle": bundle,
                "subject": subject,
                "group": _group(bundle),
                "verdict": saved.get((bundle, subject), ""),
            }
            if show_values:
                predicted = extract_predicted(snapshot or {}, bundle, subject)
                item["display"] = _display(predicted)
            rows.append(item)
    return rows


@router.get("", response_class=HTMLResponse, response_model=None)
def dashboard(
    request: Request,
    conn: sqlite3.Connection = Depends(get_gold_conn),
    settings: Settings = Depends(get_settings_dep),
    research_settings: ResearchSettings = Depends(get_research_settings_dep),
) -> HTMLResponse | RedirectResponse:
    """기간별 진행."""
    if not _has_valid_token(request, settings):
        return _redirect_token()
    run_id = research_settings.gold_run_id
    counts = conn.execute(
        """
        SELECT period,
               SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done_n,
               SUM(CASE WHEN role = 'main' THEN 1 ELSE 0 END) AS main_n
        FROM gold_samples
        WHERE run_id = ?
        GROUP BY period
        ORDER BY period
        """,
        (run_id,),
    ).fetchall()
    return templates.TemplateResponse(
        request,
        "admin/gold/dashboard.html",
        {"run_id": run_id, "counts": counts},
    )


@router.get("/next", response_model=None)
def go_next(
    request: Request,
    period: str = "P7",
    pass_mode: str = Query(default="prefill", alias="pass"),
    conn: sqlite3.Connection = Depends(get_gold_conn),
    settings: Settings = Depends(get_settings_dep),
    research_settings: ResearchSettings = Depends(get_research_settings_dep),
) -> RedirectResponse:
    """다음 문서로 보낸다."""
    if not _has_valid_token(request, settings):
        return _redirect_token()
    found = next_doc(conn, research_settings.gold_run_id, period, pass_mode)
    if found is None:
        return RedirectResponse(f"/admin/gold?period={period}", status_code=303)
    return RedirectResponse(
        f"/admin/gold/doc/{found[0]}/{found[1]}?pass={pass_mode}",
        status_code=303,
    )


@router.get(
    "/doc/{rcept_no}/{dcm_no}", response_class=HTMLResponse, response_model=None
)
def document(
    rcept_no: str,
    dcm_no: str,
    request: Request,
    pass_mode: str = Query(default="prefill", alias="pass"),
    conn: sqlite3.Connection = Depends(get_gold_conn),
    settings: Settings = Depends(get_settings_dep),
    research_settings: ResearchSettings = Depends(get_research_settings_dep),
) -> HTMLResponse | RedirectResponse:
    """문서 한 건. 블라인드는 추출값을 컨텍스트에 넣지 않는다."""
    if not _has_valid_token(request, settings):
        return _redirect_token()
    sample = _sample(conn, research_settings.gold_run_id, rcept_no, dcm_no)
    if sample is None:
        return HTMLResponse("표본에 없는 문서입니다.", status_code=404)
    meta = json.loads(sample["meta"] or "{}")
    blind = pass_mode == "blind"
    snapshot = None
    if not blind:
        snapshot = load_snapshot(conn, EXTRACTOR_VERSION, rcept_no, dcm_no)
    rows = _field_rows(
        snapshot,
        show_values=not blind,
        saved=_saved_verdicts(conn, rcept_no, dcm_no, pass_mode),
    )
    dart_url = DART_DOCUMENT_VIEW.format(rcept_no=rcept_no, dcm_no=dcm_no)
    return templates.TemplateResponse(
        request,
        "admin/gold/doc.html",
        {
            "sample": sample,
            "rows": rows,
            "pass_mode": pass_mode,
            "blind": blind,
            "dart_url": dart_url,
            "overlap": (not blind) and bool(meta.get("in_extraction_reviews")),
            "highlight": "0" if blind else "1",
            "bulk_accept": "0" if blind else "1",
        },
    )


@router.get(
    "/evidence/{rcept_no}/{dcm_no}/{bundle}",
    response_class=HTMLResponse,
    response_model=None,
)
def evidence(
    rcept_no: str,
    dcm_no: str,
    bundle: str,
    request: Request,
    pass_mode: str = Query(default="prefill", alias="pass"),
    conn: sqlite3.Connection = Depends(get_gold_conn),
    settings: Settings = Depends(get_settings_dep),
    research_settings: ResearchSettings = Depends(get_research_settings_dep),
) -> HTMLResponse | RedirectResponse:
    """근거 HTML. 캐시가 없으면 DART 링크만 보여 준다."""
    if not _has_valid_token(request, settings):
        return _redirect_token()
    snapshot = load_snapshot(conn, EXTRACTOR_VERSION, rcept_no, dcm_no) or {
        "rcept_no": rcept_no,
        "dcm_no": dcm_no,
    }
    found = evidence_for(conn, snapshot, bundle)
    link = DART_DOCUMENT_VIEW.format(rcept_no=rcept_no, dcm_no=dcm_no)
    section_html = ""
    ele_id = ""
    if found:
        link = found[0].viewer_url or found[0].dart_url or link
        ele_id = found[0].ele_id
    if pass_mode != "blind":
        cached = load_section_html(
            Path(research_settings.gold_cache_root),
            rcept_no,
            {"ele_id": ele_id},
        )
        if cached:
            section_html = annotate_cells(cached)
    return templates.TemplateResponse(
        request,
        "admin/gold/partials/evidence.html",
        {"link": link, "section_html": section_html, "bundle": bundle},
    )


@router.post("/label", response_model=None)
def post_label(
    body: LabelBody,
    request: Request,
    conn: sqlite3.Connection = Depends(get_gold_conn),
    settings: Settings = Depends(get_settings_dep),
) -> JSONResponse | RedirectResponse:
    """라벨 한 건을 저장한다."""
    if not _has_valid_token(request, settings):
        return _redirect_token()
    note = body.note or ""
    if body.bulk_accept and "bulk_accept" not in note:
        note = f"{note} bulk_accept".strip()
    save_label(
        conn,
        rcept_no=body.rcept_no,
        dcm_no=body.dcm_no,
        bundle=body.bundle,
        subject=body.subject,
        pass_=body.pass_,
        verdict=body.verdict,
        gold_value=body.gold_value,
        shown_value=body.shown_value,
        shown_version=body.shown_version,
        evidence=body.evidence,
        error_tag=body.error_tag,
        note=note,
        seconds=body.seconds,
    )
    return JSONResponse({"ok": True})


@router.post("/doc/{rcept_no}/{dcm_no}/complete", response_model=None)
def post_complete(
    rcept_no: str,
    dcm_no: str,
    request: Request,
    pass_mode: str = Query(default="prefill", alias="pass"),
    conn: sqlite3.Connection = Depends(get_gold_conn),
    settings: Settings = Depends(get_settings_dep),
    research_settings: ResearchSettings = Depends(get_research_settings_dep),
) -> JSONResponse | RedirectResponse:
    """문서를 완료한다."""
    if not _has_valid_token(request, settings):
        return _redirect_token()
    try:
        complete_doc(conn, research_settings.gold_run_id, rcept_no, dcm_no, pass_mode)
    except ValueError as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)
    return JSONResponse({"ok": True})


@router.post("/doc/{rcept_no}/{dcm_no}/exclude", response_model=None)
def post_exclude(
    rcept_no: str,
    dcm_no: str,
    request: Request,
    reason: str = "",
    conn: sqlite3.Connection = Depends(get_gold_conn),
    settings: Settings = Depends(get_settings_dep),
    research_settings: ResearchSettings = Depends(get_research_settings_dep),
) -> JSONResponse | RedirectResponse:
    """문서를 제외하고 예비분을 올린다."""
    if not _has_valid_token(request, settings):
        return _redirect_token()
    promoted = exclude_doc(
        conn,
        research_settings.gold_run_id,
        rcept_no,
        dcm_no,
        reason or "범위 밖",
    )
    return JSONResponse(
        {
            "ok": True,
            "promoted": list(promoted) if promoted else None,
        }
    )


@router.get("/metrics", response_class=HTMLResponse, response_model=None)
def metrics_page(
    request: Request,
    version: str = EXTRACTOR_VERSION,
    conn: sqlite3.Connection = Depends(get_gold_conn),
    settings: Settings = Depends(get_settings_dep),
    research_settings: ResearchSettings = Depends(get_research_settings_dep),
) -> HTMLResponse | RedirectResponse:
    """기간·풀링 정밀도."""
    if not _has_valid_token(request, settings):
        return _redirect_token()
    rows = metrics(conn, research_settings.gold_run_id, version)
    return templates.TemplateResponse(
        request,
        "admin/gold/metrics.html",
        {"rows": rows, "version": version},
    )
