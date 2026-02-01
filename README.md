# x-poster

A CLI utility for posting queued text and images to X (Twitter) using API v2.

## Features

- **Queue-based posting** - Create JSON job files and let x-poster handle the rest
- **OAuth2 PKCE authentication** - Secure login flow with automatic token refresh
- **Media upload** - Attach 1-4 images per post (supports JPEG, PNG, GIF, WebP)
- **Scheduled posts** - Set `publish_at` to delay posting until a specific time
- **File watcher** - Automatically process new jobs as they appear in the queue
- **Auto-discover images** - Images placed in `queue/img/` are auto-detected

## Installation

Requires Python 3.10+.

```bash
# Clone the repository
git clone <repo-url>
cd x-poster

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install in development mode
pip install -e .
```

## Configuration

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Fill in your X API credentials:
   ```env
   X_CLIENT_ID=your_client_id
   X_CLIENT_SECRET=your_client_secret  # Optional for public PKCE clients
   X_REDIRECT_URI=http://127.0.0.1:8080/callback
   X_SCOPES=tweet.read tweet.write users.read media.write offline.access
   ```

3. Initialize the data directories:
   ```bash
   xposter init
   ```

## Usage

### Authentication

Login to X and save access tokens:

```bash
xposter auth login
```

This opens the OAuth2 authorization flow. Follow the prompts to authorize the app.

### Creating a Post Job

Create a JSON file in the `data/queue/` directory:

```json
{
  "id": "unique-job-id",
  "text": "Hello from x-poster!",
  "image_paths": ["path/to/image.jpg"],
  "publish_at": "2025-01-28T12:00:00Z",
  "labels": ["greeting"]
}
```

**Job fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | Yes | Unique identifier for the job |
| `text` | string | No | Tweet text (max 280 characters) |
| `image_paths` | array | No | 1-4 image paths (relative to base-dir or absolute) |
| `publish_at` | string | No | ISO 8601 datetime; if set, post is delayed until this time |
| `labels` | array | No | Tags for organization |

### Posting

**Post the next ready job:**

```bash
xposter post next
```

**Run continuously (polls every N seconds):**

```bash
xposter run --interval 30
```

**Watch for new jobs and scheduled posts:**

```bash
xposter watch
```

The watch command monitors the queue directory for changes and processes scheduled posts automatically.

### Validation

Check all queue jobs for errors without posting:

```bash
xposter validate
```

## Commands Reference

| Command | Description |
|---------|-------------|
| `xposter init` | Initialize data directories |
| `xposter auth login` | Authenticate with X |
| `xposter post next` | Post the next ready job from the queue |
| `xposter run` | Continuously poll and post ready jobs |
| `xposter validate` | Validate all jobs in the queue |
| `xposter watch` | Watch queue and process jobs automatically |

### Common Options

- `--data-dir PATH` - Override default data directory (default: `./data` or `XP_DATA_DIR`)
- `--base-dir PATH` - Base directory for resolving relative image paths (default: current working dir)

## Directory Structure

```
data/
├── queue/          # Pending job files (.json)
│   └── img/        # Auto-discovered images
├── sent/           # Successfully posted jobs (with .result.json)
├── failed/         # Failed jobs (with .result.json)
├── tokens.json     # OAuth2 tokens (auto-managed)
└── log.jsonl       # Append-only event log
```

## Example Workflow

1. Authenticate:
   ```bash
   xposter auth login
   ```

2. Create a job file `data/queue/my-post.json`:
   ```json
   {
     "id": "my-first-post",
     "text": "Testing x-poster!",
     "image_paths": ["./photos/screenshot.png"]
   }
   ```

3. Validate and post:
   ```bash
   xposter validate
   xposter post next
   ```

4. Check results in `data/sent/` or `data/failed/`.

## License

MIT
