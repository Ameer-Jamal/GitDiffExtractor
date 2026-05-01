# **Git Diff Extractor GUI and MCP: AI-Ready Git and PR Context**

### **Overview**

The **Git Diff Extractor** is a desktop application and local MCP server for collecting repository context that AI tools can use directly. It helps you inspect pull requests, generate diffs, query contribution history, and expose that same data to MCP-compatible agents.
<img width="819" height="949" alt="image" src="https://github.com/user-attachments/assets/5625785f-8f7c-4e7d-9b84-200467c74a6c" />

---

## **Why I Built This?**
The core inspiration behind this tool is **bridging the gap between developers and AI-driven tools**. Git and provider APIs already contain the context an AI needs, but that context is scattered across commits, PRs, branches, repositories, and contribution history. This tool aims to:
- Collect repository and PR context in one place.
- Generate concise, reusable diffs and history summaries.
- Let MCP-compatible AI clients call the same data-gathering tools directly.

---

## **Key Features**

1. **Extract Git Diffs**: Extract diffs between commits or pull request branches and view the changes in a structured way.

2. **Intelligent PR Display**: Pull requests are displayed in a structured way. Click on any PR to view the detailed diff and even auto-insert commit hashes for further analysis.

3. **Search PRs Easily**: Filter and search through PRs using keywords, branches, commit hashes, or other metadata.

4. **Provider-Based Repository Discovery**: Configure Bitbucket or GitHub credentials in **Settings**, discover accessible repositories, and activate one or many repositories without manual local-folder selection.

5. **Multi-Repository Workflows**: Run PR, branch, and history workflows across selected repositories with clear repository context in results.

6. **Contribution History Tab**:
   - Query merged PRs, commits, or merged PRs + standalone commits
   - Scope by current repo, selected repos, or all repos in provider context
   - Filter by developer identity, date range presets/custom range, text search, branch, and bot exclusion
   - Select multiple developer aliases in one query (OR matching)
   - View summary metrics including `Fully scanned: X/Y`
   - Export to CSV, JSON, and Markdown (including PR descriptions)

7. **MCP Server Mode**:
   - Run Git Diff Extractor as a local MCP server
   - Expose repository discovery, PR listing, contribution history, and diff retrieval as AI tools
   - Reuse saved desktop-app config or override it with environment variables

---

## **How to Use the App**

1. **Configure Provider in Settings**:
   - Choose **Bitbucket** or **GitHub** and enter credentials.
   - Discover repositories and select one or many active repositories.

2. **View and Filter PRs**:
   - Use the **PR Diff Extractor** tab to list PRs for the active repository scope.
   - Search and open diffs as needed.

3. **Use Branch Commit Viewer / Create PR**:
   - Branch and PR actions run against active provider-backed repositories.

4. **Use Contribution History**:
   - Open the **Contribution History** tab.
   - Select one or multiple developer identities (aliases), choose scope/date/type, and run query.
   - Export results for resume/self-review/reporting.

5. **Use AI to Understand Diffs**:
   - Copy/export results manually, or connect the MCP server so your AI client can request the context directly.

6. **Use MCP with AI tools**:
   - Start the local MCP server through any MCP-compatible client and let the agent call Git Diff Extractor directly.

---

## **Contribution History Notes**

- **Summary-first output**: No inline code diffs by default; focus is historical work reconstruction.
- **Titles/messages only mode**: Keeps output compact for reporting and AI prompting.
- **Rate-limit resilience**: Bitbucket scans use throttling, retry/backoff, and continuation logic to improve completeness.
- **Scan completeness signal**: Summary shows `Fully scanned: X/Y` so you can quickly see whether a run was partial.

---

## **Why Use Git Diff Extractor?**

- **Time-saving**: Quickly understand what changed in a pull request without digging through provider pages and local git commands.
- **AI-ready context**: Give AI tools structured access to PRs, diffs, and contribution history through MCP.
- **Structured PR viewing**: PRs are displayed with repository, branch, author, state, and commit context.
- **Historical recall**: Reconstruct what changed across repos, developers, branches, and time windows.

---

## **Installation**

To run the app, follow these steps:

1. **Install Dependencies**:
   Make sure you have Python and PyQt5 installed. You can install the dependencies using:

   ```bash
   pip install -r requirements.txt
   ```

