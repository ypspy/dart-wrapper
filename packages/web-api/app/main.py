"""로컬 앱의 호환 진입점. 새 실행은 app.local:app 를 쓴다."""

from app.local import app, create_local_app as create_app

__all__ = ["app", "create_app"]
