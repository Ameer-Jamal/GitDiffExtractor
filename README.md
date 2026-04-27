# **Git Diff Extractor: AI-Powered Insight Through Git Diffs**

### **Overview**

The **Git Diff Extractor** is a powerful desktop application designed to simplify the process of understanding and communicating changes made in Git repositories. Whether you're collaborating with team members or using AI tools to analyze code modifications, this app makes it easy to extract, search, and interpret **Git diffs** in a clear and structured way.
<img width="819" height="949" alt="image" src="https://github.com/user-attachments/assets/5625785f-8f7c-4e7d-9b84-200467c74a6c" />

---

## **Why I Built This?**
The core inspiration behind this tool is **bridging the gap between developers and AI-driven tools**. While Git and version control systems are vital for tracking code changes, understanding the context behind these changes can be tricky. This tool aims to:
- **Streamline communication between you and AI tools** (like ChatGPT) by providing them with **Git diffs** for deeper analysis.
- Help you **understand** what was changed, why it was changed, and how it impacts the broader project—all through concise, easy-to-read diffs.
- Give you a **visual comparison** between different commits, especially **pull requests** (PRs), so you can dive deeper into how specific tasks were implemented or resolved.

---

## **Key Features**

1. **Extract Git Diffs**: Extract diffs between two Git commits (especially focused on pull requests) and easily view the code changes made in those commits.

2. **Intelligent PR Display**: Pull requests are displayed in a structured way. Click on any PR to view the detailed diff and even auto-insert commit hashes for further analysis.

3. **Search PRs Easily**: Filter and search through PRs using keywords, commit hashes, or other metadata to quickly find the changes you're looking for.

4. **Highlighting coming soon**: The app supports beautifully colored diffs with syntax highlighting, making it easy to understand what lines were added, removed, or modified.

5. **Smart Hash Extraction**: Uses robust regex-based matching to ensure that **Git commit hashes** are extracted correctly, ensuring reliability even when working with large repositories.

6. **Provider-Based Repository Discovery**: Configure Bitbucket or GitHub credentials in **Settings**, discover accessible repositories, and activate one or many repositories without manual local-folder selection.

7. **Multi-Repository Workflows**: Run PR and branch workflows across selected repositories with clear repository context in results.

8. **Contribution History Tab**:
   - Query merged PRs, commits, or merged PRs + standalone commits
   - Scope by current repo, selected repos, or all repos in provider context
   - Filter by developer identity, date range presets/custom range, text search, branch, and bot exclusion
   - Select multiple developer aliases in one query (OR matching)
   - View summary metrics including `Fully scanned: X/Y`
   - Export to CSV, JSON, and Markdown (including PR descriptions)

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
   - Once you have the diff displayed, you can copy it and interact with AI tools like ChatGPT to get insights on the changes, ask questions, or receive suggestions.

---

## **Contribution History Notes**

- **Summary-first output**: No inline code diffs by default; focus is historical work reconstruction.
- **Titles/messages only mode**: Keeps output compact for reporting and AI prompting.
- **Rate-limit resilience**: Bitbucket scans use throttling, retry/backoff, and continuation logic to improve completeness.
- **Scan completeness signal**: Summary shows `Fully scanned: X/Y` so you can quickly see whether a run was partial.

---

## **Why Use Git Diff Extractor?**

- **Time-saving**: Quickly understand what was changed in a pull request without diving into endless logs.
- **AI Assistance**: Get AI insights into diffs and how changes were made, empowering you with more understanding and context.
- **Structured and Clear PR Viewing**: PRs are clearly displayed with commit hashes, making it easy to navigate and interpret.
- **Collaborate Better**: Whether you're in a team or just trying to recall why a change was made, this app simplifies communication and understanding.

---

## **Installation**

To run the app, follow these steps:

1. **Install Dependencies**:
   Make sure you have Python and PyQt5 installed. You can install the dependencies using:

   ```bash
   pip install -r requirements.txt 
   
2. **Run the App**:
   Simply execute the app from your terminal: main.py
3.  Configure Your Repository:
4.  Select the directory of your Git repository and start analyzing your PRs with ease!

---
## Tested and built on MacOS
