# GitHub 공개 리포 런북

모노레포 루트, PowerShell. 살아 있는 문서와 `LICENSE`가 커밋된 뒤에만 실행한다. `--force` 없음. `master`를 `main`으로 바꾸지 않는다.

1. `git remote -v`가 비어 있는지 확인한다. `origin`이 있으면 **중단**한다. URL을 바꾸지 않는다.
2. `.gitignore`에 `.env`, `packages/web-api/*.db`, `.venv/`, `node_modules/`가 있는지 확인한다.
3. `git status`에 `.env`, `*.db`, 키 파일이 없는지 확인한다.
4. `gh auth status`. 실패하면 `gh auth login` 후 재개한다. `gh`가 없으면 설치하고 중단한다.
5. `$login = gh api user -q .login` 후 리포 이름은 `$login/dart-wrapper`.
6. `gh repo view "$login/dart-wrapper"`가 성공하면 **중단**한다. 이름을 임의로 바꾸어 만들지 않는다.
7. `gh repo create dart-wrapper --public --source=. --remote=origin --description "DART 공시 카탈로그·감사 추출 모노레포"` — **`--push` 없음**. 이어서 `git push -u origin master`.
8. 루트 README 클론 URL이 `https://github.com/$login/dart-wrapper`와 다르면 고쳐서 커밋·푸시한다. 같으면 생략한다.
9. 금지: `--force`, 브랜치 이름 변경, `origin` 교체, `gh repo delete`.
