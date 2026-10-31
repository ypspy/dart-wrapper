"""연구 화면 템플릿 로더. 연구 템플릿을 먼저 보고, 없으면 web-api 기본 템플릿을 본다."""

from __future__ import annotations

from pathlib import Path

import app as web_api_app
from fastapi.templating import Jinja2Templates
from jinja2 import ChoiceLoader, Environment, FileSystemLoader

RESEARCH_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
WEB_API_TEMPLATES_DIR = Path(web_api_app.__file__).resolve().parent / "templates"


def create_templates() -> Jinja2Templates:
    """연구 템플릿 → web-api 템플릿 순서로 찾는 Jinja2Templates를 만든다.

    연구 템플릿이 `admin/base.html`, `catalog/base.html`을 상속하므로 두 디렉터리가 모두 필요하다.
    """
    environment = Environment(
        loader=ChoiceLoader(
            [
                FileSystemLoader(str(RESEARCH_TEMPLATES_DIR)),
                FileSystemLoader(str(WEB_API_TEMPLATES_DIR)),
            ]
        ),
        autoescape=True,
    )
    return Jinja2Templates(env=environment)
