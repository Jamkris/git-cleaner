import argparse
import os
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

TIMEOUT = 15
PER_PAGE = 100
DEFAULT_CONCURRENCY = 10


def get_config_dir() -> Path:
    return Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config")) / "git-cleaner"


CONFIG_DIR = get_config_dir()
KEYS_FILE = CONFIG_DIR / "keys.txt"
EXCEPTIONS_FILE = CONFIG_DIR / "exceptions.txt"
BLACKLIST_FILE = CONFIG_DIR / "blacklist.txt"
CONFIG_FILE = CONFIG_DIR / "config.txt"


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    for p in (KEYS_FILE, EXCEPTIONS_FILE, BLACKLIST_FILE):
        if not p.exists():
            p.touch()


def read_config() -> dict[str, str]:
    cfg: dict[str, str] = {}
    if not CONFIG_FILE.exists():
        return cfg
    with CONFIG_FILE.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip().lower()] = v.strip()
    return cfg


def resolve_lang() -> str:
    env_lang = os.getenv("GIT_CLEANER_LANG", "").strip().lower()
    if env_lang in ("en", "ko"):
        return env_lang
    file_lang = read_config().get("lang", "").lower()
    if file_lang in ("en", "ko"):
        return file_lang
    return "en"


MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "missing_keys": "Missing GitHub username or token. Run: git-cleaner setup (or create keys at {path})",
        "api_error": "API Error on {url}: {status}",
        "rate_limit_warn": "Warning: could not check rate limit ({status}). Proceeding.",
        "rate_limit_remaining": "Rate limit remaining: {remaining}",
        "rate_limit_low": "Not enough rate limit budget (need ~{required}, have {remaining}). Aborting.",
        "fetching_following": "Fetching your following list...",
        "no_following": "You aren't following anyone. Nothing to discover.",
        "scanning": "Scanning following lists of {n} users (this may take a moment)...",
        "scanning_user": "  [{i}/{total}] {user}",
        "no_candidates": "\nNo candidates found (min-overlap={min_overlap}).",
        "candidates_header": "\n=== Discover candidates (min-overlap={min_overlap}, showing top {n}) ===",
        "candidate_row": "  {count:>3}x overlap  {name}",
        "dry_run_skip": "\n[dry-run] Skipping actual follow.",
        "following_n": "\n*** Following {n} users... ***\n",
        "followed": "Followed: {name}",
        "follow_failed": "*** Failed to follow {name}, Status Code: {status} ***",
        "unfollowing_header": "\n*** Unfollowing... ***\n",
        "unfollowed": "Unfollowed: {name}",
        "unfollow_failed": "*** Failed to unfollow {name}, Status Code: {status} ***",
        "no_unfollow": "\nNo one to unfollow!\n",
        "following_header": "\n*** Following... ***\n",
        "no_follow": "\nNo one to follow!\n",
    },
    "ko": {
        "missing_keys": "GitHub 사용자명 또는 토큰을 찾을 수 없습니다. `git-cleaner setup` 을 실행하세요 ({path} 에 직접 생성해도 됩니다)",
        "api_error": "API 오류 — {url}: {status}",
        "rate_limit_warn": "경고: rate limit 확인에 실패했습니다 ({status}). 그대로 진행합니다.",
        "rate_limit_remaining": "남은 rate limit: {remaining}",
        "rate_limit_low": "rate limit 예산이 부족합니다 (필요: 약 {required}, 현재: {remaining}). 중단합니다.",
        "fetching_following": "내 팔로잉 목록을 가져오는 중...",
        "no_following": "팔로우 중인 사람이 없습니다. 수행할 작업이 없습니다.",
        "scanning": "{n}명의 팔로잉 목록을 스캔 중입니다 (시간이 다소 걸릴 수 있습니다)...",
        "scanning_user": "  [{i}/{total}] {user}",
        "no_candidates": "\n조건에 맞는 후보가 없습니다 (min-overlap={min_overlap}).",
        "candidates_header": "\n=== Discover 후보 (min-overlap={min_overlap}, 상위 {n}명) ===",
        "candidate_row": "  {count:>3}회 겹침  {name}",
        "dry_run_skip": "\n[dry-run] 실제 팔로우는 건너뜁니다.",
        "following_n": "\n*** {n}명을 팔로우합니다... ***\n",
        "followed": "팔로우 완료: {name}",
        "follow_failed": "*** 팔로우 실패 — {name}, 상태 코드: {status} ***",
        "unfollowing_header": "\n*** 언팔로우 중... ***\n",
        "unfollowed": "언팔로우 완료: {name}",
        "unfollow_failed": "*** 언팔로우 실패 — {name}, 상태 코드: {status} ***",
        "no_unfollow": "\n언팔로우할 사람이 없습니다!\n",
        "following_header": "\n*** 팔로우 중... ***\n",
        "no_follow": "\n팔로우할 사람이 없습니다!\n",
    },
}


LANG = resolve_lang()


def t(key: str, **kwargs: object) -> str:
    template = MESSAGES.get(LANG, MESSAGES["en"]).get(key) or MESSAGES["en"].get(key, key)
    return template.format(**kwargs)


def read_keys() -> tuple[str | None, str | None]:
    username = os.getenv("GIT_CLEANER_USERNAME")
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GIT_CLEANER_TOKEN")

    if KEYS_FILE.exists():
        with KEYS_FILE.open() as f:
            lines = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]
        for line in lines:
            if "=" in line:
                k, v = line.split("=", 1)
                k = k.strip().lower()
                v = v.strip()
                if k in ("username", "user"):
                    username = v
                elif k in ("token", "github_token", "personal_access_token"):
                    token = v
        if (not username or not token) and len(lines) >= 2 and "=" not in lines[0]:
            username = username or lines[0]
            token = token or lines[1]
    return username, token


