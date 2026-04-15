# `git-cleaner`

**GitHub 팔로워/팔로잉 목록을 자동으로 관리해주는 CLI 도구.**

[English](./README.md) · [한국어](./README.ko.md)

> 팁: `git-cleaner` 가 `PATH` 에 올라가 있으면 git 이 이를 서브커맨드로 인식합니다 — `git-cleaner run` 과 `git cleaner run` 둘 다 동일하게 동작합니다.

---

## 주요 기능

1. **자동 정리** — 나를 맞팔하지 않는 사람 언팔로우
2. **자동 맞팔** — 나를 팔로우한 사람 자동으로 맞팔
3. **Discover (친구의 친구)** — 내가 팔로우하는 사람들이 공통으로 팔로우하는 유저를 찾아 자동 팔로우
4. **예외 목록 (exceptions)** — 언팔로우 대상에서 영구 제외할 유저
5. **블랙리스트 (blacklist)** — 절대 팔로우하지 않을 유저
6. **Dry-run 모드** — 실제 반영 전 변경 내역 미리보기
7. **Rate limit 보호** — 대량 스캔 전에 API 사용 가능량을 먼저 확인
8. **다국어 UI** — 모든 명령어 출력이 영어/한국어로 제공됨 (`git-cleaner lang en|ko`)

---

## 설치

### Homebrew (권장)

```bash
brew tap jamkris/git-cleaner
brew install git-cleaner
```

### 수동 설치

```bash
git clone https://github.com/Jamkris/git-cleaner.git
cd git-cleaner
chmod +x git-cleaner
sudo cp git-cleaner /usr/local/bin/
```

---

## 초기 설정

처음 한 번만 아래 명령으로 인증 정보를 저장하면 됩니다:

```bash
git-cleaner setup
```

다음 작업이 자동으로 수행됩니다:

- UI 언어 선택 (English / 한국어)
- Python 의존성(`requests`) 설치
- GitHub 사용자명 입력
- GitHub **Personal Access Token (classic)** 입력 — `user:follow` 권한 필요

> 토큰 발급 경로: <https://github.com/settings/tokens> → *Generate new token (classic)* → `user:follow` 체크

인증 정보는 `~/.config/git-cleaner/keys.txt` 에 `0600` 권한으로 저장됩니다.

---

## 사용법

### `git-cleaner run` — 맞팔 동기화

```bash
git-cleaner run
```

- 나를 팔로우하는 사람을 **맞팔** (blacklist 에 있으면 제외)
- 맞팔하지 않는 사람을 **언팔로우** (exceptions 에 있으면 제외)

### `git-cleaner discover` — 친구의 친구 찾기

```bash
git-cleaner discover --dry-run
```

내가 팔로우하는 모든 유저의 `following` 목록을 스캔해서, `--min-overlap` 값 이상 겹치는 후보를 찾아줍니다. **처음에는 반드시 `--dry-run`** 으로 미리보기부터 하세요.

**옵션**

| 플래그 | 기본값 | 설명 |
|---|---|---|
| `--min-overlap N` | `2` | 후보가 최소 몇 명의 "내 팔로잉" 에게 팔로우되어야 하는지 |
| `--max-follows N` | `20` | 한 번 실행 시 최대로 팔로우할 유저 수 |
| `--dry-run` | off | 실제 팔로우 없이 후보만 출력 |

**예시**

```bash
# 더 엄격하게 — 내 팔로잉 중 3명 이상이 공통으로 팔로우하는 유저만 미리보기
git-cleaner discover --min-overlap 3 --dry-run

# 확인 후 실제 실행 (최대 10명까지)
git-cleaner discover --min-overlap 3 --max-follows 10
```

**출력 예시**

```
Fetching your following list...
Rate limit remaining: 4932
Scanning following lists of 48 users (this may take a moment)...
  [1/48] alice
  [2/48] bob
  ...

=== Discover candidates (min-overlap=2, showing top 20) ===
   7x overlap  torvalds
   5x overlap  gaearon
   4x overlap  tj
   ...
```

블랙리스트 유저와 이미 내가 팔로우 중인 유저는 자동으로 제외됩니다.

### `git-cleaner -e <usernames...>` — exceptions 추가

```bash
git-cleaner -e username1 username2 username3
```