2. **Run the App**:

   ```bash
   python3 main.py
   ```

3. **Configure provider access in the app**:
   - Open `Settings`
   - Choose `Bitbucket` or `GitHub`
   - Enter credentials
   - Discover repositories and activate/select the ones you want

4. **Use the app**:
   Select the repository scope you want and start analyzing PRs, branches, commits, or contribution history.

---

## **Use This Project with AI via MCP**

This repo includes a local stdio MCP server at `mcp_server.py`.

Any MCP-compatible AI client can launch it directly and use Git Diff Extractor as a tool source.

### **What The MCP Server Does**

The MCP server gives an AI client read-only access to the same repository context the desktop app collects:

- inspect the active provider/repository context
- list accessible repositories
- list the selected repositories saved by the desktop app
- list/search pull requests for a repository, optionally filtered by developer
- list pull requests authored by the authenticated provider user
- find pull requests by ticket id, including multiple PRs for the same ticket
- retrieve grouped PR diffs for one or more tickets
- retrieve a pull request diff
- retrieve a commit diff
- query contribution history across current, selected, or all repositories
- list likely developer identity candidates for contribution-history filters

The server may clone or fetch local repositories when a diff tool needs a checkout, but it does not create PRs, change settings, edit repositories, or write provider data.

### **MCP Tools**

- `get_active_context`
- `list_repositories`
- `get_selected_repositories`
- `list_pull_requests`
- `list_my_pull_requests`
- `find_pull_requests_by_ticket`
- `get_ticket_diffs`
- `get_pr_diff`
- `get_commit_diff`
- `query_contribution_history`
- `list_developer_candidates`

### **General setup**

MCP is the integration standard here. Codex is one client example, but the same server can be used by other MCP-compatible tools as well.

Typical flow:

- configure provider credentials and repositories in the app, or pass them as env vars
- register `mcp_server.py` with your MCP client
- restart the client
- ask the AI to use the Git Diff Extractor MCP tools

### **Basic Test Prompt**

Use this prompt in a new AI client after registering the MCP server:

```text
Use the Git Diff Extractor MCP server to test basic functionality.

1. Call get_active_context and tell me the configured provider, active repository, selected repository count, and whether config came from app config or overrides.
2. Call get_selected_repositories and list the selected repository names.
3. Call list_pull_requests for the active repository with filter_mode="open" and summarize the count plus the first 3 PR ids/titles/states.
4. Call find_pull_requests_by_ticket with ticket="RU-25463" and summarize any matching PRs.
5. Do not call get_pr_diff yet unless I explicitly ask, because diffs can be large.
6. If any tool fails, report the exact tool name and error.
```

Developer PR prompt:

```text
Use the Git Diff Extractor MCP server to list my open pull requests across selected repositories.

Call list_my_pull_requests with:
scope="selected"
filter_mode="open"

Return the repo, PR id, title, source branch, target branch, and link for each PR.
```

To inspect another developer:

```text
Use the Git Diff Extractor MCP server to list Ameer's merged pull requests across selected repositories.

Call list_pull_requests for each selected repository with:
developer="Ameer"
filter_mode="merged"

Summarize the PR ids, titles, repos, and branches.
```

If that works, test a specific diff with a follow-up prompt:

```text
Use the Git Diff Extractor MCP server to call get_pr_diff for PR <PR_ID> in the active repository. Summarize the files and main change themes. If the diff is truncated, say so.
```

Ticket lookup prompt:

```text
Use the Git Diff Extractor MCP server to find pull requests for ticket RU-25463. Search the active repository first. If there are multiple PRs, list each PR id, title, state, source branch, destination branch, and link.
```

Multi-ticket diff prompt:

```text
Use the Git Diff Extractor MCP server to call get_ticket_diffs with tickets_json=["RU-25463", "RU-00000"]. Analyze the returned PR diffs and create this table:

| Ticket # | QA Impact | Notes/Comments |
|---|---|---|

Rules:
- Combine multiple PRs for the same ticket into one row.
- QA Impact should describe what QA should test, not just which files changed.
- Notes/Comments should include PR ids and any uncertainty.
- If no PRs are found for a ticket, say that directly.
- If any diff is truncated or failed, mention that in Notes/Comments.
```

### **Codex example**