def read_list(path: Path) -> list[str]:
    if not path.exists():
        return []
    with path.open() as f:
        return [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]


ensure_config_dir()

my_username, token = read_keys()
if not my_username or not token:
    print(t("missing_keys", path=KEYS_FILE))
    sys.exit(1)

exceptions = read_list(EXCEPTIONS_FILE)
blacklist = read_list(BLACKLIST_FILE)

base_url = f"https://api.github.com/users/{my_username}/"
headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def _paginated_get(url_template: str) -> list[dict]:
    users: list[dict] = []
    page = 1
    while True:
        url = f"{url_template}?per_page={PER_PAGE}&page={page}"
        response = requests.get(url, headers=headers, timeout=TIMEOUT)
        if response.status_code != 200:
            print(t("api_error", url=url, status=response.status_code))
            break
        data = response.json()
        if not data:
            break
        users.extend(data)
        if len(data) < PER_PAGE:
            break
        page += 1
    return users


def get_all_users(endpoint: str) -> list[dict]:
    return _paginated_get(f"{base_url}{endpoint}")


def get_user_following(username: str) -> list[str]:
    data = _paginated_get(f"https://api.github.com/users/{username}/following")
    return [u["login"] for u in data]


def check_rate_limit(required: int) -> bool:
    r = requests.get("https://api.github.com/rate_limit", headers=headers, timeout=TIMEOUT)
    if r.status_code != 200:
        print(t("rate_limit_warn", status=r.status_code))
        return True
    remaining = r.json().get("rate", {}).get("remaining", 0)
    print(t("rate_limit_remaining", remaining=remaining))
    if remaining < required:
        print(t("rate_limit_low", required=required, remaining=remaining))
        return False
    return True


def run_cleanup() -> None:
    followers = get_all_users("followers")
    following = get_all_users("following")

    follower_usernames = {f["login"] for f in followers}
    following_usernames = {u["login"] for u in following}

    unfollow = [n for n in following_usernames if n not in follower_usernames and n not in exceptions]
    follow = [n for n in follower_usernames if n not in following_usernames and n not in blacklist]

    if unfollow:
        print(t("unfollowing_header"))
        for name in unfollow:
            url = f"https://api.github.com/user/following/{name}"
            r = requests.delete(url, headers=headers, timeout=TIMEOUT)
            if r.status_code == 204:
                print(t("unfollowed", name=name))
            else:
                print(t("unfollow_failed", name=name, status=r.status_code))
    else:
        print(t("no_unfollow"))

    if follow:
        print(t("following_header"))
        for name in follow:
            url = f"https://api.github.com/user/following/{name}"
            r = requests.put(url, headers=headers, timeout=TIMEOUT)
            if r.status_code == 204:
                print(t("followed", name=name))
            else:
                print(t("follow_failed", name=name, status=r.status_code))
    else:
        print(t("no_follow"))


def run_discover(min_overlap: int, max_follows: int, dry_run: bool, concurrency: int) -> None:
    print(t("fetching_following"))
    my_following_raw = get_all_users("following")
    my_following = {u["login"] for u in my_following_raw}

    if not my_following:
        print(t("no_following"))
        return

    estimated = len(my_following) * 2 + max_follows + 5
    if not check_rate_limit(estimated):
        return

    users_list = sorted(my_following)
    total = len(users_list)
    print(t("scanning", n=total))

    counter: Counter[str] = Counter()
    lock = threading.Lock()
    completed = 0

    def fetch(user: str) -> tuple[str, list[str]]:
        return user, get_user_following(user)

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = [pool.submit(fetch, u) for u in users_list]
        for future in as_completed(futures):
            user, names = future.result()
            with lock:
                completed += 1
                print(t("scanning_user", i=completed, total=total, user=user), flush=True)
                for name in names:
                    if name == my_username or name in my_following or name in blacklist:
                        continue
                    counter[name] += 1

    candidates = [(name, count) for name, count in counter.most_common() if count >= min_overlap]

    if not candidates:
        print(t("no_candidates", min_overlap=min_overlap))
        return

    to_follow = candidates[:max_follows]

    print(t("candidates_header", min_overlap=min_overlap, n=len(to_follow)))
    for name, count in to_follow:
        print(t("candidate_row", count=count, name=name))

    if dry_run:
        print(t("dry_run_skip"))
        return

    print(t("following_n", n=len(to_follow)))
    for name, _ in to_follow:
        url = f"https://api.github.com/user/following/{name}"
        r = requests.put(url, headers=headers, timeout=TIMEOUT)
        if r.status_code == 204:
            print(t("followed", name=name))
        else:
            print(t("follow_failed", name=name, status=r.status_code))


def main() -> None:
    parser = argparse.ArgumentParser(prog="git-cleaner")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("run", help="Sync followers/following (follow back, unfollow non-mutuals)")

    disc = sub.add_parser("discover", help="Discover users followed by people you follow")
    disc.add_argument("--min-overlap", type=int, default=2)
    disc.add_argument("--max-follows", type=int, default=20)
    disc.add_argument("--dry-run", action="store_true")
    disc.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)

    args = parser.parse_args()

    if args.cmd == "discover":
        run_discover(args.min_overlap, args.max_follows, args.dry_run, args.concurrency)
    else:
        run_cleanup()


if __name__ == "__main__":
    main()