`exceptions` 에 등록된 유저는 `git-cleaner run` 에서 **절대 언팔로우되지 않습니다**.

### `git-cleaner -b <usernames...>` — blacklist 추가

```bash
git-cleaner -b spammer1 spammer2
```

`blacklist` 에 등록된 유저는 `git-cleaner run` / `git-cleaner discover` 에서 **절대 팔로우되지 않습니다**.

### `git-cleaner lang` — UI 언어 전환

```bash
git-cleaner lang          # 현재 언어 표시
git-cleaner lang ko       # 한국어로 전환
git-cleaner lang en       # 영어로 전환
```

모든 출력 메시지가 번역되어 있습니다. 선택한 언어는 `~/.config/git-cleaner/config.txt` 에 저장됩니다. 한 번만 다른 언어로 실행하려면 환경변수를 사용하세요:

```bash
GIT_CLEANER_LANG=ko git-cleaner discover --dry-run
```

환경변수가 설정되어 있으면 config 파일보다 우선합니다.

### `git-cleaner view` — 현재 목록 확인

```bash
git-cleaner view
```

현재 `exceptions`, `blacklist` 를 번호와 함께 출력합니다.

### `git-cleaner -h` — 도움말

```bash
git-cleaner -h
```

---

## `discover` 의 동작 원리

GitHub 홈 화면의 "Who people are following" 피드는 공개 API 로 접근할 수 없습니다 (관련 `FollowEvent` 는 오래 전 deprecated 됨). 그래서 `discover` 는 팔로우 관계를 직접 크롤링하는 방식으로 같은 결과를 근사합니다:

```
내가 팔로우하는 각 유저 X 에 대해:
    X 의 `following` 목록을 가져옴
    목록 내 각 후보 Y 에 대해:
        Y 가 나 자신이 아니고
        Y 를 내가 이미 팔로우하지 않고
        Y 가 블랙리스트에 없으면:
            counter[Y] += 1

counter[Y] >= min_overlap 인 후보만 유지
겹침 횟수 내림차순으로 정렬 → 상위 max_follows 선택
```

`--min-overlap` 이 높을수록 "사회적 검증" 신호가 강해지고, 스팸 계정이 걸러질 확률이 올라갑니다.

---

## Rate limit

인증된 GitHub API 는 시간당 **5000회** 로 제한됩니다. `discover` 는 대략 `2 × (내 팔로잉 수) + max_follows` 정도의 요청을 사용합니다. 실행 전에 `/rate_limit` 엔드포인트로 사용 가능량을 확인하며, 부족하면 조용히 할당량을 소진하지 않고 즉시 중단합니다.

---

## 설정 파일

모두 `~/.config/git-cleaner/` 에 저장됩니다 (`$XDG_CONFIG_HOME` 존중):

| 파일 | 용도 |
|---|---|
| `keys.txt` | GitHub 사용자명 + Personal Access Token (`0600`) |
| `exceptions.txt` | 한 줄에 한 명 — 자동 언팔 대상에서 제외 |
| `blacklist.txt` | 한 줄에 한 명 — 자동 팔로우 대상에서 제외 |
| `config.txt` | key=value 형태의 설정 (현재 지원: `lang=en` 또는 `lang=ko`) |

환경 변수가 설정되어 있으면 파일 값을 덮어씁니다:

- `GIT_CLEANER_USERNAME`
- `GITHUB_TOKEN` (또는 `GIT_CLEANER_TOKEN`)
- `GIT_CLEANER_LANG` (`en` 또는 `ko`) — `config.txt` 보다 우선

---

## 요구 사항

- **Python 3.10+** (모던 타입 힌트 사용)
- `requests` 라이브러리 (`git-cleaner setup` 실행 시 자동 설치)
- GitHub **Personal Access Token (classic)** — `user:follow` 권한 필수

---

## 안전 수칙

- `git-cleaner discover` 는 항상 `--dry-run` 으로 먼저 확인하세요.
- `--max-follows` 값을 너무 크게 잡으면 GitHub 의 어뷰징 방지 정책에 걸릴 수 있습니다.
- `keys.txt` 는 **절대로 커밋하지 마세요** — 개인 토큰이 평문으로 들어 있습니다.

---

## 라이선스

MIT — [LICENSE](./LICENSE) 참고. Copyright © 2026 Jamkris \<contact@jamkris.com\>.
