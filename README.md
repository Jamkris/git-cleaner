# `git-cleaner`

**A CLI tool to automatically manage your GitHub followers and following lists.**

[English](./README.md) · [한국어](./README.ko.md)

> Tip: once `git-cleaner` is on your `PATH`, git auto-discovers it as a subcommand — you can call it as either `git-cleaner run` or `git cleaner run`.

---

## Features

1. **Automatic cleanup** — Unfollow users who don't follow you back
2. **Auto follow-back** — Follow back users who follow you
3. **Discover (friends-of-friends)** — Find and follow users who are already followed by multiple people you follow
4. **Exceptions list** — Users you always want to keep following (never auto-unfollow)
5. **Blacklist** — Users you never want to follow (always skipped)
6. **Dry-run mode** — Preview changes before anything happens
7. **Rate-limit aware** — Checks GitHub API budget before running expensive scans
8. **Bilingual UI** — All command output available in English and Korean (`git-cleaner lang en|ko`)

---

## Installation

### Via Homebrew (recommended)

```bash
brew tap jamkris/git-cleaner
brew install git-cleaner
```

### Manual installation

```bash
git clone https://github.com/Jamkris/git-cleaner.git
cd git-cleaner
chmod +x git-cleaner
sudo cp git-cleaner /usr/local/bin/
# Then place githubapi.py + requirements.txt next to the binary, or
# set SCRIPT_DIR references appropriately.
```

---

## Setup

Run the interactive setup once to save your credentials:

```bash
git-cleaner setup
```

This will:

- Prompt for your UI language (English / 한국어)
- Install the required Python dependency (`requests`)
- Prompt for your GitHub username
- Prompt for a GitHub **Personal Access Token (classic)** with the `user:follow` scope

> Create your token at <https://github.com/settings/tokens> → *Generate new token (classic)* → check `user:follow`.

Credentials are saved to `~/.config/git-cleaner/keys.txt` with `0600` permissions.

---

## Usage

### `git-cleaner run` — Sync mutual follows

```bash
git-cleaner run
```

- **Follows back** every user who follows you (skipping anyone in `blacklist`)
- **Unfollows** users who don't follow you back (skipping anyone in `exceptions`)

### `git-cleaner discover` — Find friends-of-friends

```bash
git-cleaner discover --dry-run
```

Scans the `following` list of every user you follow, counts how many of them follow each candidate, and suggests users who appear at least `--min-overlap` times. Always start with `--dry-run`.

**Options**

| Flag | Default | Description |
|---|---|---|
| `--min-overlap N` | `2` | Minimum number of your follows that must follow a candidate |
| `--max-follows N` | `20` | Maximum number of users to follow in a single run |
| `--dry-run` | off | Print candidates without following them |

**Example**

```bash
# Preview strictly — only users followed by 3+ of your follows
git-cleaner discover --min-overlap 3 --dry-run

# Commit: follow up to 10 of them
git-cleaner discover --min-overlap 3 --max-follows 10
```

**Sample output**

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

Blacklisted users and users you already follow are automatically filtered out.

### `git-cleaner -e <usernames...>` — Add to exceptions

```bash
git-cleaner -e username1 username2 username3
```

Users in `exceptions` will **never** be auto-unfollowed by `git-cleaner run`.

### `git-cleaner -b <usernames...>` — Add to blacklist

```bash
git-cleaner -b spammer1 spammer2
```

Users in `blacklist` will **never** be auto-followed by `git-cleaner run` or `git-cleaner discover`.

### `git-cleaner lang` — Switch UI language

```bash
git-cleaner lang          # show current language
git-cleaner lang ko       # switch to Korean
git-cleaner lang en       # switch to English
```

All command output is translated. The choice is saved to `~/.config/git-cleaner/config.txt`. Override per-invocation with an environment variable:

```bash
GIT_CLEANER_LANG=ko git-cleaner discover --dry-run
```

The environment variable takes precedence over the config file.

### `git-cleaner view` — Inspect your lists

```bash
git-cleaner view
```

Prints the current `exceptions` and `blacklist` with numbering.

### `git-cleaner -h` — Help

```bash
git-cleaner -h
```

---

## How `discover` works

GitHub's home-page "Who people are following" feed isn't available in the public API (the underlying `FollowEvent` was deprecated years ago). Instead, `discover` approximates it by crawling follow relationships:

```
For each user X you follow:
    fetch X's `following` list
    for each candidate Y in that list:
        if Y != you
        and Y is not already followed by you
        and Y is not in blacklist:
            counter[Y] += 1

Keep candidates with counter[Y] >= min_overlap
Sort by overlap (descending), take top max_follows
```

The higher the `--min-overlap`, the stronger the "social proof" signal and the less spammy the result.

---

## Rate limits

Authenticated GitHub API requests are limited to **5000/hour**. `discover` performs roughly `2 × (#following) + max_follows` requests. Before running, it calls `/rate_limit` and aborts if there isn't enough budget, so it won't silently exhaust your quota.

---

## Configuration files

All stored in `~/.config/git-cleaner/` (respects `$XDG_CONFIG_HOME`):

| File | Purpose |
|---|---|
| `keys.txt` | GitHub username and personal access token (`0600`) |
| `exceptions.txt` | One username per line — never auto-unfollow |
| `blacklist.txt` | One username per line — never auto-follow |
| `config.txt` | Key-value settings (currently: `lang=en` or `lang=ko`) |

Environment variables override file values when set:

- `GIT_CLEANER_USERNAME`
- `GITHUB_TOKEN` (or `GIT_CLEANER_TOKEN`)
- `GIT_CLEANER_LANG` (`en` or `ko`) — overrides `config.txt`

---

## Requirements

- **Python 3.10+** (uses modern type hints)
- `requests` library (installed automatically by `git-cleaner setup`)
- A GitHub **Personal Access Token (classic)** with the `user:follow` scope

---

## Safety notes

- Always run `git-cleaner discover --dry-run` first before committing follows.
- Keep `--max-follows` reasonable to avoid GitHub's anti-abuse throttling.
- Never commit `keys.txt` anywhere — it contains your access token.

---

## License

MIT — see [LICENSE](./LICENSE). Copyright © 2026 Jamkris \<contact@jamkris.com\>.
