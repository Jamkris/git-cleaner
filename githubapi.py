import argparse
import os
import re
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

TIMEOUT = 15
PER_PAGE = 100
DEFAULT_CONCURRENCY = 10
DEFAULT_HARVEST_SLEEP = 1.0
HARVEST_OVERSHOOT_MULT = 3
HARVEST_OVERSHOOT_BASE = 50


def get_config_dir() -> Path:
    return Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config")) / "git-cleaner"


CONFIG_DIR = get_config_dir()
KEYS_FILE = CONFIG_DIR / "keys.txt"
EXCEPTIONS_FILE = CONFIG_DIR / "exceptions.txt"
BLACKLIST_FILE = CONFIG_DIR / "blacklist.txt"
CONFIG_FILE = CONFIG_DIR / "config.txt"
HARVESTED_FILE = CONFIG_DIR / "harvested.txt"


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
        "harvest_fetching": "Fetching recent candidates from {source}: {target}...",
        "harvest_found": "Fetched {n} raw candidates, filtering against your follows / blacklist / history...",
        "harvest_no_candidates": "No eligible candidates found. Try a different source or --limit higher.",
        "harvest_plan": "\n=== Harvest plan ({source}: {target}) — {n} users ===",
        "harvest_progress": "  [{i}/{total}] Followed: {name}",
        "harvest_follow_fail": "  [{i}/{total}] Failed {name} (status {status})",
        "harvest_rate_limited": "\n⚠ Hit GitHub secondary rate limit. Stopping early to protect your account.",
        "harvest_summary": "\nDone — followed {followed}, failed {failed}. History recorded in harvested.txt.",
        "harvest_warn_high": "⚠ Warning: following {n} users in one run may trigger anti-abuse throttling. Consider splitting across days.",
        "harvest_unknown_source": "Unknown harvest source: {source}. Use 'stargazers' or 'followers'.",
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
        "harvest_fetching": "{source} 에서 최근 후보를 가져오는 중: {target}...",
        "harvest_found": "원본 후보 {n}명 확보. 내 팔로잉 / 블랙리스트 / 이력 기준으로 필터링 중...",
        "harvest_no_candidates": "팔로우 가능한 후보가 없습니다. 다른 소스를 시도하거나 --limit 을 늘려보세요.",
        "harvest_plan": "\n=== Harvest 계획 ({source}: {target}) — {n}명 ===",
        "harvest_progress": "  [{i}/{total}] 팔로우 완료: {name}",
        "harvest_follow_fail": "  [{i}/{total}] 실패 — {name} (상태 {status})",
        "harvest_rate_limited": "\n⚠ GitHub secondary rate limit 에 걸렸습니다. 계정 보호를 위해 조기 종료합니다.",
        "harvest_summary": "\n완료 — 팔로우 {followed}명, 실패 {failed}명. 이력은 harvested.txt 에 기록되었습니다.",
        "harvest_warn_high": "⚠ 경고: 한 번에 {n}명 팔로우는 어뷰징 감지에 걸릴 수 있습니다. 며칠에 걸쳐 나눠서 실행하세요.",
        "harvest_unknown_source": "알 수 없는 harvest 소스: {source}. 'stargazers' 또는 'followers' 중에서 선택하세요.",
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


def _parse_last_page(link_header: str) -> int:
    for part in link_header.split(","):
        if 'rel="last"' in part:
            m = re.search(r"[?&]page=(\d+)", part)
            if m:
                return int(m.group(1))
    return 1


def _fetch_recent_paginated(base_url: str, limit: int) -> list[str]:
    """Fetch the most recent entries first by starting from the last page."""
    first_url = f"{base_url}?per_page={PER_PAGE}&page=1"
    r = requests.get(first_url, headers=headers, timeout=TIMEOUT)
    if r.status_code != 200:
        print(t("api_error", url=first_url, status=r.status_code))
        return []

    link = r.headers.get("Link", "")
    last_page = _parse_last_page(link)

    if last_page <= 1:
        data = r.json()
        return [u["login"] for u in reversed(data)][:limit]

    users: list[str] = []
    page = last_page
    while page >= 1 and len(users) < limit:
        url = f"{base_url}?per_page={PER_PAGE}&page={page}"
        resp = requests.get(url, headers=headers, timeout=TIMEOUT)
        if resp.status_code != 200:
            print(t("api_error", url=url, status=resp.status_code))
            break
        data = resp.json()
        if not data:
            break
        users.extend(u["login"] for u in reversed(data))
        page -= 1
    return users[:limit]


def fetch_stargazers(repo: str, limit: int) -> list[str]:
    repo = repo.strip().strip("/")
    return _fetch_recent_paginated(f"https://api.github.com/repos/{repo}/stargazers", limit)


def fetch_user_followers(username: str, limit: int) -> list[str]:
    username = username.strip().lstrip("@")
    return _fetch_recent_paginated(f"https://api.github.com/users/{username}/followers", limit)


