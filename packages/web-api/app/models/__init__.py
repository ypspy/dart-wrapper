"""SQLAlchemy 모델 패키지.

서브모듈을 직접 import한다. 패키지 import 시 연구 전용 모델을 불러오지 않는다.
"""

from app.models.base import Base

__all__ = ["Base"]
