import os
import platform
import re
import subprocess
import textwrap

import requests
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QLabel, QLineEdit,
                             QPushButton, QFileDialog, QMessageBox, QHBoxLayout, QListWidget,
                             QListWidgetItem, QTabWidget, QRadioButton, QButtonGroup)
from BranchCommitViewer import BranchCommitViewer
from ConfigManager import ConfigManager
from CreatePrTab import CreatePRTab
from SettingsTab import SettingsTab

DEFAULT_BITBUCKET_WORKSPACE = os.environ.get('BITBUCKET_WORKSPACE', 'etqdev').strip() or 'etqdev'

# CONSTS:
INPUT_ERROR = "Input Error"


class GitDiffExtractor(QWidget):

    def __init__(self):
        super().__init__()
        # Initialize the ConfigManager
        self.run_button = None
        self.search_input = None
        self.all_diffs_radio = None
        self.only_merges_radio = None
        self.only_pr_radio = None
        self.radio_group = None
        self.only_merges_checkbox = None
        self.pr_button = None
        self.config_manager = ConfigManager()
        self.default_output_dir = self.config_manager.get_output_dir()
        self.prs = []  # List to hold PR metadata dictionaries
        # Initialize the QTabWidget
        self.tabs = QTabWidget()

        # Create the PR Diff Extractor UI and Branch Commit Viewer UI as separate widgets
        self.initUI()

        # Build tabs
        self.pr_tab_widget = self.prExtractDiffWidget()
        self.branch_viewer = BranchCommitViewer(self.config_manager)
        self.branch_viewer.repoChanged.connect(self.on_repo_changed)
        self.create_pr_tab = CreatePRTab(self.config_manager)
        self.create_pr_tab.repoChanged.connect(self.on_repo_changed)
        self.settings_tab = SettingsTab(self.config_manager)
        self.settings_tab.providerChanged.connect(self._on_provider_updated)
        self.settings_tab.settingsUpdated.connect(self._on_settings_updated)

        # Add both tabs to the QTabWidget
        self.tabs.addTab(self.pr_tab_widget, "PR Diff Extractor")  # Default tab
        self.tabs.addTab(self.branch_viewer, "Branch Commit Viewer")
        self.tabs.addTab(self.create_pr_tab, "Create PR")
        self.tabs.addTab(self.settings_tab, "Settings")

        # Set the layout for the main window
        main_layout = QVBoxLayout()
        main_layout.addWidget(self.tabs)
        self.setLayout(main_layout)

        self.apply_repo_config()

    def initUI(self):
        self.setWindowTitle('Git Diff Extractor')
        self.setGeometry(500, 500, 800, 900)

    def prExtractDiffWidget(self):
        """Create the widget for PR Extract Diff functionality."""
        pr_widget = QWidget()
        layout = QVBoxLayout(pr_widget)

        # Repository Directory
        repo_layout = QHBoxLayout()
        self.repo_label = QLabel('Repository Directory:')
        repo_layout.addWidget(self.repo_label)
        self.repo_input = QLineEdit(self)
        self.repo_input.setText(self.config_manager.get_repo_dir())  # Load last used repo dir
        self.repo_input.editingFinished.connect(self._handle_repo_edit)
        repo_layout.addWidget(self.repo_input)
        self.repo_button = QPushButton('Browse', self)
        self.repo_button.clicked.connect(self.browseRepo)
        repo_layout.addWidget(self.repo_button)
        layout.addLayout(repo_layout)

        # Commit Hashes
        commit_layout = QHBoxLayout()
        self.commit_label = QLabel('Commit Hashes (comma or space-separated):')
        commit_layout.addWidget(self.commit_label)
        self.commit_input = QLineEdit(self)
        self.commit_input.editingFinished.connect(self._store_commit_hashes)
        commit_layout.addWidget(self.commit_input)
        layout.addLayout(commit_layout)

        # Output Directory
        output_layout = QHBoxLayout()
        self.output_label = QLabel('Output Directory:')
        output_layout.addWidget(self.output_label)
        self.output_input = QLineEdit(self)
        self.output_input.setText(self.config_manager.get_output_dir())  # Load last used output dir
        self.output_input.editingFinished.connect(self._store_output_dir)
        output_layout.addWidget(self.output_input)
        self.output_button = QPushButton('Browse', self)
        self.output_button.clicked.connect(self.browseOutput)
        output_layout.addWidget(self.output_button)
        layout.addLayout(output_layout)

        # Search Bar for PRs
        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("Search PRs")
        self.search_input.textChanged.connect(self.searchPRs)
        layout.addWidget(self.search_input)

        # List of Pull Requests
        self.pr_list = QListWidget(self)
        self.pr_list.itemClicked.connect(self.onPRClick)
        self.pr_list.itemDoubleClicked.connect(self.generateDiff)
        layout.addWidget(self.pr_list)

        # Load PRs Button
        self.pr_button = QPushButton('List Diffs', self)
        self.pr_button.clicked.connect(self.listPRs)
        layout.addWidget(self.pr_button)

        # Add a radio for filtering merge commits
        self.only_pr_radio = QRadioButton('Only Pull Requests')
        self.only_merges_radio = QRadioButton('Only Merges')
        self.all_diffs_radio = QRadioButton('All Diffs')

        # Default to showing open pull requests
        self.only_pr_radio.setChecked(True)

        # Group the radio buttons to ensure only one can be selected
        self.radio_group = QButtonGroup()
        self.radio_group.addButton(self.only_pr_radio)
        self.radio_group.addButton(self.only_merges_radio)
        self.radio_group.addButton(self.all_diffs_radio)

        # Add the radio buttons to the layout
        layout.addWidget(self.only_pr_radio)
        layout.addWidget(self.only_merges_radio)
        layout.addWidget(self.all_diffs_radio)

        # Generate Diff Button
        self.run_button = QPushButton('Generate Diff', self)
        self.run_button.clicked.connect(self.generateDiff)
        layout.addWidget(self.run_button)

        pr_widget.setLayout(layout)  # Set the layout for the pr_widget
        return pr_widget

    def getPRDiffs(self):
        repo_dir = self.repo_input.text()
        pr_merge_commit = self.commit_input.text().strip()
        output_dir = self.output_input.text()

        if not repo_dir or not pr_merge_commit or not output_dir:
            QMessageBox.warning(self, INPUT_ERROR, "All fields must be filled out.")
            return

        try:
            os.chdir(repo_dir)

            # Get all commits related to the PR (before the merge commit)
            result = subprocess.run(['git', 'log', '--pretty=%H', f'{pr_merge_commit}^1'],
                                    capture_output=True, text=True)
            commit_hashes = result.stdout.strip().split()

            if not commit_hashes:
                QMessageBox.warning(self, "Error",
                                    f"No commits found for the specified merge commit {pr_merge_commit}.")
                return

            # Generate diffs for each commit related to the PR
            for commit_hash in commit_hashes:
                diff_file_path = os.path.join(output_dir, f'{commit_hash}_diff.txt')
                with open(diff_file_path, 'w') as diff_file:
                    # Get diff from previous commit to current commit
                    subprocess.run(['git', 'diff', f'{commit_hash}^', commit_hash], stdout=diff_file)
                self.openFile(diff_file_path)

            QMessageBox.information(self, "Success", "Diff files created and opened.")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"An error occurred: {str(e)}")

    def browseRepo(self):
        directory = self.selectDirectory("Select Repository Directory")
        if directory:
            self.repo_input.setText(directory)
            self.on_repo_changed(directory)

    def browseOutput(self):
        directory = self.selectDirectory("Select Output Directory")
        if directory:
            self.output_input.setText(directory)
            self.config_manager.set_output_dir(directory)  # Save to config

    def selectDirectory(self, title):
        """ Open a standard directory selection dialog using QFileDialog. """
        return QFileDialog.getExistingDirectory(self, title)

    def generateDiff(self):
        repo_dir = self.repo_input.text().strip()
        output_dir = self.output_input.text().strip()

        if not repo_dir or not output_dir:
            QMessageBox.warning(self, INPUT_ERROR, "Repository and output directories must be provided.")
            return

        os.makedirs(output_dir, exist_ok=True)

        selected_item = self.pr_list.currentItem()
        if selected_item is not None:
            pr_data = selected_item.data(Qt.UserRole)
            if isinstance(pr_data, dict):
                try:
                    self._generate_pr_diff(pr_data, repo_dir, output_dir)
                except Exception as exc:
                    QMessageBox.critical(self, "Error", f"Failed to generate PR diff:\n{exc}")
                return

        commit_text = self.commit_input.text()
        commit_hashes = commit_text.replace(',', ' ').split()
        self.config_manager.set_commit_hashes(commit_text.strip())

        if not commit_hashes:
            QMessageBox.warning(self, INPUT_ERROR, "Enter at least one commit hash or select a pull request.")
            return

        try:
            for commit_hash in commit_hashes:
                parents_result = subprocess.run(
                    ['git', 'rev-list', '--parents', '-n', '1', commit_hash],
                    capture_output=True,
                    text=True,
                    cwd=repo_dir,
                    check=True,
                )
                parents = parents_result.stdout.strip().split()

                if len(parents) == 1:
                    QMessageBox.warning(
                        self,
                        "Warning",
                        f"The commit {commit_hash} has no parents (initial commit). Skipping.",
                    )
                    continue

                parent_commit = parents[1]
                diff_file_path = os.path.join(output_dir, f'{commit_hash}_diff.txt')
                with open(diff_file_path, 'w', encoding='utf-8') as diff_file:
                    subprocess.run(
                        ['git', 'diff', parent_commit, commit_hash],
                        stdout=diff_file,
                        cwd=repo_dir,
                        check=True,
                    )

                self.openFile(diff_file_path)

            QMessageBox.information(self, "Success", "Diff files created and opened.")

        except subprocess.CalledProcessError as exc:
            QMessageBox.critical(self, "Error", f"Git command failed:\n{exc.stderr or exc}")
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"An unexpected error occurred:\n{exc}")

    def listPRs(self):
        repo_dir = self.repo_input.text().strip()

        if not repo_dir:
            QMessageBox.warning(self, INPUT_ERROR, "Repository directory must be filled out.")
            return

        provider = self.config_manager.get_provider() or 'bitbucket'
        filter_mode = self._selected_filter()

        try:
            if provider == 'github':
                provider_config = self._get_github_config()
                if not provider_config:
                    return
                prs = self._fetch_github_pull_requests(filter_mode, provider_config)
            else:
                provider_config = self._get_bitbucket_config()
                if not provider_config:
                    return
                prs = self._fetch_bitbucket_pull_requests(filter_mode, provider_config)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to retrieve pull requests:\n{exc}")
            return

        self.prs = prs
        if not prs:
            QMessageBox.information(self, "No Results", "No pull requests matched the current filters.")

        self.displayPRs()

    def displayPRs(self, prs=None):
        """Display pull requests in the list widget."""
        self.pr_list.clear()
        records = prs if prs is not None else self.prs

        for pr in records:
            pr_id = pr.get('id', 'Unknown')
            raw_title = pr.get('title') or ''
            title = raw_title.strip() or '(No title)'
            state = (pr.get('state') or 'UNKNOWN').upper()
            source_branch = pr.get('source_branch') or 'unknown'
            destination_branch = pr.get('destination_branch') or 'unknown'
            author = pr.get('author') or 'Unknown author'
            summary = textwrap.shorten(title, width=100, placeholder='…')
            provider_label = (pr.get('provider') or '').capitalize()

            header = f"PR #{pr_id} · {state}"
            if provider_label:
                header = f"{header} [{provider_label}]"

            item_text = (
                f"{header}\n"
                f"{source_branch} ⟶ {destination_branch}\n"
                f"Title: {summary}\n"
                f"Author: {author}\n"
                f"{'_' * 75}"
            )

            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, pr)
            self.pr_list.addItem(item)

    def searchPRs(self):
        """Filter PRs based on the search input."""
        query = self.search_input.text().strip().lower()
        if not query:
            self.displayPRs()
            return

        filtered = []
        for pr in self.prs:
            fields = [
                str(pr.get('id', '')),
                pr.get('title') or '',
                pr.get('state') or '',
                pr.get('source_branch') or '',
                pr.get('destination_branch') or '',
                pr.get('author') or '',
            ]
            descriptor = ' '.join(f.lower() for f in fields)
            if query in descriptor:
                filtered.append(pr)

        self.displayPRs(filtered)

    def _on_settings_updated(self):
        self.apply_repo_config()

    def _on_provider_updated(self, provider):
        provider = (provider or 'bitbucket').lower()
        self.create_pr_tab.setEnabled(provider == 'bitbucket')
        self.prs = []
        self.pr_list.clear()

    def _selected_filter(self):
        if self.only_pr_radio.isChecked():
            return 'open'
        if self.only_merges_radio.isChecked():
            return 'merged'
        return 'all'

    def _get_bitbucket_config(self):
        username = (self.config_manager.get_bitbucket_username() or '').strip()
        password = (self.config_manager.get_bitbucket_app_password() or '').strip()
        slug = (self.config_manager.get_repo_slug() or '').strip()
        workspace = (self.config_manager.get_bitbucket_workspace() or '').strip()
        workspace = workspace or DEFAULT_BITBUCKET_WORKSPACE

        if not username or not password:
            QMessageBox.warning(
                self,
                "Bitbucket Configuration",
                "Bitbucket username and app password are required."
                "\nPlease update them in the Settings tab.",
            )
            self.tabs.setCurrentWidget(self.settings_tab)
            self.settings_tab.focus_bitbucket_credentials()
            return None

        if not slug:
            QMessageBox.warning(
                self,
                "Bitbucket Configuration",
                "Repository slug is required."
                "\nPlease fill it in under the Settings tab.",
            )
            self.tabs.setCurrentWidget(self.settings_tab)
            self.settings_tab.focus_bitbucket_slug()
            return None

        return {
            'username': username,
            'password': password,
            'slug': slug,
            'workspace': workspace,
        }

    def _get_github_config(self):
        owner = (self.config_manager.get_github_owner() or '').strip()
        repo = (self.config_manager.get_github_repo() or '').strip()
        token = (self.config_manager.get_github_token() or '').strip()

        if not owner or not repo:
            QMessageBox.warning(
                self,
                "GitHub Configuration",
                "GitHub owner and repository are required."
                "\nPlease fill them in via the Settings tab.",
            )
            self.tabs.setCurrentWidget(self.settings_tab)
            if not owner:
                self.settings_tab.focus_github_owner()
            else:
                self.settings_tab.focus_github_repo()
            return None

        headers = {'Accept': 'application/vnd.github+json'}
        if token:
            headers['Authorization'] = f'token {token}'

        return {
            'owner': owner,
            'repo': repo,
            'headers': headers,
        }

    def _fetch_bitbucket_pull_requests(self, filter_mode, config):
        username = config['username']
        password = config['password']
        slug = config['slug']
        workspace = config['workspace']

        url = f"https://api.bitbucket.org/2.0/repositories/{workspace}/{slug}/pullrequests"
        params = [('pagelen', '50')]
        if filter_mode == 'open':
            states = ['OPEN']
        elif filter_mode == 'merged':
            states = ['MERGED']
        else:
            states = ['OPEN', 'MERGED']

        params.extend(('state', state) for state in states)

        prs = []
        next_url = url

        while next_url:
            response = requests.get(
                next_url,
                params=params if next_url == url else None,
                auth=(username, password),
                timeout=15,
            )
            response.raise_for_status()

            data = response.json()
            for pr_record in data.get('values', []):
                prs.append(self._map_bitbucket_pr(pr_record))

            next_url = data.get('next')
            params = None

        return prs

    @staticmethod
    def _map_bitbucket_pr(pr_record):
        source = pr_record.get('source') or {}
        destination = pr_record.get('destination') or {}
        links = pr_record.get('links') or {}
        merge_commit = pr_record.get('merge_commit') or {}
        summary = pr_record.get('summary') or {}

        return {
            'id': pr_record.get('id'),
            'title': pr_record.get('title'),
            'state': (pr_record.get('state') or '').upper(),
            'author': ((pr_record.get('author') or {}).get('display_name')),
            'source_branch': (source.get('branch') or {}).get('name'),
            'destination_branch': (destination.get('branch') or {}).get('name'),
            'source_commit': (source.get('commit') or {}).get('hash'),
            'destination_commit': (destination.get('commit') or {}).get('hash'),
            'merge_commit': merge_commit.get('hash'),
            'link': (links.get('html') or {}).get('href'),
            'description': summary.get('raw') or pr_record.get('description'),
            'updated_on': pr_record.get('updated_on'),
            'provider': 'bitbucket',
        }

    def _fetch_github_pull_requests(self, filter_mode, config):
        owner = config['owner']
        repo = config['repo']
        headers = config['headers']

        url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
        if filter_mode == 'open':
            state_param = 'open'
        elif filter_mode == 'merged':
            state_param = 'closed'
        else:
            state_param = 'all'

        params = {'per_page': 50, 'state': state_param}
        prs = []
        next_url = url

        while next_url:
            response = requests.get(
                next_url,
                params=params if next_url == url else None,
                headers=headers,
                timeout=15,
            )
            response.raise_for_status()

            data = response.json()

            for pr_record in data:
                is_merged = bool(pr_record.get('merged_at'))
                state = pr_record.get('state', 'open')

                if filter_mode == 'merged' and not is_merged:
                    continue
                if filter_mode == 'open' and state != 'open':
                    continue

                prs.append(self._map_github_pr(pr_record))

            next_url = self._github_next_link(response.headers.get('Link'))
            params = None

        return prs

    @staticmethod
    def _map_github_pr(pr_record):
        head = pr_record.get('head') or {}
        base = pr_record.get('base') or {}
        user = pr_record.get('user') or {}

        merged = bool(pr_record.get('merged_at'))
        state = 'MERGED' if merged else (pr_record.get('state') or 'open').upper()

        return {
            'id': pr_record.get('number'),
            'title': pr_record.get('title'),
            'state': state,
            'author': user.get('login'),
            'source_branch': head.get('ref'),
            'destination_branch': base.get('ref'),
            'source_commit': head.get('sha'),
            'destination_commit': base.get('sha'),
            'merge_commit': pr_record.get('merge_commit_sha'),
            'link': pr_record.get('html_url'),
            'description': pr_record.get('body'),
            'updated_on': pr_record.get('updated_at'),
            'provider': 'github',
        }

    @staticmethod
    def _github_next_link(link_header):
        if not link_header:
            return None

        parts = link_header.split(',')
        for part in parts:
            section = part.strip().split(';')
            if len(section) < 2:
                continue
            url_part = section[0].strip()
            rel_part = section[1].strip()
            if rel_part == 'rel="next"':
                return url_part.strip('<>')

        return None

    def _generate_pr_diff(self, pr, repo_dir, output_dir):
        pr_id = pr.get('id', 'unknown')
        title = pr.get('title') or ''
        state = pr.get('state') or ''
        source_branch = pr.get('source_branch')
        destination_branch = pr.get('destination_branch')

        try:
            subprocess.run(['git', 'fetch', 'origin'], cwd=repo_dir, check=True, capture_output=True)
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or b'').decode('utf-8', 'ignore') if isinstance(exc.stderr, bytes) else (
                        exc.stderr or '')
            raise RuntimeError(f"git fetch failed: {stderr.strip() or exc}") from exc

        resolved_source = self._resolve_commit(repo_dir, pr.get('source_commit'), source_branch)
        resolved_destination = self._resolve_commit(repo_dir, pr.get('destination_commit'), destination_branch)

        if not resolved_source:
            raise RuntimeError(f"Unable to resolve the source commit for PR #{pr_id} ({title}).")

        if not resolved_destination:
            raise RuntimeError(f"Unable to resolve the destination commit for PR #{pr_id} ({title}).")

        merge_base = self._merge_base(repo_dir, resolved_destination, resolved_source) or resolved_destination

        diff_path = self._build_pr_diff_filename(pr, output_dir)

        try:
            with open(diff_path, 'w', encoding='utf-8') as diff_file:
                subprocess.run(
                    ['git', 'diff', merge_base, resolved_source],
                    cwd=repo_dir,
                    stdout=diff_file,
                    check=True,
                )
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or b'').decode('utf-8', 'ignore') if isinstance(exc.stderr, bytes) else (
                        exc.stderr or '')
            raise RuntimeError(f"git diff failed: {stderr.strip() or exc}") from exc

        QMessageBox.information(
            self,
            "Success",
            f"Diff for PR #{pr_id} ({state}) saved to {diff_path}.",
        )
        self.openFile(diff_path)

    def _resolve_commit(self, repo_dir, commit_hash, branch_name):
        candidates = []
        if commit_hash:
            candidates.append(commit_hash)
        if branch_name:
            candidates.append(branch_name)
            if not branch_name.startswith('origin/'):
                candidates.append(f'origin/{branch_name}')

        for candidate in candidates:
            resolved = self._verify_commit(repo_dir, candidate)
            if resolved:
                return resolved

        return None

    @staticmethod
    def _verify_commit(repo_dir, identifier):
        if not identifier:
            return None

        try:
            result = subprocess.run(
                ['git', 'rev-parse', '--verify', f'{identifier}^{{commit}}'],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return None

    @staticmethod
    def _merge_base(repo_dir, destination_commit, source_commit):
        if not destination_commit or not source_commit:
            return None

        try:
            result = subprocess.run(
                ['git', 'merge-base', destination_commit, source_commit],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            merge_base = result.stdout.strip()
            return merge_base if merge_base else None
        except subprocess.CalledProcessError:
            return None

    def _build_pr_diff_filename(self, pr, output_dir):
        pr_id = pr.get('id', 'unknown')
        state = (pr.get('state') or 'unknown').lower()
        safe_title = self._safe_filename(pr.get('title'), fallback='pr')
        filename = f"pr_{pr_id}_{state}_{safe_title}.diff"
        return os.path.join(output_dir, filename)

    @staticmethod
    def _safe_filename(value, fallback='file'):
        text = (value or '').strip()
        if not text:
            text = fallback
        sanitized = re.sub(r'[^A-Za-z0-9._-]+', '_', text)
        sanitized = sanitized.strip('_')
        if not sanitized:
            sanitized = fallback
        return sanitized[:60]

    def onPRClick(self, item):
        """Populate the commit input based on the selected PR."""
        pr = item.data(Qt.UserRole)
        if isinstance(pr, dict):
            commit_hash = pr.get('merge_commit') or pr.get('source_commit') or ''
            self.commit_input.setText(commit_hash)
            self.config_manager.set_commit_hashes(commit_hash)
        else:
            commit_hash = item.data(Qt.UserRole)
            self.commit_input.setText(commit_hash)
            self.config_manager.set_commit_hashes(commit_hash)

    @staticmethod
    def openFile(file_path):
        if platform.system() == "Darwin":
            subprocess.run(['open', file_path])
        elif platform.system() == "Windows":
            os.startfile(file_path)
        else:
            subprocess.run(['xdg-open', file_path])

    # ------------------------------------------------------------------
    # Configuration synchronisation
    def on_repo_changed(self, repo_dir):
        repo_dir = repo_dir.strip()
        self.config_manager.set_repo_dir(repo_dir)
        self.apply_repo_config()

    def apply_repo_config(self):
        repo_dir = self.config_manager.get_repo_dir()
        output_dir = self.config_manager.get_output_dir()
        commits = self.config_manager.get_commit_hashes()

        self._set_line_edit_text(self.repo_input, repo_dir)
        self._set_line_edit_text(self.output_input, output_dir)
        self._set_line_edit_text(self.commit_input, commits)

        if hasattr(self, 'settings_tab') and self.settings_tab:
            self.settings_tab.apply_repo_config()

        self.branch_viewer.apply_repo_config()
        self.create_pr_tab.apply_repo_config()
        provider = (self.config_manager.get_provider() or 'bitbucket').lower()
        self.create_pr_tab.setEnabled(provider == 'bitbucket')

    @staticmethod
    def _set_line_edit_text(line_edit, value):
        block = line_edit.blockSignals(True)
        line_edit.setText(value)
        line_edit.blockSignals(block)

    def _handle_repo_edit(self):
        self.on_repo_changed(self.repo_input.text())

    def _store_commit_hashes(self):
        self.config_manager.set_commit_hashes(self.commit_input.text().strip())

    def _store_output_dir(self):
        self.config_manager.set_output_dir(self.output_input.text().strip())


if __name__ == '__main__':
    app = QApplication([])
    extractor = GitDiffExtractor()
    extractor.show()
    app.exec_()
