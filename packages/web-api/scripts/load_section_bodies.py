"""감리결과 섹션 본문을 dart_sections.db에 넣는다.

packages/web-api 에서 저장소 venv로 실행한다.

    .\\.venv\\Scripts\\python.exe scripts\\load_section_bodies.py

카탈로그(dart_catalog.db)는 읽기만 한다. 본문 DB는 커밋하지 않는다.
시카고 00:00–04:59에는 시작하지 않고, 실행 중 그 시각이 되면 저장 후 멈춘다.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.sections.load import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
