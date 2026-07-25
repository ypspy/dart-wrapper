# dart-wrapper

DART 공시 소스를 **재가공해 제공**하기 위한 모노레포입니다.

원문 HTML/PDF는 장기 저장하지 않고, 추출한 **entry(메타·주소)** 를 저장한 뒤 필요할 때 소스를 가져와 변환·제공합니다.

## 구조

```text
dart-wrapper/
└── packages/
    ├── entry-extractor/   # 공시 컨테이너 → 구성 문서 leaf entry 추출 (Node)
    └── web-api/           # Admin 카탈로그 수집 + Public Viewer API (FastAPI)
```

## 현재 모듈

| 패키지 | 역할 |
|--------|------|
| [`@dart-wrapper/entry-extractor`](./packages/entry-extractor) | 목록·목차 파싱 후 저장용 flat entry 생성 |
| [`web-api`](./packages/web-api) | Admin 수집 트리거·현황 및 Viewer 원문 정제 API |

## 설치

루트에서 한 번 설치하면 workspace 패키지 의존성이 함께 잡힙니다.

```bash
npm install
```

## 예제

```bash
npm run example
npm run example:entries
```

또는 패키지 폴더에서:

```bash
cd packages/entry-extractor
npm run example:entries
```
