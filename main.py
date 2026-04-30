import os
import platform
import re
import subprocess
import textwrap
import time

import requests
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QLabel, QLineEdit,
                             QPushButton, QFileDialog, QMessageBox, QHBoxLayout, QListWidget,
                             QListWidgetItem, QTabWidget, QRadioButton, QButtonGroup, QProgressDialog)
from BranchCommitViewer import BranchCommitViewer
from ConfigManager import ConfigManager
from ContributionHistoryTab import ContributionHistoryTab
from CreatePrTab import CreatePRTab
from diff_service import DiffService
from ListDelegates import PRListDelegate, UI_ROLE
from PRAggregationService import PRAggregationService
from pull_request_service import PullRequestService
from RepositoryProvider import RepositoryProvider
from SettingsTab import SettingsTab
from TaskRunner import TaskRunner

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
        self.load_more_button = None
        self._load_more_label = ''
        self.config_manager = ConfigManager()
        self.default_output_dir = self.config_manager.get_output_dir()
        self.prs = []  # List to hold PR metadata dictionaries
        self._pr_cache = {}
        self._pr_cache_ttl = 60  # seconds
        self._pagination_state = None
        self._pr_page_loading = False
        self._pr_search_timer = None
        self._last_remote_search_key = None
        self._remote_search_inflight = False
        self._current_provider = None
        self._current_filter_mode = None
        self._current_provider_config = None
        self._current_selected_repos = []
        self._current_cursor_state = {}
        self._repo_activation_in_progress = False
        self._repo_progress_dialog = None
        self._previous_tab_index = 0
        self._handling_tab_change = False
        self.task_runner = TaskRunner(self)
        self.pr_service = PullRequestService(self.config_manager)
        self.diff_service = DiffService()
        # Initialize the QTabWidget
        self.tabs = QTabWidget()

        # Create the PR Diff Extractor UI and Branch Commit Viewer UI as separate widgets
        self.initUI()

        # Build tabs
        self.pr_tab_widget = self.prExtractDiffWidget()
        self.branch_viewer = BranchCommitViewer(self.config_manager, self.task_runner)
        self.create_pr_tab = CreatePRTab(self.config_manager, self.task_runner)
        self.settings_tab = SettingsTab(self.config_manager, self.task_runner)
        self.contribution_history_tab = ContributionHistoryTab(self.config_manager, self.task_runner)
        self.settings_tab.providerChanged.connect(self._on_provider_updated)
        self.settings_tab.settingsUpdated.connect(self._on_settings_updated)
        self.settings_tab.activeRepositoriesChanged.connect(self._on_active_repositories_selected)

        # Add both tabs to the QTabWidget
        self.tabs.addTab(self.pr_tab_widget, "Diff Extractor")  # Default tab
        self.tabs.addTab(self.branch_viewer, "Branch Commit Viewer")
        self.tabs.addTab(self.create_pr_tab, "Create PR")
        self.tabs.addTab(self.contribution_history_tab, "Contribution History")
        self.tabs.addTab(self.settings_tab, "Settings")
        self._previous_tab_index = self.tabs.currentIndex()
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # Set the layout for the main window
        main_layout = QVBoxLayout()
        main_layout.addWidget(self.tabs)
        self.setLayout(main_layout)

        self.apply_repo_config()
        self._initialize_active_repository()

    def initUI(self):
        self.setWindowTitle('Git Diff Extractor')
        self.setGeometry(500, 500, 800, 900)

    def prExtractDiffWidget(self):
        """Create the widget for PR Extract Diff functionality."""
        pr_widget = QWidget()
        layout = QVBoxLayout(pr_widget)

        # Active Repository
        repo_layout = QHBoxLayout()
        self.repo_label = QLabel('Primary Repository Directory:')
        repo_layout.addWidget(self.repo_label)
        self.repo_input = QLineEdit(self)
        self.repo_input.setText(self.config_manager.get_repo_dir())
        self.repo_input.setReadOnly(True)
        self.repo_input.setPlaceholderText('Select active repository in Settings')
        repo_layout.addWidget(self.repo_input)
        layout.addLayout(repo_layout)

        # Commit Hashes
        commit_layout = QHBoxLayout()
        self.commit_label = QLabel('Commit Hashes (comma or space-separated):')
        commit_layout.addWidget(self.commit_label)
        self.commit_input = QLineEdit(self)
        self.commit_input.editingFinished.connect(self._store_commit_hashes)
        commit_layout.addWidget(self.commit_input)
        layout.addLayout(commit_layout)

        # Search Bar for PRs
        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("Search PRs")
        self.search_input.textChanged.connect(self._on_pr_search_text_changed)
        layout.addWidget(self.search_input)

        # List of Pull Requests
        self.pr_list = QListWidget(self)
        self.pr_list.itemClicked.connect(self.onPRClick)
        self.pr_list.itemDoubleClicked.connect(self.generateDiff)
        self.pr_list.verticalScrollBar().valueChanged.connect(self._on_pr_list_scrolled)
        self.pr_list.setItemDelegate(PRListDelegate(self.pr_list))
        layout.addWidget(self.pr_list)

        # Load PRs Button
        self.pr_button = QPushButton('List Diffs', self)
        self.pr_button.clicked.connect(self.listPRs)
        layout.addWidget(self.pr_button)
        self._pr_button_label = self.pr_button.text()

        self.load_more_button = QPushButton('Load More', self)
        self.load_more_button.clicked.connect(self.loadMorePRs)
        self.load_more_button.setEnabled(False)
        self.load_more_button.setVisible(False)
        layout.addWidget(self.load_more_button)
        self._load_more_label = self.load_more_button.text()

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
        self._run_button_label = self.run_button.text()
        self._pr_search_timer = QTimer(self)
        self._pr_search_timer.setSingleShot(True)
        self._pr_search_timer.timeout.connect(self._perform_debounced_pr_search)

        pr_widget.setLayout(layout)  # Set the layout for the pr_widget
        return pr_widget

    def getPRDiffs(self):
        repo_dir = self._require_active_repo_dir()
        pr_merge_commit = self.commit_input.text().strip()
        output_dir = self.config_manager.get_output_dir().strip()

        if not repo_dir or not pr_merge_commit or not output_dir:
            QMessageBox.warning(
                self,
                INPUT_ERROR,
                "Active repository, commit hash, and output directory must be provided.\n"
                "Set the output directory in Settings.",
            )
            if not output_dir:
                self.tabs.setCurrentWidget(self.settings_tab)
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

    def selectDirectory(self, title):
        """ Open a standard directory selection dialog using QFileDialog. """
        return QFileDialog.getExistingDirectory(self, title)

    def generateDiff(self):
        repo_dir = self._require_active_repo_dir()
        output_dir = self.config_manager.get_output_dir().strip()

        if not repo_dir or not output_dir:
            QMessageBox.warning(
                self,
                INPUT_ERROR,
                "Active repository and output directory must be provided.\nSet the output directory in Settings.",
            )
            if not output_dir:
                self.tabs.setCurrentWidget(self.settings_tab)
            return

        os.makedirs(output_dir, exist_ok=True)

        selected_item = self.pr_list.currentItem()
        if selected_item is not None:
            pr_data = selected_item.data(Qt.UserRole)
            if isinstance(pr_data, dict):
                selected_repo_dir = (pr_data.get('repo_local_dir') or '').strip()
                if selected_repo_dir and os.path.isdir(selected_repo_dir):
                    repo_dir = selected_repo_dir
                if self.task_runner:
                    self._generate_diff_async(repo_dir, output_dir, pr_data=pr_data)
                else:
                    try:
                        diff_path, state = self._generate_pr_diff(pr_data, repo_dir, output_dir)
                        QMessageBox.information(
                            self,
                            "Success",
                            f"Diff for PR #{pr_data.get('id')} ({state}) saved to {diff_path}.",
                        )
                        self.openFile(diff_path)
                    except Exception as exc:  # noqa: BLE001
                        QMessageBox.critical(self, "Error", f"Failed to generate PR diff:\n{exc}")
                return

        commit_text = self.commit_input.text()
        commit_hashes = commit_text.replace(',', ' ').split()
        self.config_manager.set_commit_hashes(commit_text.strip())

        if not commit_hashes:
            QMessageBox.warning(self, INPUT_ERROR, "Enter at least one commit hash or select a pull request.")
            return

        if self.task_runner:
            self._generate_diff_async(repo_dir, output_dir, commit_hashes=commit_hashes)
            return

        try:
            diff_paths, warnings = self._generate_commit_diffs(repo_dir, commit_hashes, output_dir)
            for path in diff_paths:
                self.openFile(path)
            message = f"Created {len(diff_paths)} diff file(s)."
            if warnings:
                message += "\n\nWarnings:\n" + "\n".join(warnings)
            QMessageBox.information(self, "Success", message)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"An unexpected error occurred:\n{exc}")

    def listPRs(self):
        selected_repos = self.config_manager.get_selected_repositories()
        if not selected_repos:
            repo_dir = self._require_active_repo_dir()
            if not repo_dir:
                return
            selected_repos = [self.config_manager.get_active_repository()]

        provider = (self.config_manager.get_provider() or 'bitbucket').lower()
        repo_ids = [str((repo or {}).get('id', '')) for repo in selected_repos if (repo or {}).get('id')]
        if not repo_ids:
            QMessageBox.warning(self, INPUT_ERROR, "No selected repositories were found. Select repositories in Settings.")
            return

        filter_mode = self._selected_filter()

        if provider == 'github':
            provider_base_config = self._get_github_config(repo=selected_repos[0], show_dialog=True)
        else:
            provider_base_config = self._get_bitbucket_config(repo=selected_repos[0], show_dialog=True)

        if not provider_base_config:
            return

        self._current_provider = provider
        self._current_filter_mode = filter_mode
        self._current_provider_config = provider_base_config
        self._current_selected_repos = selected_repos
        self._current_cursor_state = PRAggregationService.seed_cursor_state(selected_repos)
        self._last_remote_search_key = None

        cache_key = (provider, tuple(sorted(repo_ids)), filter_mode)
        cached = self._pr_cache.get(cache_key)
        if cached:
            timestamp, cached_prs, cached_next = cached
            if time.time() - timestamp < self._pr_cache_ttl:
                self.prs = list(cached_prs)
                self._pagination_state = cached_next
                self._current_cursor_state = cached_next or {}
                if not self.prs:
                    QMessageBox.information(
                        self,
                        "No Results",
                        "No pull requests matched the current filters.",
                    )
                self.displayPRs()
                self.load_more_button.setEnabled(bool(self._pagination_state))
                return

        self.prs = []
        self.pr_list.clear()
        self._pagination_state = PRAggregationService.seed_cursor_state(selected_repos)
        self._current_cursor_state = dict(self._pagination_state)
        self.load_more_button.setEnabled(False)

        self._load_pr_page(reset=True)

    def loadMorePRs(self, auto=False):
        if not self._current_provider or not self._current_provider_config:
            if not auto:
                QMessageBox.warning(self, INPUT_ERROR, "Load pull requests before requesting more results.")
            return

        if not PRAggregationService.has_more(self._current_cursor_state):
            self.load_more_button.setEnabled(False)
            if not auto:
                QMessageBox.information(self, "No More Results", "All pull requests have been loaded.")
            return

        self._load_pr_page(reset=False)

    def _load_pr_page(self, reset):
        if self._pr_page_loading:
            return

        self._pr_page_loading = True
        provider = self._current_provider
        filter_mode = self._current_filter_mode
        config = self._current_provider_config
        selected_repos = getattr(self, '_current_selected_repos', [])

        if not provider or not config or not selected_repos:
            self._pr_page_loading = False
            return

        cursor_state = dict(self._current_cursor_state or {})

        def handle_result(result):
            records, next_token = result
            self._handle_pr_page_result(records, next_token, reset)

        def handle_error(exc: Exception):
            QMessageBox.critical(self, "Error", f"Failed to retrieve pull requests:\n{exc}")

        def execute_fetch():
            return self.pr_service.aggregate_pull_requests(selected_repos, filter_mode, cursor_state, reset)

        if not self.task_runner:
            try:
                handle_result(execute_fetch())
            except Exception as exc:  # noqa: BLE001
                handle_error(exc)
            finally:
                self._pr_page_loading = False
                self._auto_load_more_if_needed()
            return

        message = "Loading…" if reset else "Loading more…"
        self._set_pr_loading(True, message)

        def on_finished():
            self._pr_page_loading = False
            self._set_pr_loading(False)
            self._auto_load_more_if_needed()

        self.task_runner.run(
            execute_fetch,
            description="Load Pull Requests" if reset else "Load More Pull Requests",
            on_result=handle_result,
            on_error=handle_error,
            on_finished=on_finished,
        )

    def _handle_pr_page_result(self, records, next_cursor, reset):
        if reset:
            self.prs = []
            self.pr_list.clear()

        self.prs.extend(records)

        if reset and not self.prs:
            QMessageBox.information(self, "No Results", "No pull requests matched the current filters.")

        if reset:
            self.displayPRs()
        else:
            self.displayPRs(records, append=True)

        self.searchPRs()

        if not records and not reset:
            QMessageBox.information(self, "No More Results", "No additional pull requests were returned.")

        self._pagination_state = next_cursor
        self._current_cursor_state = dict(next_cursor or {})
        self.load_more_button.setEnabled(PRAggregationService.has_more(self._current_cursor_state))

        repo_ids = [str((repo or {}).get('id', '')) for repo in getattr(self, '_current_selected_repos', []) if (repo or {}).get('id')]
        cache_key = (self._current_provider, tuple(sorted(repo_ids)), self._current_filter_mode)
        self._pr_cache[cache_key] = (
            time.time(),
            list(self.prs),
            next_cursor,
        )

    def displayPRs(self, prs=None, append=False):
        """Display pull requests in the list widget."""
        if append:
            records = prs if prs is not None else []
        else:
            self.pr_list.clear()
            records = prs if prs is not None else self.prs

        self.pr_list.setUpdatesEnabled(False)
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
            repo_label = pr.get('repo_label') or ''

            header = f"PR #{pr_id} · {state}"
            if provider_label:
                header = f"{header} [{provider_label}]"

            item = QListWidgetItem()
            item.setData(Qt.UserRole, pr)
            descriptor = (
                f"{header} {repo_label} {source_branch} {destination_branch} "
                f"{title} {author} {(pr.get('description') or '')}"
            ).lower()
            item.setData(Qt.UserRole + 1, descriptor)
            item.setData(
                UI_ROLE,
                {
                    "header": header,
                    "repo_label": repo_label or "Unknown",
                    "branch_line": f"{source_branch} -> {destination_branch}",
                    "title": summary,
                    "author": author,
                },
            )
            item.setText(descriptor)
            self.pr_list.addItem(item)
        self.pr_list.setUpdatesEnabled(True)

    def searchPRs(self):
        """Filter PRs based on the search input."""
        query = self.search_input.text().strip().lower()
        local_matches = self._apply_local_pr_filter(query)

        if not query:
            self._last_remote_search_key = None
            return

        if local_matches > 0:
            return

        self._trigger_remote_pr_search(query)

    def _on_pr_search_text_changed(self):
        # Instant local filtering for responsiveness.
        query = self.search_input.text().strip().lower()
        self._apply_local_pr_filter(query)
        if not query:
            self._last_remote_search_key = None
            return

        if self._pr_search_timer:
            self._pr_search_timer.start(250)
        else:
            self._perform_debounced_pr_search()

    def _perform_debounced_pr_search(self):
        self.searchPRs()

    def _apply_local_pr_filter(self, query):
        local_matches = 0
        for i in range(self.pr_list.count()):
            item = self.pr_list.item(i)
            descriptor = item.data(Qt.UserRole + 1) or ""
            is_match = (not query) or (query in descriptor)
            item.setHidden(not is_match)
            if is_match:
                local_matches += 1
        return local_matches

    def _trigger_remote_pr_search(self, query):
        provider = self._current_provider or (self.config_manager.get_provider() or 'bitbucket').lower()
        filter_mode = self._current_filter_mode or self._selected_filter()
        selected_repos = getattr(self, '_current_selected_repos', []) or self.config_manager.get_selected_repositories()
        repo_ids = tuple(sorted(str((repo or {}).get('id', '')) for repo in selected_repos if (repo or {}).get('id')))
        search_key = (provider, filter_mode, repo_ids, query)

        if self._remote_search_inflight:
            return

        self._last_remote_search_key = search_key
        self._remote_search_inflight = True

        def on_result(remote_records):
            self._remote_search_inflight = False
            current_query = self.search_input.text().strip().lower()
            if current_query != query:
                return

            if not remote_records:
                return

            existing_ids = {
                (str(pr.get('repo_id', '')), str(pr.get('id', '')))
                for pr in self.prs
            }
            new_records = []
            for pr in remote_records:
                key = (str(pr.get('repo_id', '')), str(pr.get('id', '')))
                if key in existing_ids:
                    continue
                existing_ids.add(key)
                new_records.append(pr)

            if not new_records:
                return

            self.prs.extend(new_records)
            self.displayPRs(new_records, append=True)
            self.searchPRs()

        def on_error(_exc: Exception):
            self._remote_search_inflight = False
            self._last_remote_search_key = None

        def task():
            return self._search_prs_remote(provider, filter_mode, selected_repos, query)

        if self.task_runner:
            self.task_runner.run(
                task,
                description="Search Pull Requests",
                on_result=on_result,
                on_error=on_error,
            )
            return

        try:
            on_result(task())
        except Exception as exc:  # noqa: BLE001
            on_error(exc)

    def _search_prs_remote(self, provider, filter_mode, selected_repos, query):
        return self.pr_service.search_pull_requests(selected_repos, filter_mode, query)

    def _on_settings_updated(self):
        self._pr_cache.clear()
        self.apply_repo_config()
        self.contribution_history_tab.apply_provider_context()

    def _on_provider_updated(self, provider):
        provider = (provider or 'bitbucket').lower()
        active_repo = self.config_manager.get_active_repository()
        if (active_repo.get('provider') or '').lower() != provider:
            self.config_manager.clear_active_repository()
            self.config_manager.set_selected_repositories([])
            self.settings_tab.clear_pending_repository_selection()
        self.create_pr_tab.setEnabled(provider == 'bitbucket')
        self._pr_cache.clear()
        self.prs = []
        self.pr_list.clear()
        self.apply_repo_config()
        self.contribution_history_tab.apply_provider_context()

    def _on_tab_changed(self, index):
        if self._handling_tab_change:
            self._previous_tab_index = index
            return

        previous_widget = self.tabs.widget(self._previous_tab_index)
        current_widget = self.tabs.widget(index)
        self._previous_tab_index = index

        if previous_widget is not self.settings_tab or current_widget is self.settings_tab:
            return
        if self._repo_activation_in_progress or not self.settings_tab.has_unsaved_repository_selection():
            return

        result = QMessageBox.question(
            self,
            "Save Repository Selection?",
            "Would you like to save the selected repositories before leaving Settings?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if result == QMessageBox.Yes:
            self.settings_tab.activate_selected_repositories()
        else:
            self.settings_tab.discard_unsaved_repository_selection()

    def _selected_filter(self):
        if self.only_pr_radio.isChecked():
            return 'open'
        if self.only_merges_radio.isChecked():
            return 'merged'
        return 'all'

    def _get_bitbucket_config(self, repo=None, show_dialog=True):
        username = (self.config_manager.get_bitbucket_username() or '').strip()
        password = (self.config_manager.get_bitbucket_app_password() or '').strip()
        active_repo = repo or self.config_manager.get_active_repository()
        slug = (active_repo.get('slug') or '').strip()
        active_workspace = (active_repo.get('owner') or '').strip()
        workspace = (self.config_manager.get_bitbucket_workspace() or '').strip()
        workspace = active_workspace or workspace or DEFAULT_BITBUCKET_WORKSPACE

        if not username or not password:
            if show_dialog:
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
            if show_dialog:
                QMessageBox.warning(
                    self,
                    "Bitbucket Configuration",
                    "Select an active Bitbucket repository in Settings before loading pull requests.",
                )
                self.tabs.setCurrentWidget(self.settings_tab)
            return None

        return {
            'username': username,
            'password': password,
            'slug': slug,
            'workspace': workspace,
        }

    def _get_github_config(self, repo=None, show_dialog=True):
        active_repo = repo or self.config_manager.get_active_repository()
        owner = (active_repo.get('owner') or '').strip()
        repo = (active_repo.get('slug') or active_repo.get('name') or '').strip()
        token = (self.config_manager.get_github_token() or '').strip()

        if not owner or not repo:
            if show_dialog:
                QMessageBox.warning(
                    self,
                    "GitHub Configuration",
                    "Select an active GitHub repository in Settings before loading pull requests.",
                )
                self.tabs.setCurrentWidget(self.settings_tab)
            return None

        headers = {'Accept': 'application/vnd.github+json'}
        if token:
            headers['Authorization'] = f'token {token}'

        return {
            'owner': owner,
            'repo': repo,
            'headers': headers,
        }

    def _fetch_bitbucket_pull_requests_page(self, filter_mode, config, next_url=None):
        return self.pr_service._fetch_bitbucket_pull_requests_page(filter_mode, config, next_url)

    @staticmethod
    def _map_bitbucket_pr(pr_record):
        return PullRequestService._map_bitbucket_pr(pr_record)

    def _fetch_github_pull_requests_page(self, filter_mode, config, next_url=None):
        return self.pr_service._fetch_github_pull_requests_page(filter_mode, config, next_url)

    @staticmethod
    def _map_github_pr(pr_record):
        return PullRequestService._map_github_pr(pr_record)

    @staticmethod
    def _github_next_link(link_header):
        return PullRequestService._github_next_link(link_header)

    def _generate_pr_diff(self, pr, repo_dir, output_dir):
        return self.diff_service.save_pr_diff(pr, repo_dir, output_dir)

    def _resolve_commit(self, repo_dir, commit_hash, branch_name):
        return self.diff_service._resolve_commit(repo_dir, commit_hash, branch_name)

    @staticmethod
    def _verify_commit(repo_dir, identifier):
        return DiffService()._verify_commit(repo_dir, identifier)

    @staticmethod
    def _merge_base(repo_dir, destination_commit, source_commit):
        return DiffService()._merge_base(repo_dir, destination_commit, source_commit)

    def _build_pr_diff_filename(self, pr, output_dir):
        return self.diff_service._build_pr_diff_filename(pr, output_dir)

    @staticmethod
    def _safe_filename(value, fallback='file'):
        return DiffService._safe_filename(value, fallback=fallback)

    def _set_pr_loading(self, loading, message=None):
        if loading:
            self.pr_button.setText(message or "Working…")
            self.run_button.setText("Working…")
            if self.load_more_button:
                self.load_more_button.setText(message or "Working…")
        else:
            self.pr_button.setText(self._pr_button_label)
            self.run_button.setText(self._run_button_label)
            if self.load_more_button:
                self.load_more_button.setText(self._load_more_label)

        widgets = [
            self.pr_button,
            self.run_button,
            self.pr_list,
            self.search_input,
            self.only_pr_radio,
            self.only_merges_radio,
            self.all_diffs_radio,
            self.load_more_button,
        ]
        for widget in widgets:
            widget.setEnabled(not loading)

    def _on_pr_list_scrolled(self, value):
        scrollbar = self.pr_list.verticalScrollBar()
        if not scrollbar:
            return
        if self._pr_page_loading or not PRAggregationService.has_more(self._current_cursor_state):
            return
        if value >= max(0, scrollbar.maximum() - 40):
            self.loadMorePRs(auto=True)

    def _auto_load_more_if_needed(self):
        # Keep pagination fully driven by explicit user scrolling events.
        return

    def _generate_diff_async(self, repo_dir, output_dir, pr_data=None, commit_hashes=None):
        self._set_pr_loading(True, "Processing…")

        def task():
            if pr_data is not None:
                diff_path, state = self._generate_pr_diff(pr_data, repo_dir, output_dir)
                return {
                    'type': 'pr',
                    'paths': [diff_path],
                    'state': state,
                    'pr': pr_data,
                }

            diff_paths, warnings = self._generate_commit_diffs(repo_dir, commit_hashes, output_dir)
            return {
                'type': 'commits',
                'paths': diff_paths,
                'warnings': warnings,
            }

        def on_result(result):
            if result['type'] == 'pr':
                info = result['pr']
                diff_path = result['paths'][0]
                state = result.get('state', 'UNKNOWN')
                QMessageBox.information(
                    self,
                    "Success",
                    f"Diff for PR #{info.get('id')} ({state}) saved to {diff_path}.",
                )
                self.openFile(diff_path)
            else:
                warnings = result.get('warnings', [])
                for path in result['paths']:
                    self.openFile(path)
                message = f"Created {len(result['paths'])} diff file(s)."
                if warnings:
                    message += "\n\nWarnings:\n" + "\n".join(warnings)
                QMessageBox.information(self, "Success", message)

        def on_error(exc: Exception):
            QMessageBox.critical(self, "Error", f"Failed to generate diff:\n{exc}")

        self.task_runner.run(
            task,
            description="Generate Diff",
            on_result=on_result,
            on_error=on_error,
            on_finished=lambda: self._set_pr_loading(False),
        )

    def _generate_commit_diffs(self, repo_dir, commit_hashes, output_dir):
        return self.diff_service.save_commit_diffs(repo_dir, commit_hashes, output_dir)

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
    def _initialize_active_repository(self):
        selected_repos = self.config_manager.get_selected_repositories()
        if selected_repos:
            active_repo = self.config_manager.get_active_repository()
            self._prepare_selected_repositories(
                selected_repos,
                show_success=False,
                preferred_active_repo_id=(active_repo.get('id') or ''),
            )
            return

        active_repo = self.config_manager.get_active_repository()
        repo_id = (active_repo.get('id') or '').strip()
        if not repo_id:
            return

        local_dir = (active_repo.get('local_dir') or '').strip()
        if local_dir and os.path.isdir(local_dir):
            self.config_manager.set_repo_dir(local_dir)
            self.apply_repo_config()
            return

        self._prepare_selected_repositories([active_repo], show_success=False, preferred_active_repo_id=repo_id)

    def _on_active_repositories_selected(self, repos):
        self._prepare_selected_repositories(repos, show_success=True)

    def _prepare_selected_repositories(self, repos, show_success, preferred_active_repo_id=''):
        if self._repo_activation_in_progress:
            return
        selected = [dict(repo or {}) for repo in (repos or []) if (repo or {}).get('id')]
        if not selected:
            return

        provider = (selected[0].get('provider') or self.config_manager.get_provider() or 'bitbucket').lower()
        selected = [repo for repo in selected if (repo.get('provider') or provider).lower() == provider]
        if not selected:
            return

        valid, message, _ = RepositoryProvider.validate_provider_config(provider, self.config_manager)
        if not valid:
            QMessageBox.warning(self, "Configuration Error", message)
            self.tabs.setCurrentWidget(self.settings_tab)
            self.settings_tab.set_repository_activation_finished(False)
            return

        self._repo_activation_in_progress = True
        self._set_repo_activation_ui(
            True,
            f"Preparing {len(selected)} selected repositories...",
        )

        def on_result(prepared_repos):
            prepared = list(prepared_repos or [])
            if not prepared:
                raise RuntimeError("No repositories were prepared.")

            active_repo = prepared[0]
            if preferred_active_repo_id:
                for candidate in prepared:
                    if str(candidate.get('id', '')) == str(preferred_active_repo_id):
                        active_repo = candidate
                        break

            self.config_manager.set_selected_repositories(prepared)
            self.config_manager.set_active_repository(active_repo)
            self._pr_cache.clear()
            self.contribution_history_tab.apply_provider_context()
            self.apply_repo_config()
            self._repo_activation_in_progress = False
            self._set_repo_activation_ui(False)
            self.settings_tab.set_repository_activation_finished(True, prepared, active_repo)
            if show_success:
                QMessageBox.information(
                    self,
                    "Repositories Updated",
                    f"Prepared {len(prepared)} repositories.\n"
                    f"Primary repository: {active_repo.get('owner', '')}/{active_repo.get('slug', active_repo.get('name', ''))}.",
                )

        def on_error(exc: Exception):
            self._repo_activation_in_progress = False
            self._set_repo_activation_ui(False)
            self.settings_tab.set_repository_activation_finished(False)
            QMessageBox.critical(self, "Repository Setup Error", f"Failed to prepare repository:\n{exc}")

        if not self.task_runner:
            try:
                on_result(RepositoryProvider.ensure_local_checkouts(selected, self.config_manager))
            except Exception as exc:  # noqa: BLE001
                on_error(exc)
            return

        self.task_runner.run(
            lambda: RepositoryProvider.ensure_local_checkouts(selected, self.config_manager),
            description="Prepare Active Repository",
            on_result=on_result,
            on_error=on_error,
        )

    def _set_repo_activation_ui(self, active: bool, message: str = "Preparing repository..."):
        if active:
            self.tabs.setEnabled(False)
            if self._repo_progress_dialog is None:
                dialog = QProgressDialog(message, None, 0, 0, self)
                dialog.setWindowTitle("Preparing Repository")
                dialog.setWindowModality(Qt.ApplicationModal)
                dialog.setCancelButton(None)
                dialog.setMinimumDuration(0)
                dialog.setAutoClose(False)
                dialog.setAutoReset(False)
                dialog.setWindowFlag(Qt.WindowCloseButtonHint, False)
                self._repo_progress_dialog = dialog
            else:
                self._repo_progress_dialog.setLabelText(message)
            self._repo_progress_dialog.show()
            QApplication.setOverrideCursor(Qt.WaitCursor)
            return

        self.tabs.setEnabled(True)
        if self._repo_progress_dialog is not None:
            self._repo_progress_dialog.hide()

        while QApplication.overrideCursor() is not None:
            QApplication.restoreOverrideCursor()

    def _require_active_repo_dir(self):
        if self._repo_activation_in_progress:
            QMessageBox.information(
                self,
                "Repository Setup In Progress",
                "The selected repository is still being prepared. Please wait a moment and try again.",
            )
            return None

        repo_dir = (self.config_manager.get_repo_dir() or '').strip()
        if repo_dir and os.path.isdir(repo_dir):
            return repo_dir

        QMessageBox.warning(
            self,
            INPUT_ERROR,
            "Active repository is not set.\nUse Settings -> Repository Discovery to choose a repository.",
        )
        self.tabs.setCurrentWidget(self.settings_tab)
        return None

    def apply_repo_config(self):
        repo_dir = self.config_manager.get_repo_dir()
        commits = self.config_manager.get_commit_hashes()
        selected_count = len(self.config_manager.get_selected_repositories())

        self._set_line_edit_text(self.repo_input, repo_dir)
        self._set_line_edit_text(self.commit_input, commits)
        if selected_count > 1:
            self.repo_label.setText(f'Primary Repository Directory ({selected_count} selected):')
        elif selected_count == 1:
            self.repo_label.setText('Primary Repository Directory (1 selected):')
        else:
            self.repo_label.setText('Primary Repository Directory:')

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

    def _store_commit_hashes(self):
        self.config_manager.set_commit_hashes(self.commit_input.text().strip())


if __name__ == '__main__':
    app = QApplication([])
    extractor = GitDiffExtractor()
    extractor.show()
    app.exec_()