def read_harvested() -> set[str]:
    if not HARVESTED_FILE.exists():
        return set()
    with HARVESTED_FILE.open() as f:
        return {line.strip() for line in f if line.strip() and not line.startswith("#")}


def append_harvested(names: list[str]) -> None:
    if not names:
        return
    with HARVESTED_FILE.open("a") as f:
        for name in names:
            f.write(f"{name}\n")


def _is_secondary_rate_limit(response: requests.Response) -> bool:
    if response.status_code not in (403, 429):
        return False
    body = (response.text or "").lower()
    return "secondary rate limit" in body or "abuse" in body


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


def run_harvest(
    source: str,
    target: str,
    limit: int,
    dry_run: bool,
    sleep_sec: float,
) -> None:
    if limit > 50:
        print(t("harvest_warn_high", n=limit))

    print(t("harvest_fetching", source=source, target=target))
    overshoot = limit * HARVEST_OVERSHOOT_MULT + HARVEST_OVERSHOOT_BASE

    if source == "stargazers":
        raw = fetch_stargazers(target, overshoot)
    elif source == "followers":
        raw = fetch_user_followers(target, overshoot)
    else:
        print(t("harvest_unknown_source", source=source))
        return

    if not raw:
        print(t("harvest_no_candidates"))
        return

    print(t("harvest_found", n=len(raw)))

    my_following_raw = get_all_users("following")
    my_following = {u["login"] for u in my_following_raw}
    harvested = read_harvested()
    blocked = set(blacklist)

    eligible: list[str] = []
    seen: set[str] = set()
    for name in raw:
        if name in seen:
            continue
        seen.add(name)
        if name == my_username:
            continue
        if name in my_following:
            continue
        if name in blocked:
            continue
        if name in harvested:
            continue
        eligible.append(name)
        if len(eligible) >= limit:
            break

    if not eligible:
        print(t("harvest_no_candidates"))
        return

    print(t("harvest_plan", source=source, target=target, n=len(eligible)))
    for name in eligible:
        print(f"  → {name}")

    if dry_run:
        print(t("dry_run_skip"))
        return

    followed: list[str] = []
    failed: list[str] = []
    total = len(eligible)
    for i, name in enumerate(eligible, 1):
        url = f"https://api.github.com/user/following/{name}"
        r = requests.put(url, headers=headers, timeout=TIMEOUT)
        if r.status_code == 204:
            print(t("harvest_progress", i=i, total=total, name=name), flush=True)
            followed.append(name)
        elif _is_secondary_rate_limit(r):
            print(t("harvest_rate_limited"))
            break
        else:
            print(t("harvest_follow_fail", i=i, total=total, name=name, status=r.status_code), flush=True)
            failed.append(name)
        if i < total:
            time.sleep(sleep_sec)

    # Record every attempted name (success or fail) so we don't retry later.
    append_harvested(followed + failed)
    print(t("harvest_summary", followed=len(followed), failed=len(failed)))


def main() -> None:
    parser = argparse.ArgumentParser(prog="git-cleaner")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("run", help="Sync followers/following (follow back, unfollow non-mutuals)")

    disc = sub.add_parser("discover", help="Discover users followed by people you follow")
    disc.add_argument("--min-overlap", type=int, default=2)
    disc.add_argument("--max-follows", type=int, default=20)
    disc.add_argument("--dry-run", action="store_true")
    disc.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)

    harvest = sub.add_parser("harvest", help="Harvest followers from a high-value pool")
    harvest_sub = harvest.add_subparsers(dest="source")

    h_star = harvest_sub.add_parser("stargazers", help="Follow recent stargazers of a repo")
    h_star.add_argument("--repo", required=True, help="owner/repo, e.g. facebook/react")
    h_star.add_argument("--limit", type=int, default=20)
    h_star.add_argument("--sleep", type=float, default=DEFAULT_HARVEST_SLEEP)
    h_star.add_argument("--dry-run", action="store_true")

    h_fol = harvest_sub.add_parser("followers", help="Follow recent followers of a user")
    h_fol.add_argument("--user", required=True, help="target username")
    h_fol.add_argument("--limit", type=int, default=20)
    h_fol.add_argument("--sleep", type=float, default=DEFAULT_HARVEST_SLEEP)
    h_fol.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    if args.cmd == "discover":
        run_discover(args.min_overlap, args.max_follows, args.dry_run, args.concurrency)
    elif args.cmd == "harvest":
        if args.source == "stargazers":
            run_harvest("stargazers", args.repo, args.limit, args.dry_run, args.sleep)
        elif args.source == "followers":
            run_harvest("followers", args.user, args.limit, args.dry_run, args.sleep)
        else:
            harvest.print_help()
    else:
        run_cleanup()


if __name__ == "__main__":
    main()
