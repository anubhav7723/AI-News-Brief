# AI Daily Brief 📰

> A fully automated AI news newspaper delivered to your inbox every morning at **6:30 AM IST**.  
> Powered by **RSS feeds + OpenAI GPT-OSS on Groq + Gmail SMTP + GitHub Actions** — completely free.

---

## What You Get

A newspaper-style HTML email with:
- **8–12 curated AI stories** ranked and summarised by OpenAI GPT-OSS on Groq
- **Why it matters** for each story — written for an AI/ML engineering audience
- **Technical takeaways** — concrete experiments or tools to try
- **Organised sections**: LLMs, Agents, Research, Open-Source, MLOps, Industry, Safety
- **Learn Today** — one daily action item for skill-building
- Working source links with full attribution

---

## Quick Start

### Prerequisites
- Python 3.11+
- A free [Groq API key](https://console.groq.com/keys)
- A Gmail account with [App Passwords enabled](https://myaccount.google.com/apppasswords)

### 1. Clone and Install

```bash
git clone https://github.com/yourusername/AI-Daily-Brief.git
cd AI-Daily-Brief
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure Secrets

```bash
cp .env.example .env
# Edit .env with your real values
```

Required `.env` values:

| Variable | Description |
|---|---|
| `GROQ_API_KEY` | Your free Groq API key from console.groq.com |
| `GROQ_MODEL` | Model name (default: `openai/gpt-oss-20b` or `openai/gpt-oss-120b`) |
| `EMAIL_SENDER` | Your Gmail address |
| `EMAIL_PASSWORD` | Your Gmail **App Password** (16 chars, not your login password) |
| `EMAIL_RECIPIENT` | Where to deliver the brief (can be same as sender) |

> **How to get a Gmail App Password:**
> 1. Go to [myaccount.google.com](https://myaccount.google.com)
> 2. Security → 2-Step Verification (enable if not already)
> 3. Security → App passwords → Create new → Name: "AI Daily Brief"
> 4. Copy the 16-character password into `EMAIL_PASSWORD`

### 3. Test Locally

```bash
# Dry run — renders email, saves HTML to data/preview_<date>.html, does NOT send
python main.py --dry-run

# Full run — sends the email for real
python main.py

# Debug mode
python main.py --dry-run --debug
```

Open `data/preview_<date>.html` in your browser to verify the email layout.

### 4. Run Tests

```bash
pytest tests/ -v
```

---

## GitHub Actions Deployment

### Step 1: Push to GitHub

```bash
git add .
git commit -m "feat: initial AI Daily Brief setup"
git push origin main
```

### Step 2: Add Secrets

In your GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret Name | Value |
|---|---|
| `GROQ_API_KEY` | Your Groq API key |
| `EMAIL_SENDER` | Your Gmail address |
| `EMAIL_PASSWORD` | Your Gmail App Password |
| `EMAIL_RECIPIENT` | Recipient email address |

Optionally, set a **Repository Variable** (not secret) for:

| Variable Name | Value |
|---|---|
| `GROQ_MODEL` | `openai/gpt-oss-20b` (or `openai/gpt-oss-120b`) |

### Step 3: Grant Write Permissions

Repo → **Settings → Actions → General → Workflow permissions → Read and write permissions** ✅

This allows the workflow to commit the updated `sent_stories.json` history back to the repo.

### Step 4: Test the Workflow

Repo → **Actions → AI Daily Brief → Run workflow → dry_run: true → Run workflow**

Check the **Artifacts** tab after the run to download and view the email HTML preview.

### Schedule

The workflow runs automatically every day at:
- **6:30 AM IST** (01:00 UTC)
- Cron: `0 1 * * *`

---

## Project Structure

```
AI-Daily-Brief/
├── .github/workflows/daily_brief.yml  # GitHub Actions schedule
├── src/
│   ├── collector.py    # RSS feed fetching
│   ├── cleaner.py      # Deduplication & URL normalization
│   ├── ranker.py       # Gemini: story selection
│   ├── summarizer.py   # Gemini: summarization
│   ├── validator.py    # Pydantic schemas
│   ├── renderer.py     # Jinja2 → HTML email
│   ├── mailer.py       # Gmail SMTP delivery
│   ├── history.py      # Persistent story memory
│   └── pipeline.py     # Orchestrator
├── templates/
│   └── email.html.j2   # Email template
├── config/
│   └── feeds.yaml      # RSS feeds (edit to add/remove sources)
├── tests/              # pytest unit tests
├── data/
│   └── sent_stories.json  # History (auto-committed by Actions)
├── .env.example        # Secret template
├── requirements.txt
├── main.py             # CLI entry point
└── README.md
```

---

## Customisation

### Adding or Removing Feeds

Edit [`config/feeds.yaml`](config/feeds.yaml). Each feed entry:

```yaml
feeds:
  - url: "https://example.com/rss.xml"
    name: "Example AI Blog"
    category: "llm_releases"   # See categories below
    priority: 1                # 1=high, 2=medium, 3=low
```

**Valid categories:** `llm_releases`, `agents`, `rag`, `research`, `open_source`, `mlops`, `industry`, `safety`, `general_ai`

### Changing the Schedule

Edit the cron expression in [`.github/workflows/daily_brief.yml`](.github/workflows/daily_brief.yml):

```yaml
schedule:
  - cron: "0 1 * * *"   # 01:00 UTC = 06:30 AM IST
```

Use [crontab.guru](https://crontab.guru) to generate your preferred time. Remember GitHub Actions runs in UTC.

### Changing the Number of Stories

Set `MAX_STORIES` in `.env` or as a GitHub Actions variable:

```
MAX_STORIES=10
```

### Adjusting History Retention

```
HISTORY_RETENTION_DAYS=14
```

---

## Free-Tier Usage Estimate

| Service | Free Limit | Daily Usage | Cost |
|---|---|---|---|
| Gemini Flash 2.0 | 1,500 req/day, 1M tokens/day | ~3 requests, ~12K tokens | **\$0** |
| Gmail SMTP | 500 emails/day | 1 email | **\$0** |
| GitHub Actions | 2,000 min/month | ~5 min/day ≈ 150 min/month | **\$0** |
| RSS Feeds | Public | ~20 feeds | **\$0** |
| **Total** | | | **\$0/month** |

> ⚠️ The system will never silently upgrade to a paid tier. If you hit a quota, the run will fail with a clear error message in the Actions log.

---

## Troubleshooting

### "No articles collected"
- Check your internet connection when running locally.
- One or more feeds may be temporarily down. The pipeline continues even if feeds fail.
- Try `--debug` to see per-feed logs.

### "SMTP authentication failed"
- Make sure you are using a **Gmail App Password**, not your regular password.
- Verify 2-Step Verification is enabled on your Google account.
- The App Password must not contain spaces when pasted into `.env`.

### "Edition already sent today"
- Expected behaviour — the duplicate guard prevents double-sends.
- To force a re-run, either delete the last entry from `data/sent_stories.json` or use `--dry-run`.

### "LLM returned no articles" / Gemini errors
- Check that `GEMINI_API_KEY` is valid and not expired.
- Gemini free tier limits: 1,500 RPD, 15 RPM. The pipeline uses ~3 requests, so this should never be an issue.
- The ranker and summariser both have heuristic fallbacks, so a Gemini failure degrades gracefully.

### Email looks broken in Gmail
- Open the HTML preview file in Chrome before testing email delivery.
- Gmail strips `<style>` blocks in some contexts. The template uses inline-style fallbacks for critical properties.

---

## Architecture

```
GitHub Actions (cron)
       ↓
  collector.py   ← config/feeds.yaml
       ↓
  history.py     ← data/sent_stories.json
       ↓
  cleaner.py     (dedup + normalize)
       ↓
  ranker.py      → Gemini API (ranking)
       ↓
  summarizer.py  → Gemini API (summarization)
       ↓
  validator.py   (Pydantic validation)
       ↓
  renderer.py    ← templates/email.html.j2
       ↓
  mailer.py      → Gmail SMTP
       ↓
  history.py     → data/sent_stories.json (committed to repo)
```

---

## License

MIT — see [LICENSE](LICENSE) for details.
