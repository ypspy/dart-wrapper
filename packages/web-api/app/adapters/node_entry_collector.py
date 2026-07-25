"""Node @dart-wrapper/entry-extractor를 서브프로세스로 호출하는 수집 어댑터."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from app.errors import SourceFetchError
from app.ports.entry_collector import CollectRequest
from app.schemas.entry import EntryRecord

logger = logging.getLogger(__name__)


class NodeEntryCollector:
    """CLI 브릿지 스크립트를 실행해 엔트리 JSON을 받아온다.

    stdout은 엔트리 배열 JSON 전용이고, 진행 로그는 stderr로 들어온다.
    """

    def __init__(
        self,
        node_executable: str,
        script_path: Path,
        timeout_seconds: int = 900,
    ) -> None:
        self._node_executable = node_executable
        self._script_path = Path(script_path)
        self._timeout_seconds = timeout_seconds

    async def collect(self, request: CollectRequest) -> list[EntryRecord]:
        """수집 스크립트를 실행하고 엔트리 목록으로 변환한다.

        :raises SourceFetchError: 프로세스 실패, 시간 초과, 출력 파싱 실패
        """
        payload = json.dumps(request.model_dump(), ensure_ascii=False)
        process = await asyncio.create_subprocess_exec(
            self._node_executable,
            str(self._script_path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(payload.encode("utf-8")),
                timeout=self._timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            process.kill()
            raise SourceFetchError(
                f"엔트리 수집이 {self._timeout_seconds}초 안에 끝나지 않아 중단했습니다."
            ) from exc

        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        if stderr_text:
            logger.info("수집기 진행 로그: %s", stderr_text)

        if process.returncode != 0:
            raise SourceFetchError(
                f"엔트리 수집 프로세스가 비정상 종료했습니다(코드 {process.returncode}): "
                f"{stderr_text or '추가 정보 없음'}"
            )

        try:
            raw_entries = json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SourceFetchError(f"수집 결과 JSON을 해석하지 못했습니다: {exc}") from exc

        records = [EntryRecord.model_validate(item) for item in raw_entries]
        if request.corp_code:
            # 상세검색 목록은 기업 필터를 지원하지 않아 수집 후 걸러낸다.
            records = [record for record in records if record.corp_code == request.corp_code]
        return records
