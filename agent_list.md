# Agent List

Detailed work and scope of every agent in company-brain, organized by department.
For the high-level platform overview, see [`README.md`](README.md).

Each department is one table with the header shown once. Within it, agents are grouped
in this order: **managers** first, then **cross-platform agents**, then **platform
specialist agents**, and the **onboarding agent always appears last** for its platform /
department. Each agent spans three stacked rows: its name on top, the other properties
below, then a full-width box holding its description. The property fields are:

- **State** — `persistent` (idles and wakes on schedule) or `ephemeral` (runs to completion).
- **Trigger/Schedule** — when it starts and what starts it.
- **Info Source** — where it ingests from.
- **Destination** — the wiki Markdown file it writes (source of truth).
- **Notion Page** — the linked/mirrored Notion page.

A blank field means it does not apply to that agent.

## Engineering

<table>
<thead>
<tr>
<th>State</th><th>Trigger/Schedule</th><th>Info Source</th><th>Destination</th><th>Notion Page</th>
</tr>
</thead>
<tbody>
<tr><td colspan="5"><strong>Managers</strong></td></tr>
<tr><td colspan="5"><strong><code>github_manager.py</code></strong></td></tr>
<tr>
<td>persistent</td><td>Starts at deploy; wakes daily at 08:00</td><td>GitHub (read-only <code>gh</code> CLI)</td><td></td><td></td>
</tr>
<tr><td colspan="5">Scoped to GitHub. On each morning check it refreshes branch status, and dispatches <code>open_pr</code> (when open PRs exist), <code>feature_update</code> (Mondays, when there was weekly commit activity), and <code>product_features</code> (when commits advanced since the last run). Idles between checks.</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong>GitHub specialists</strong> (<code>engineering/github/</code>)</td></tr>
<tr><td colspan="5"><strong><code>open_pr.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>Dispatched by <code>github_manager</code> when open PRs exist (daily check)</td><td>GitHub open PRs</td><td><code>engineering/github/open-prs.md</code></td><td>Open PRs</td>
</tr>
<tr><td colspan="5">Lists every open pull request with author, branch, and review decision, overwriting the page each run (update mode).</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong><code>branch_monitor.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>Dispatched by <code>github_manager</code> every morning</td><td>GitHub branches, PRs, and <code>compare</code> API</td><td><code>engineering/github/branch-status.md</code></td><td>Branch Status</td>
</tr>
<tr><td colspan="5">Per repo, maintains an Environments table (Prod/Preview/Dev deploys with ahead/behind vs prod) and a Branches/PRs table (target env, ahead/behind, last activity, risk verdict). Overwrites each run.</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong><code>feature_update.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>Dispatched by <code>github_manager</code> on Mondays when there was weekly commit activity</td><td>GitHub commits (last 7 days)</td><td><code>engineering/github/feature-updates.md</code></td><td>Feature Updates</td>
</tr>
<tr><td colspan="5">Digests the past week's commits, filters out merges/dependency bumps/trivia, and prepends a weekly section of major implementations (append mode, newest on top).</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong><code>product_features.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>Dispatched by <code>github_manager</code> when commits advanced since the last run</td><td>GitHub commits (last day)</td><td><code>engineering/github/product-features.md</code></td><td>Product Features</td>
</tr>
<tr><td colspan="5">Classifies commits into user-facing features and prepends newly detected ones, keeping a ranked list for end users (append mode).</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong>Onboarding</strong></td></tr>
<tr><td colspan="5"><strong><code>github_onboarding.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>Once, on first GitHub connection</td><td>GitHub (all repos)</td><td></td><td>Seeds all GitHub pages above</td>
</tr>
<tr><td colspan="5">Scans all repos under the account, summarizes the GitHub presence, then runs <code>open_pr</code>, <code>branch_monitor</code>, <code>feature_update</code>, and <code>product_features</code> once to seed their pages with real data. On completion, starts the persistent <code>github_manager</code> (which idles until its next morning check) and exits.</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
</tbody>
</table>

## Finance

