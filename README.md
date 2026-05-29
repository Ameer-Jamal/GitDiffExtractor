# **RepoLens: AI-Ready Repository and PR Context**

### **Overview**

**RepoLens** is a desktop application and local MCP server for collecting repository context that AI tools can use directly. It helps you inspect pull requests, generate diffs, query contribution history, and expose that same data to MCP-compatible agents.

<div>
   <img width="1735" height="906" alt="Banner" src="https://github.com/user-attachments/assets/c06783ee-f186-4201-bce8-fe3e77d832bf" />
   <img width="1074" height="917" alt="image" src="https://github.com/user-attachments/assets/11f8c2eb-4ba7-4490-811e-702f9eb3fee4" />
</div>

---

## **Why It Exists**

Git providers already contain the context an AI needs, but that context is scattered across commits, PRs, branches, repositories, and contribution history. RepoLens gives you one place to gather that context and one MCP server that AI clients can call directly.

---

## **Key Features**

1. **PR and Commit Diffs**: Extract diffs between commits or pull request branches and view the changes in a structured way.

2. **Provider Repository Discovery**: Configure Bitbucket or GitHub credentials in **Settings**, discover accessible repositories, and activate one or many repositories without manual local-folder selection.

3. **Multi-Repository Workflows**: Run PR, branch, ticket, and history workflows across selected repositories with repository context included in results.

4. **Pull Request Filtering**: Filter PRs by state, text search, and developer identity. The developer filter can use `Any developer`, `Me`, or a provider username/display name/email.

5. **Contribution History**: Query merged PRs, commits, or both by developer, date range, repository scope, branch, and text. Export results to CSV, JSON, or Markdown.

6. **MCP Server Mode**: Expose repository discovery, selected repositories, PR lookup, ticket lookup, diffs, and contribution history as local MCP tools for AI clients.

---

## **How to Use the App**

1. **Install dependencies**:

   ```bash
   pip install -r requirements.txt
   ```

2. **Run the desktop app**:

   ```bash
   python3 main.py
   ```

3. **Configure provider access**:

   - Open `Settings`.
   - Choose `Bitbucket` or `GitHub`.
   - Enter credentials.
   - Discover repositories.
   - Select one or more active repositories.

4. **Use the main tabs**:

   - `PR Lens`: list/search PRs, filter by developer, and generate PR or commit diffs.
   - `Branch Commit Viewer`: inspect branch commits.
   - `Create PR`: create pull requests from configured repositories.
   - `Contribution History`: reconstruct work by developer, repository, branch, and date.
   - `Settings`: manage provider config, repository discovery, selected repos, and output paths.

---

## **MCP Server**

This repo includes a local stdio MCP server at `mcp_server.py`. Any MCP-compatible AI client can launch it and use RepoLens as a tool source.

The MCP server is read-only for provider data. It may clone or fetch local repositories when a diff tool needs a checkout, but it does not edit repositories, create PRs, or change provider data.

### **Tools**

- `get_active_context`
- `list_repositories`
- `get_selected_repositories`
- `list_pull_requests`
- `list_my_pull_requests`
- `find_pull_requests_by_ticket`
- `get_ticket_diffs`
- `get_pr_diff`
- `get_commit_diff`
- `query_contribution_history` (with fuzzy repository resolution and diagnostic info)
- `find_pr_for_commit` (Link commits to their parent PRs)
- `search_contributions_by_ticket` (Deep search across repositories for a ticket)
- `analyze_file_history` (Unified commit and PR history for a specific file)
- `get_pr_context` (Unified tool to get PR metadata and diff from a URL, ticket, or title)
- `list_developer_candidates`

### **General Setup**

Typical flow:

1. Configure provider credentials and selected repositories in the desktop app, or pass them as environment variables.
2. Register `mcp_server.py` with your MCP-compatible client.
3. Restart the client so it starts a fresh MCP server process.
4. Ask the AI to use the RepoLens MCP tools.

You do not need to reinstall/register the MCP server after code changes when the command path stays the same. You do need to restart the MCP client so it reloads the server process and tool definitions.

### **Register The Local Server**

Below are instructions for connecting the **RepoLens MCP** to popular AI platforms. Use the absolute path to `mcp_server.py`: `/Users/ajamal/Documents/PythonProjects/RepoLens/mcp_server.py`.

#### **Claude Code**
Run this command in your terminal:
```bash
claude mcp add repolens --command "python3 /Users/ajamal/Documents/PythonProjects/RepoLens/mcp_server.py"
```
Then enter `/mcp` in Claude Code to verify and authenticate.

#### **Claude Desktop**
1. Go to **Settings** → **Connectors** → **Add custom connector**.
2. Alternatively, edit your `claude_desktop_config.json` (usually in `~/Library/Application Support/Claude/` on macOS):
```json
{
  "mcpServers": {
    "repolens": {
      "command": "python3",
      "args": ["/Users/ajamal/Documents/PythonProjects/RepoLens/mcp_server.py"]
    }
  }
}
```

