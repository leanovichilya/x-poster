# x-poster

CLI tool for publishing posts from a local folder queue to X (Twitter).

## Installation

```bash
pip install -e .
```

Or:

```bash
pip install -r requirements.txt
```

## Setup

Initialize data directories:

```bash
xposter init
```

This creates:

```
data/
├── queue/
├── sent/
│   ├── morning/
│   ├── day/
│   └── night/
├── failed/
│   ├── morning/
│   ├── day/
│   └── night/
├── config.json
├── tokens.json
├── schedule.json
└── log.jsonl
```

Edit `data/tokens.json` with your credentials:

```json
{
  "access_token": "your_access_token",
  "base_url": "https://api.twitter.com"
}
```

## Creating Posts

Create a post folder in `data/queue/yyyy-mm-dd/any_name/`:

```
data/queue/2025-02-01/hello-world/
├── post.json
├── 01.png
└── 02.jpg
```

`post.json` schema:

```json
{
  "text": "Hello from x-poster!",
  "publish_at": "",
  "labels": ["morning", "greeting"]
}
```

- `labels[0]` must be `morning`, `day`, or `night` (the slot)
- `publish_at` is optional; if empty, uses default time from `config.json`
- Images must be named `01.png`, `02.png`, `03.png`, `04.png` (up to 4)

## Configuration

`data/config.json`:

```json
{
  "timezone": "local",
  "default_times": {
    "morning": "09:00",
    "day": "13:00",
    "night": "22:30"
  }
}
```

## Commands

| Command | Description |
|---------|-------------|
| `xposter init` | Initialize data directories |
| `xposter watch` | Watch queue and post on schedule |
| `xposter run` | Process all due posts once |
| `xposter dry-run` | Preview what would be posted |
| `xposter validate` | Validate queue structure |

### Options

- `--data-dir PATH` - Override data directory (default: `./data` or `XP_DATA_DIR`)

## Watch Mode

```bash
xposter watch
```

The main way to run x-poster. Starts a background process that:

1. Scans `queue/` and builds schedule on startup
2. Sets timer for next scheduled post (no polling)
3. Watches for file changes in `queue/`
4. After file changes, waits 30 seconds (debounce) then rescans
5. Saves schedule to `data/schedule.json` on changes and exit

Example output:

```
[watcher] Initial scan...
[watcher] Found 2 post(s)
  hello-world @ 2025-02-01 09:00:00
  goodbye @ 2025-02-01 22:30:00
[scheduler] Next post: hello-world at 2025-02-01 09:00:00 (in 3600s)
[watcher] Watching data\queue

[watcher] added: post.json
[watcher] Changes detected, waiting 30s...
[watcher] Rescanning queue...
```

Press `Ctrl+C` to stop. Schedule is saved automatically.

## Output

After processing:

- **Success**: Post moved to `data/sent/{slot}/yyyy-mm-dd/HH-MM/post_name/`
- **Failure**: Post moved to `data/failed/{slot}/yyyy-mm-dd/HH-MM/post_name/` with `error.txt`

All attempts are logged to `data/log.jsonl`.

## Schedule File

`data/schedule.json` stores the current queue state:

```json
[
  {
    "folder": "data/queue/2025-02-01/hello-world",
    "text": "Hello!",
    "slot": "morning",
    "scheduled_dt": "2025-02-01T09:00:00",
    "labels": ["morning", "greeting"],
    "images": ["data/queue/2025-02-01/hello-world/01.png"]
  }
]
```

This file is updated automatically and preserves the queue on restart.