If you already configured provider credentials and repositories in the desktop app, the MCP server can reuse that saved config.

From this repo, add it to Codex:

```bash
codex mcp add gitDiffExtractor -- python3 /Users/ajamal/Documents/PythonProjects/GitDiffExtractor/mcp_server.py
```

Verify it is registered:

```bash
codex mcp list
```

Then restart Codex and ask for it explicitly, for example:

```text
Use the gitDiffExtractor MCP server to list pull requests for my active repository and summarize the latest 5.
```

### **MCP-specific overrides**

The server supports environment-variable overrides on top of the saved app config.

Example with GitHub:

```bash
codex mcp add gitDiffExtractor \
  --env GITDIFFEXTRACTOR_PROVIDER=github \
  --env GITDIFFEXTRACTOR_GITHUB_OWNER=your-org-or-user \
  --env GITDIFFEXTRACTOR_GITHUB_TOKEN=your-token \
  -- python3 /Users/ajamal/Documents/PythonProjects/GitDiffExtractor/mcp_server.py
```

Example with Bitbucket:

```bash
codex mcp add gitDiffExtractor \
  --env GITDIFFEXTRACTOR_PROVIDER=bitbucket \
  --env GITDIFFEXTRACTOR_BITBUCKET_USERNAME=your-username \
  --env GITDIFFEXTRACTOR_BITBUCKET_APP_PASSWORD=your-app-password \
  --env GITDIFFEXTRACTOR_BITBUCKET_WORKSPACE=your-workspace \
  -- python3 /Users/ajamal/Documents/PythonProjects/GitDiffExtractor/mcp_server.py
```

### **Codex config example**

Codex stores MCP servers in `~/.codex/config.toml`.

For a local stdio server, the equivalent config looks like this:

```toml
[mcp_servers.gitDiffExtractor]
command = "python3"
args = ["/Users/ajamal/Documents/PythonProjects/GitDiffExtractor/mcp_server.py"]

[mcp_servers.gitDiffExtractor.env]
GITDIFFEXTRACTOR_PROVIDER = "github"
```

You can add more environment variables under `[mcp_servers.gitDiffExtractor.env]` as needed.

### **Environment variables supported by the MCP server**

- `GITDIFFEXTRACTOR_PROVIDER`
- `GITDIFFEXTRACTOR_BITBUCKET_USERNAME`
- `GITDIFFEXTRACTOR_BITBUCKET_APP_PASSWORD`
- `GITDIFFEXTRACTOR_BITBUCKET_WORKSPACE`
- `GITDIFFEXTRACTOR_GITHUB_OWNER`
- `GITDIFFEXTRACTOR_GITHUB_REPO`
- `GITDIFFEXTRACTOR_GITHUB_TOKEN`
- `GITDIFFEXTRACTOR_MANAGED_REPO_ROOT`
- `GITDIFFEXTRACTOR_SELECTED_REPOSITORIES_JSON`
- `GITDIFFEXTRACTOR_ACTIVE_REPO_PROVIDER`
- `GITDIFFEXTRACTOR_ACTIVE_REPO_ID`
- `GITDIFFEXTRACTOR_ACTIVE_REPO_NAME`
- `GITDIFFEXTRACTOR_ACTIVE_REPO_OWNER`
- `GITDIFFEXTRACTOR_ACTIVE_REPO_SLUG`
- `GITDIFFEXTRACTOR_ACTIVE_REPO_CLONE_URL`
- `GITDIFFEXTRACTOR_ACTIVE_REPO_HTML_URL`
- `GITDIFFEXTRACTOR_ACTIVE_REPO_LOCAL_DIR`

### **Important notes**

- This MCP server is currently **local stdio only**. It is intended for local MCP clients.
- MCP is the protocol/integration point. Codex is just one supported client example.
- If you already saved credentials and repository selections in the desktop app, you usually do **not** need to pass env vars.
- Developer filters use provider-side author search where supported. Bitbucket does not support filtering PRs by author fields in its query API, so the app applies state/search filters through Bitbucket first and then filters authors locally.
- If your AI client does not automatically choose the server, mention it explicitly in your prompt.
- You do **not** need to reinstall/register the MCP server after code changes when the command path stays the same.
- Restart your MCP client after code changes so it starts a fresh server process and reloads tool definitions.

---
## Tested and built on MacOS