#### **Cursor**
1. Go to **Settings** → **Cursor Settings**.
2. Select **Tools & MCPs** → **Connect**.
3. Choose `command` (stdio) as the transport.
4. Name: `repoLens`
5. Command: `python3`
6. Arguments: `/Users/ajamal/Documents/PythonProjects/RepoLens/mcp_server.py`

#### **ChatGPT**
1. Turn on **Developer Mode**.
2. Go to **Settings** → **Apps** → **Create app**.
3. Provide the command and arguments for the RepoLens server.

#### **Other platforms**
You can connect to RepoLens on any platform that supports the **Model Context Protocol** via local `stdio` transport. Just point the client at:
- **Command**: `python3`
- **Arguments**: `/Users/ajamal/Documents/PythonProjects/RepoLens/mcp_server.py`

### **Environment Variable Overrides**

The server reuses saved desktop-app config by default. You can override config with environment variables:

- `REPOLENS_PROVIDER`
- `REPOLENS_BITBUCKET_USERNAME`
- `REPOLENS_BITBUCKET_APP_PASSWORD`
- `REPOLENS_BITBUCKET_WORKSPACE`
- `REPOLENS_GITHUB_OWNER`
- `REPOLENS_GITHUB_REPO`
- `REPOLENS_GITHUB_TOKEN`
- `REPOLENS_MANAGED_REPO_ROOT`
- `REPOLENS_SELECTED_REPOSITORIES_JSON`
- `REPOLENS_ACTIVE_REPO_PROVIDER`
- `REPOLENS_ACTIVE_REPO_ID`
- `REPOLENS_ACTIVE_REPO_NAME`
- `REPOLENS_ACTIVE_REPO_OWNER`
- `REPOLENS_ACTIVE_REPO_SLUG`
- `REPOLENS_ACTIVE_REPO_CLONE_URL`
- `REPOLENS_ACTIVE_REPO_HTML_URL`
- `REPOLENS_ACTIVE_REPO_LOCAL_DIR`

Example:

```bash
REPOLENS_PROVIDER=bitbucket \
REPOLENS_BITBUCKET_USERNAME=your-username \
REPOLENS_BITBUCKET_APP_PASSWORD=your-app-password \
REPOLENS_BITBUCKET_WORKSPACE=your-workspace \
python3 /Users/ajamal/Documents/PythonProjects/RepoLens/mcp_server.py
```

---

## **AI Test Prompts**

Use this prompt in a new AI client after registering the MCP server:

```text
Use the RepoLens MCP server to test basic functionality.

1. Call get_active_context and tell me the configured provider, active repository, selected repository count, and whether config came from app config or overrides.
2. Call get_selected_repositories and list the selected repository names.
3. Call list_pull_requests for the active repository with filter_mode="open" and summarize the count plus the first 3 PR ids/titles/states.
4. Call find_pull_requests_by_ticket with ticket="RU-25463" and summarize any matching PRs.
5. Do not call get_pr_diff yet unless I explicitly ask, because diffs can be large.
6. If any tool fails, report the exact tool name and error.
```

Developer PR prompt:

```text
Use the RepoLens MCP server to list my open pull requests across selected repositories.

Call list_my_pull_requests with:
scope="selected"
filter_mode="open"

Return the repo, PR id, title, source branch, target branch, and link for each PR.
```

Ticket lookup prompt:

```text
Use the RepoLens MCP server to find pull requests for ticket RU-25463. Search selected repositories. If there are multiple PRs, list each PR id, title, repo, state, source branch, destination branch, and link.
```

Specific repository prompt:

```text
Use the RepoLens MCP server to check open PRs in pdf-repo, even if it is not the active or selected repository.

Call list_pull_requests with:
scope="specific:pdf-repo"
filter_mode="open"

Return PR id, title, state, source branch, destination branch, author, and link.
```

For an explicit owner/workspace, use `scope="specific:WORKSPACE_OR_OWNER/pdf-capturing-service-repo"`.
RepoLens treats `specific:` as an override selector: it searches active, selected, and discovered repositories for a matching slug, name, or `owner/slug`, then uses that matched repository.

Multi-ticket QA impact prompt:

```text
Use the RepoLens MCP server to call get_ticket_diffs with tickets_json=["RU-25463", "RU-00000"] and scope="selected". Analyze the returned PR diffs and create this table:

| Ticket # | QA Impact | Notes/Comments |
|---|---|---|

Rules:
- Combine multiple PRs for the same ticket into one row.
- QA Impact should describe what QA should test, not just which files changed.
- Notes/Comments should include PR ids, repository names, and any uncertainty.
- If no PRs are found for a ticket, say that directly.
- If any diff is truncated or failed, mention that in Notes/Comments.
```

---

## **Notes**

- MCP is the protocol/integration point; RepoLens is not tied to one AI client.
- Developer filters use provider-side author search where supported. If the provider API cannot filter by author efficiently, RepoLens narrows by provider-supported filters first and then applies local author matching.
- Managed repositories default to `~/.repolens/repos`.
- Existing settings and repository config from older installs are migrated into the RepoLens namespace on startup.
- Tested and built on macOS.
