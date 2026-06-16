# 四库七阁

The automated platform that covers any information circulation within a company.

四库七阁 is the maintenance layer for an internal company wiki presented through [Notion](https://www.notion.so). It contains agents and components that ingest information from various sources, compile it into structured wiki articles, and publish them to your company's Notion workspace using the [Notion CLI](https://developers.notion.com/cli/get-started/overview).

## Agents

### Engineering

Managers (dispatch specialist agents based on the information they gather; a department can have several, each scoped to one or more platforms):

`github_manager.py` — Persistent manager scoped to GitHub (periodically checks GitHub according to its specified action schedule, idles otherwise). Detects relevant changes in GitHub and dispatches the specialist GitHub agents below to complete specific tasks.

#### GitHub (`engineering/github/`)


| Agent                  | Schedule                | Description                                                 |
| ---------------------- | ----------------------- | ----------------------------------------------------------- |
| `open_pr.py`           | On demand (via manager) | Syncs open PRs to a Notion "Open PRs" page                  |
| `feature_update.py`    | Mondays (via manager)   | Compiles major commits into a weekly "Feature Updates" page |
| `product_features.py`  | On demand (via manager) | Maintains a ranked "Product Features" page for end users    |
| `github_onboarding.py` | Once (first connection) | Scans all repos, seeds all GitHub-related Notion pages      |

### Finance

Managers (dispatch specialist agents based on the information they gather; each spans the department's platforms):

`monthly_expense.py` — Persistent manager (1st of each month at 08:00, idles otherwise). Dispatches the transaction specialists for the previous month, sorts outbound spend into budget categories, posts the report to Slack #finance, and creates a Notion "<Month> Expense Report" under "Monthly Expense Reports".

`quarterly_calculation.py` — Persistent manager (5th of each quarter at 09:00, idles otherwise). Computes Revenue, Expenses, Net Income, EBITDA, and Net Burn with a monthly breakdown into the Notion "Quarterly Metric" page; then starts `budget_report` and `subscription_audit` (or `manual_request` if anything is uncategorized).

Cross-platform agents (department level):

| Agent                  | Trigger                          | Description                                                                                  |
| ---------------------- | -------------------------------- | -------------------------------------------------------------------------------------------- |
| `budget_report.py`     | Started by quarterly_calculation | Matches spend to events in Notion "Company Timeline"; updates "Budget Summary" per quarter   |
| `subscription_audit.py`| Started by quarterly_calculation | Detects recurring spend, verifies pricing online, flags overlaps, updates "Company Subscriptions" |
| `manual_request.py`    | Started on uncategorized spend   | Requests manual categorization in Notion + Slack; learns the result and reruns the source agent |
| `finance_onboarding.py`| Once (first connection)          | Backfills monthly + quarterly reports for all historical periods                             |

#### Mercury (`finance/mercury/`)

| Agent                   | Schedule                | Description                                                            |
| ----------------------- | ----------------------- | --------------------------------------------------------------------- |
| `asset_compile.py`      | On demand (via manager) | Total assets from Mercury bank + treasury for a date (excludes credit)|
| `bank_transaction.py`   | On demand (via manager) | Inbound + outbound Mercury bank transactions for a time frame         |
| `mercury_card_spend.py` | On demand (via manager) | Mercury IO card spend categorized by Mercury's own categories         |

#### Ramp (`finance/ramp/`)

| Agent               | Schedule                | Description                                                      |
| ------------------- | ----------------------- | ---------------------------------------------------------------- |
| `ramp_card_spend.py`| On demand (via manager) | Ramp card spend categorized by QuickBooks categories (via MCP)   |

## Prerequisites

- Python 3.11+
- [Notion CLI (`ntn`)](https://developers.notion.com/cli/get-started/installation) installed and authenticated
- [GitHub CLI (`gh`)](https://cli.github.com/) installed and authenticated (read-only access)
- [Mercury CLI](https://mercury.com/api) installed; `MERCURY_TOKEN` set (finance agents)
- Ramp [MCP server](https://docs.ramp.com/developer-api/v1/ramp-mcp) configured; `RAMP_TOKEN` set (finance agents)
- Slack bot token (`SLACK_BOT_TOKEN`) for finance notifications to #finance
- `ANTHROPIC_API_KEY` for Claude Agent SDK agents

See `.env.example` for all environment variables.

## Install

```bash
pip install -e .
```

## Quick Start

```bash
# Authenticate the Notion CLI with your workspace
ntn login

# Initialize the wiki structure in your Notion workspace
company-brain init

# Check wiki status
company-brain status
```

## Commands


| Command                          | Description                                                |
| -------------------------------- | ---------------------------------------------------------- |
| `company-brain init`             | Discover existing workspace content, set up wiki structure |
| `company-brain ingest <source>`  | Run an ingestion agent                                     |
| `company-brain absorb`           | Compile raw entries into wiki articles                     |
| `company-brain query <question>` | Query the wiki                                             |
| `company-brain sync`             | Sync local registry with Notion                            |
| `company-brain status`           | Show wiki statistics                                       |
| `company-brain cleanup`          | Audit and enrich articles                                  |


## Project Structure

```
company-brain/
  config/
    wiki.yaml          # Wiki taxonomy and structure
    notion.yaml        # Notion workspace mapping (generated by init)
    finance.yaml       # Finance schedules, Slack channel, Notion titles, learned categories
  src/company_brain/
    cli.py             # CLI entry point
    config.py          # Configuration loader
    notion/            # Notion CLI wrapper and helpers
    wiki/              # Wiki data models, index, registry
    ingestion/         # Ingestion pipeline and base classes
    output/            # Formatter and publisher
    agents/            # Agent base classes, organized by department → platform
      engineering/             # Department (may hold multiple managers)
        github_manager.py        # Manager scoped to GitHub — dispatches GitHub specialists
        github/                  # Platform — specialist agents live directly here
          gh.py                  # Read-only GitHub CLI wrapper (shared)
          notion_binding.py      # Notion discover-or-create helper (shared)
          open_pr.py             # Open PRs → Notion (daily)
          feature_update.py      # Weekly feature updates → Notion (Mondays)
          product_features.py    # User-facing product features → Notion (ranked)
          github_onboarding.py   # One-time repo scan on first GitHub connection
      finance/                 # Department (Mercury + Ramp)
        monthly_expense.py       # Manager — monthly expense report (Notion + Slack)
        quarterly_calculation.py # Manager — quarterly metrics (Notion)
        budget_report.py         # Cross-platform — budget summary vs company timeline
        subscription_audit.py    # Cross-platform — recurring spend + overlap audit
        manual_request.py        # Cross-platform — manual categorization + learning loop
        finance_onboarding.py    # One-time historical backfill
        shared/                  # categories, notion_pages, slack, transactions, config
        mercury/                 # Mercury CLI wrapper + specialists
          mercury_client.py
          asset_compile.py
          bank_transaction.py
          mercury_card_spend.py
        ramp/                    # Ramp MCP client + specialist
          ramp_client.py
          ramp_card_spend.py
  scripts/
    setup_wiki.py      # Wiki initialization script
```

## Configuration

- `**config/wiki.yaml**` defines the wiki taxonomy: sections, article types, and writing conventions.
- `**config/notion.yaml**` maps wiki sections to Notion page IDs. Generated by `company-brain init`.

## License

MIT