<table>
<thead>
<tr>
<th>State</th><th>Trigger/Schedule</th><th>Info Source</th><th>Destination</th><th>Notion Page</th>
</tr>
</thead>
<tbody>
<tr><td colspan="5"><strong>Managers</strong></td></tr>
<tr><td colspan="5"><strong><code>monthly_expense.py</code></strong></td></tr>
<tr>
<td>persistent</td><td>Starts at deploy; wakes the 1st of each month at 08:00</td><td>Mercury bank + Mercury card + Ramp card (via specialists)</td><td><code>finance/expense-reports/&lt;YYYY-MM&gt;.md</code></td><td><code>&lt;Month&gt; Expense Report</code> (under Monthly Expense Reports)</td>
</tr>
<tr><td colspan="5">Dispatches the transaction specialists for the previous month, sorts outbound spend into budget categories, posts the report to Slack #finance, and writes a per-month page. If any spend is uncategorized, starts <code>request_manual_accounting</code>. Idles between runs.</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong><code>quarterly_calculation.py</code></strong></td></tr>
<tr>
<td>persistent</td><td>Starts at deploy; wakes the 5th of each quarter-start month at 09:00</td><td>Mercury + Ramp transactions (via specialists)</td><td><code>finance/quarterly-metric.md</code></td><td>Quarterly Metric</td>
</tr>
<tr><td colspan="5">Computes the previous quarter's Revenue, Expenses, Net Income, EBITDA, and Net Burn with a per-month breakdown, cross-verified against the monthly expense reports. Then starts <code>request_manual_accounting</code> (if any spend is uncategorized) or <code>budget_report</code> + <code>subscription_audit</code>. Idles between runs.</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong>Cross-platform agents</strong></td></tr>
<tr><td colspan="5"><strong><code>budget_report.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>Started by <code>quarterly_calculation</code> (cost-gated: only when the quarter's metrics changed)</td><td>Quarterly Metric + Company Timeline wiki pages</td><td><code>finance/budget-summary.md</code></td><td>Budget Summary</td>
</tr>
<tr><td colspan="5">Matches the quarter's spend to major company events and prepends a per-quarter budget section (append mode). Uses the Claude Agent SDK with a deterministic fallback.</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong><code>subscription_audit.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>Started by <code>quarterly_calculation</code></td><td>Mercury + Ramp transactions (3 months) + web search</td><td><code>finance/company-subscriptions.md</code></td><td>Company Subscriptions</td>
</tr>
<tr><td colspan="5">Detects recurring vendors over the past 3 months, verifies pricing via web search, flags overlapping services, posts a summary to Slack #finance, and overwrites the audit page (update mode).</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong><code>request_manual_accounting.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>Started by <code>monthly_expense</code> or <code>quarterly_calculation</code> on uncategorized spend; polls daily at noon</td><td>Notion Manual Accounting page (human input) + Slack</td><td><code>finance/manual-accounting.md</code></td><td>Manual Accounting</td>
</tr>
<tr><td colspan="5">Writes uncategorized transactions as a checklist, requests help in Slack #finance, and bumps daily until complete. On completion, records vendor-&gt;category mappings as learned categories and reruns the source manager. Overwrites the page (update mode).</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong>Mercury specialists</strong> (<code>finance/mercury/</code>)</td></tr>
<tr><td colspan="5"><strong><code>asset_compile.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>On demand (e.g. quarter-end snapshot)</td><td>Mercury bank + treasury balances/statements</td><td><code>finance/total-assets.md</code></td><td>Total Assets</td>
</tr>
<tr><td colspan="5">Snapshots total assets from Mercury bank + treasury for a month-end, quarter-end, or current date (credit balances excluded; statement balances for past periods). Prepends a snapshot (append mode).</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong><code>bank_transaction.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>On demand (called by the finance managers and audits)</td><td>Mercury bank accounts</td><td></td><td></td>
</tr>
<tr><td colspan="5">Pulls normalized inbound/outbound Mercury bank transactions for a date range, excluding internal/treasury transfers. Returns data to its caller.</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong><code>mercury_card_spend.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>On demand (called by the finance managers and audits)</td><td>Mercury IO credit card</td><td></td><td></td>
</tr>
<tr><td colspan="5">Pulls Mercury IO credit-card outflows for a date range, categorized by Mercury's own transaction categories. Returns data to its caller.</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong>Ramp specialists</strong> (<code>finance/ramp/</code>)</td></tr>
<tr><td colspan="5"><strong><code>ramp_card_spend.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>On demand (called by the finance managers and audits)</td><td>Ramp (via MCP)</td><td></td><td></td>
</tr>
<tr><td colspan="5">Reads Ramp card transactions for a date range via the Ramp MCP server and categorizes spend by QuickBooks accounting category. Returns data to its caller.</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong>Onboarding</strong></td></tr>
<tr><td colspan="5"><strong><code>finance_onboarding.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>Once, on first finance connection</td><td>Mercury transaction history</td><td>Seeds monthly + quarterly pages</td><td>Monthly Expense Reports, Quarterly Metric</td>
</tr>
<tr><td colspan="5">Backfills history by running <code>monthly_expense</code> and <code>quarterly_calculation</code> for every month/quarter with prior transactions (escalation disabled so historical periods do not spam manual-accounting requests). On completion, starts both persistent managers (which idle until the 1st of the month / 5th of the quarter) and exits.</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
</tbody>
</table>

## Operations

The catch-all department for general platforms that don't belong to a more specific
department. Platform connectivity is being set up; agents are not yet specced and will
be added here (managers, then cross-platform agents, then platform specialists, with the
onboarding agent last) as they are built.

- **Gmail** (`operations/gmail/`) — connection layer in place via `gmail_client.py`: Google's official Gmail MCP server by default, or Composio for less setup. Posture is read + labels + draft compose only (agents never send email). No agents yet.
