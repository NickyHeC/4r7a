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
department.

<table>
<thead>
<tr>
<th>State</th><th>Trigger/Schedule</th><th>Info Source</th><th>Destination</th><th>Notion Page</th>
</tr>
</thead>
<tbody>
<tr><td colspan="5"><strong>Managers</strong></td></tr>
<tr><td colspan="5"><strong><code>gmail_manager.py</code></strong></td></tr>
<tr>
<td>persistent</td><td>Starts at deploy; wakes 08:00, 12:00, 16:00, and 22:00 on workdays</td><td>Gmail routing records (<code>wiki/operations/gmail/routing/</code>)</td><td></td><td></td>
</tr>
<tr><td colspan="5">Scoped to Gmail for every connected account. Dispatches profile-enabled specialists at 8/12/4 workdays (see <code>gmail.profiles</code> in <code>config/operations.yaml</code>). Monday 8am: <code>ingest_queue_review</code> when enabled. Friday 8am: <code>partnership_digest</code> / <code>receipt_router</code> when enabled. At 10pm: <code>inbox_sweep</code> when enabled.</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong>Gmail specialists</strong> (<code>operations/gmail/</code>)</td></tr>
<tr><td colspan="5"><strong><code>inbox_triage.py</code></strong></td></tr>
<tr>
<td>persistent</td><td>Starts at deploy; every 30 minutes on workdays</td><td>Gmail (REST history delta / backfill query)</td><td><code>operations/gmail/routing/&lt;mailbox&gt;/&lt;message_id&gt;.json</code></td><td></td>
</tr>
<tr><td colspan="5">The only raw-mail reader. Classifies new inbound mail with Phase-1 heuristics, applies visible attention labels (1–4) and hidden domain labels, marks read/archives per disposition, and writes one routing record per message. Does not dispatch specialists.</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong><code>inbox_sweep.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>Dispatched by <code>gmail_manager</code> at 22:00 on workdays</td><td>Gmail + routing records</td><td></td><td></td>
</tr>
<tr><td colspan="5">Nightly lifecycle sweep: archives Reply threads after a sent reply, FYI after opened, Newsletters/Receipts after +1 day, Meeting after opened. Deterministic REST only.</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong><code>thread_watcher.py</code></strong></td></tr>
<tr>
<td>persistent</td><td>Starts at deploy; every 15 minutes on workdays</td><td>Gmail sent-folder history delta</td><td>Routing record enrichment</td><td></td>
</tr>
<tr><td colspan="5">Watches for new sent mail. Classifies acknowledgments vs decisions vs ingest-worthy replies; applies <code>Decision</code> / <code>Ingest</code> labels; dispatches <code>decision_propagate</code> and <code>gmail_ingest</code>.</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong><code>draft_reply.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>Dispatched by <code>gmail_manager</code> at 8/12/4 on workdays</td><td>Gmail threads (<code>2. Reply</code>, low complexity)</td><td>Gmail draft (never send)</td><td></td>
</tr>
<tr><td colspan="5">Creates draft replies via Gmail MCP for simple Reply threads. Complex threads (legal, long, multi-party) are skipped for human handling.</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong><code>decision_propagate.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>Dispatched by <code>thread_watcher</code> on real decisions</td><td>Sent Gmail message</td><td><code>operations/gmail/company-timeline.md</code></td><td>Company Timeline</td>
</tr>
<tr><td colspan="5">Appends a decision section to the company timeline wiki page (Notion mirror). Skips thanks/pass acknowledgments.</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong><code>gmail_ingest.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>Dispatched by <code>thread_watcher</code> or <code>gmail_manager</code></td><td>Ingest-tagged Gmail threads</td><td><code>raw/entries/*.md</code></td><td></td>
</tr>
<tr><td colspan="5">Clear ingest content becomes raw wiki entries for absorb; ambiguous content is flagged for <code>ingest_queue_review</code>.</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong><code>ingest_queue_review.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>Monday 8am via <code>gmail_manager</code> (configurable)</td><td>Routing records with ambiguous ingest</td><td><code>operations/gmail/ingest-queue.md</code></td><td>Ingest Queue</td>
</tr>
<tr><td colspan="5">Appends ambiguous ingest items to the Ingest Queue wiki page and pings <code>#ingest</code> on Slack.</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong><code>attachment_router.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>Dispatched by <code>gmail_manager</code> at 8/12/4 on workdays</td><td>Gmail message attachments</td><td><code>operations/gmail/attachments/</code></td><td></td>
</tr>
<tr><td colspan="5">Fetches attachments from triaged mail and stores them under contracts/decks/documents/other on the wiki volume.</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong><code>investor_tracker.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>Dispatched by <code>gmail_manager</code> at 8/12/4 on workdays</td><td><code>Investor</code>, <code>Cold Inbound/Investor Interest</code></td><td><code>investors-crm.md</code>, <code>investor-interests.md</code></td><td>Investors CRM, Investor Interests</td>
</tr>
<tr><td colspan="5">Confirmed investors append to Investors CRM; cold investor interest appends to Investor Interests (MD first → Notion).</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong><code>gmail_customer_support.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>Dispatched by <code>gmail_manager</code> at 8/12/4 on workdays</td><td><code>Customer</code>-tagged mail</td><td></td><td></td>
</tr>
<tr><td colspan="5">Posts a summary (with source mailbox) to Slack <code>#customer-support</code> for each customer-tagged message.</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong><code>customer_crm.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>Dispatched by <code>gmail_manager</code> at 8/12/4 on workdays</td><td><code>Customer</code>-tagged mail</td><td><code>customer-crm.md</code></td><td>Customer CRM</td>
</tr>
<tr><td colspan="5">Appends customer interaction log to the Customer CRM wiki page (active customers only; list drives triage).</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong><code>growth_inbound.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>Dispatched by <code>gmail_manager</code> at 8/12/4 on workdays</td><td>Press &amp; Podcast, Event Invitations cold tags</td><td><code>media-promotion.md</code></td><td>Media Promotion</td>
</tr>
<tr><td colspan="5">Press/podcast → Media Promotion wiki. Event invites → Slack <code>#events</code> (attend) or <code>#growth</code> (sponsor/co-host).</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong><code>vendor_tracker.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>Dispatched by <code>gmail_manager</code> at 8/12/4 on workdays</td><td><code>Vendor</code>-tagged mail</td><td><code>vendors/&lt;slug&gt;.md</code></td><td>Per-vendor pages</td>
</tr>
<tr><td colspan="5">One wiki page per vendor for ops comms (contact, renewals). Finance costs stay in subscription_audit.</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong><code>gmail_crm.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>Dispatched by <code>gmail_manager</code> at 8/12/4 on workdays</td><td><code>People</code>, <code>Warm intro</code> (excludes <code>contact_type: investor</code>)</td><td><code>company-connections.md</code></td><td>Company Connections</td>
</tr>
<tr><td colspan="5">Appends people/connection interactions to Company Connections — not investor CRM.</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong><code>recruiting_inbound.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>Dispatched by <code>gmail_manager</code> at 8/12/4 on workdays</td><td><code>Cold Inbound/Job Seekers</code></td><td><code>inbound-candidates.md</code></td><td>Inbound Candidates</td>
</tr>
<tr><td colspan="5">Logs job seeker inbound even when auto-archived at triage.</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong><code>partnership_digest.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>Friday 8am via <code>gmail_manager</code> (configurable)</td><td>Partnership, Founder Networking cold tags</td><td></td><td></td>
</tr>
<tr><td colspan="5">Weekly ranked digest to Slack; keeps top relevant messages in inbox, archives the rest.</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong><code>inbox_task.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>Dispatched by <code>gmail_manager</code> at 8/12/4 on workdays</td><td><code>1. Action</code>, complex <code>2. Reply</code></td><td>Linear issue</td><td></td>
</tr>
<tr><td colspan="5">Creates Linear tasks for action mail and complex reply threads (simple replies stay with <code>draft_reply</code>).</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong><code>team_on_it.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>Dispatched by <code>gmail_manager</code> at 8/12/4 on workdays</td><td><code>4. Team On It</code></td><td>Linear issue + Slack</td><td></td>
</tr>
<tr><td colspan="5">Creates a Linear task and posts to <code>#team-ops</code> (configurable). No Gmail forward (send forbidden).</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong><code>duplicate_across_mailboxes.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>First in each <code>gmail_manager</code> dispatch pass</td><td>Routing records across <code>connected_mailboxes</code></td><td></td><td></td>
</tr>
<tr><td colspan="5">Marks secondary copies when the same thread/subject+from appears in multiple connected mailboxes.</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong><code>receipt_router.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>Friday 8am via <code>gmail_manager</code> (configurable)</td><td>Receipts tags + subscription sender list</td><td><code>receipt-routing.md</code></td><td>Receipt Routing</td>
</tr>
<tr><td colspan="5">Weekly gap report for missing subscription receipts; Ramp cross-check note when token set.</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong>Linear connection</strong> (<code>operations/linear/</code>)</td></tr>
<tr><td colspan="5"><strong><code>linear_client.py</code></strong></td></tr>
<tr>
<td></td><td></td><td>Linear GraphQL API / MCP / optional CLI</td><td></td><td></td>
</tr>
<tr><td colspan="5">Connection layer: GraphQL issue create (default), official MCP at <code>mcp.linear.app</code>, optional <code>linear</code> CLI when <code>LINEAR_USE_CLI=1</code>. Token via <code>LINEAR_API_KEY</code>.</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
<tr><td colspan="5"><strong>Onboarding</strong></td></tr>
<tr><td colspan="5"><strong><code>gmail_onboarding.py</code></strong></td></tr>
<tr>
<td>ephemeral</td><td>Once, on first Gmail connection</td><td>Gmail (30-day backfill by default)</td><td>Label taxonomy + routing records</td><td></td>
</tr>
<tr><td colspan="5">Ensures the Gmail label taxonomy, seeds CRM wiki pages, runs bounded backfill triage (default 30 days), then starts persistent <code>inbox_triage</code>, <code>thread_watcher</code>, and <code>gmail_manager</code> and exits.</td></tr>
<tr><td colspan="5">&nbsp;</td></tr>
</tbody>
</table>
