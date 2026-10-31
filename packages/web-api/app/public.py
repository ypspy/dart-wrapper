"""공개 카탈로그·Viewer 진입점."""

from app.apps import create_public_app, require_postgres_url
from app.config import get_settings

_settings = get_settings()
require_postgres_url(_settings.database_url)
app = create_public_app(_settings)
