# Customization & Configuration Guide — AI Daily Brief 📰

This guide explains how to customize your sources, add multiple email recipients, adjust the daily delivery time, and push changes to GitHub.

---

## 1. Where & How to Edit Custom Website Pages (Feeds)

All news sources and keyword filters are located in:  
📁 **[`config/feeds.yaml`](config/feeds.yaml)**

### Adding a New Feed
To add any new website or blog, find its RSS or Atom feed link and append it to the `feeds:` list:

```yaml
  - url: "https://example.com/feed.xml"     # Direct RSS / Atom feed URL
    name: "Tech News Daily"                 # Readable source name
    category: "open_source"                 # Category (see list below)
    priority: 1                             # 1 = Top priority / breaking; 2 = Standard
```

### Available Categories:
* `llm_releases` — Foundation models, LLMs, frontier lab releases
* `agents` — AI agents, agentic workflows, LangGraph, MCP
* `research` — arXiv papers, academic breakthroughs, benchmarks
* `open_source` — GitHub tools, open-weight models, libraries
* `mlops` — AI infrastructure, deployment, GPUs, serving engines
* `industry` — Major funding, partnerships, acquisitions
* `safety` — AI alignment, ethics, regulations
* `general_ai` — General industry news

### Adding Boost & Exclusion Keywords:
In the same file ([`config/feeds.yaml`](config/feeds.yaml)), you can fine-tune what stories get prioritized or filtered out:

```yaml
# Drops stories matching these terms:
exclusion_keywords:
  - "crypto"
  - "nft"
  - "sponsor"

# Gives extra relevance boost to stories containing these terms:
boost_keywords:
  - "open-source"
  - "weights"
  - "agent"
  - "rag"
```

---

## 2. Where & How to Add Multiple Email Recipients

You can send the daily newspaper to as many people as you want (friends, team members, or other email accounts).

### Local Configuration:
Open your local **`.env`** file and separate emails with commas:
```env
EMAIL_RECIPIENT=anubhavg0098@gmail.com, colleague@example.com, friend@gmail.com
```

### GitHub Actions (Cloud) Configuration:
1. Open your repository on GitHub: **[https://github.com/anubhav7723/AI-News-Brief](https://github.com/anubhav7723/AI-News-Brief)**
2. Go to **Settings** → **Secrets and variables** → **Actions**.
3. Under **Repository secrets**, click the pencil icon next to **`EMAIL_RECIPIENT`**.
4. Update the value with multiple emails separated by a comma:
   ```text
   anubhavg0098@gmail.com, colleague@example.com
   ```
5. Click **Update secret**.

---

## 3. Where & How to Edit Delivery Time

The delivery schedule is controlled by the GitHub Actions workflow file:  
📁 **[`.github/workflows/daily_brief.yml`](.github/workflows/daily_brief.yml)**

Around line 6, look for the `cron` expression:

```yaml
on:
  schedule:
    # 01:00 UTC = 6:30 AM IST (Indian Standard Time)
    - cron: "0 1 * * *"
```

### Understanding UTC vs IST Time:
GitHub Actions runs on **UTC time**, which is **5 hours and 30 minutes behind IST**:
$$\text{UTC Time} = \text{IST Time} - \text{5 hours 30 minutes}$$

### Popular Delivery Time Examples:

| Desired IST Time | UTC Equivalent | Cron Expression to Use |
|---|---|---|
| **6:30 AM IST** *(Current default)* | 01:00 UTC | `- cron: "0 1 * * *"` |
| **7:00 AM IST** | 01:30 UTC | `- cron: "30 1 * * *"` |
| **8:00 AM IST** | 02:30 UTC | `- cron: "30 2 * * *"` |
| **9:00 AM IST** | 03:30 UTC | `- cron: "30 3 * * *"` |
| **8:00 PM IST** (Evening Digest) | 14:30 UTC | `- cron: "30 14 * * *"` |

*Note: The 5 fields in cron are: `minute hour day-of-month month day-of-week`.*

---

## 4. What To Do After Making Changes (Deploying to GitHub)

Whenever you edit [`config/feeds.yaml`](config/feeds.yaml) or [`.github/workflows/daily_brief.yml`](.github/workflows/daily_brief.yml), follow this standard workflow:

### Step 1: Test Locally (Optional but Recommended)
Test that your feed changes or recipient changes parse properly without sending duplicate emails:
```powershell
.venv\Scripts\python main.py --dry-run
```
Open `data/preview_YYYY-MM-DD.html` in your browser to inspect the output.

### Step 2: Commit and Push to GitHub
Run these commands in your PowerShell terminal:
```powershell
# Check modified files
git status

# Stage changes
git add config/feeds.yaml .github/workflows/daily_brief.yml

# Commit with a descriptive message
git commit -m "chore: update news feeds and delivery schedule"

# Push to your personal GitHub repository
git push origin main
```

### Step 3: Trigger an Instant Manual Run (Verify in Cloud)
1. In your GitHub repository, click the **Actions** tab at the top.
2. Under "All workflows" on the left, click **AI Daily Brief**.
3. On the right, click the **Run workflow** dropdown button.
4. Leave `dry_run` unchecked (or checked for a preview test) and click **Run workflow**.
5. Within 1–2 minutes, check your inbox!
