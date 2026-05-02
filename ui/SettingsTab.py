import os
import platform
import subprocess
import time

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGroupBox,
    QHBoxLayout,
    QFormLayout,
    QRadioButton,
    QButtonGroup,
    QLineEdit,
    QLabel,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QFileDialog,
)

from services.RepositoryProvider import RepositoryProvider


class SettingsTab(QWidget):
    """Central location for provider selection, credentials, and repository discovery."""

    settingsUpdated = pyqtSignal()
    providerChanged = pyqtSignal(str)
    activeRepositoriesChanged = pyqtSignal(list)

    def __init__(self, config_manager, task_runner=None):
        super().__init__()
        self.config = config_manager
        self.task_runner = task_runner

        self.bitbucket_radio = None
        self.github_radio = None
        self.bitbucket_group = None
        self.github_group = None

        self.bb_user_input = None
        self.bb_password_input = None
        self.bb_workspace_input = None

        self.github_owner_input = None
        self.github_token_input = None

        self.repo_list = None
        self.selected_repo_list = None
        self.repo_search_input = None
        self.repo_status = None
        self.discover_button = None
        self.refresh_button = None
        self.activate_button = None
        self.clear_checked_button = None
        self.output_input = None
        self.output_browse_button = None
        self.open_reports_button = None

        self._repos = []
        self._activation_in_progress = False
        self._selected_repo_map = {}

        self._build_ui()
        self.apply_repo_config()

    # ------------------------------------------------------------------
    # UI construction
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(18)

        provider_group = QGroupBox("Provider", self)
        provider_layout = QHBoxLayout(provider_group)
        provider_layout.setContentsMargins(12, 12, 12, 12)
        provider_layout.setSpacing(20)

        self.bitbucket_radio = QRadioButton("Bitbucket", provider_group)
        self.github_radio = QRadioButton("GitHub", provider_group)

        self.bitbucket_radio.toggled.connect(self._on_provider_toggled)
        self.github_radio.toggled.connect(self._on_provider_toggled)

        provider_buttons = QButtonGroup(provider_group)
        provider_buttons.addButton(self.bitbucket_radio)
        provider_buttons.addButton(self.github_radio)

        provider_layout.addWidget(self.bitbucket_radio)
        provider_layout.addWidget(self.github_radio)
        provider_layout.addStretch()
        layout.addWidget(provider_group)

        # Bitbucket configuration
        self.bitbucket_group = QGroupBox("Bitbucket Settings", self)
        bb_form = QFormLayout(self.bitbucket_group)
        bb_form.setLabelAlignment(Qt.AlignRight)
        bb_form.setFormAlignment(Qt.AlignLeft)
        bb_form.setContentsMargins(12, 12, 12, 12)
        bb_form.setHorizontalSpacing(12)
        bb_form.setVerticalSpacing(8)

        self.bb_user_input = QLineEdit(self)
        self.bb_user_input.editingFinished.connect(self._store_bitbucket_username)
        bb_form.addRow(QLabel("Username:"), self.bb_user_input)

        self.bb_password_input = QLineEdit(self)
        self.bb_password_input.setEchoMode(QLineEdit.Password)
        self.bb_password_input.editingFinished.connect(self._store_bitbucket_password)
        bb_form.addRow(QLabel("App Password:"), self.bb_password_input)

        self.bb_workspace_input = QLineEdit(self)
        self.bb_workspace_input.editingFinished.connect(self._store_bitbucket_workspace)
        bb_form.addRow(QLabel("Workspace:"), self.bb_workspace_input)

        layout.addWidget(self.bitbucket_group)

        # GitHub configuration
        self.github_group = QGroupBox("GitHub Settings", self)
        gh_form = QFormLayout(self.github_group)
        gh_form.setLabelAlignment(Qt.AlignRight)
        gh_form.setFormAlignment(Qt.AlignLeft)
        gh_form.setContentsMargins(12, 12, 12, 12)
        gh_form.setHorizontalSpacing(12)
        gh_form.setVerticalSpacing(8)

        self.github_owner_input = QLineEdit(self)
        self.github_owner_input.setPlaceholderText("Optional owner/org filter")
        self.github_owner_input.editingFinished.connect(self._store_github_owner)
        gh_form.addRow(QLabel("Owner Filter:"), self.github_owner_input)

        self.github_token_input = QLineEdit(self)
        self.github_token_input.setEchoMode(QLineEdit.Password)
        self.github_token_input.editingFinished.connect(self._store_github_token)
        gh_form.addRow(QLabel("Token:"), self.github_token_input)

        layout.addWidget(self.github_group)

        application_group = QGroupBox("Application Settings", self)
        application_form = QFormLayout(application_group)
        application_form.setLabelAlignment(Qt.AlignRight)
        application_form.setFormAlignment(Qt.AlignLeft)
        application_form.setContentsMargins(12, 12, 12, 12)
        application_form.setHorizontalSpacing(12)
        application_form.setVerticalSpacing(8)

        output_layout = QHBoxLayout()
        self.output_input = QLineEdit(self)
        self.output_input.editingFinished.connect(self._store_output_dir)
        output_layout.addWidget(self.output_input)

        self.output_browse_button = QPushButton("Browse", self)
        self.output_browse_button.clicked.connect(self.browse_output_dir)
        output_layout.addWidget(self.output_browse_button)

        self.open_reports_button = QPushButton("Open Reports", self)
        self.open_reports_button.clicked.connect(self.open_reports_folder)
        output_layout.addWidget(self.open_reports_button)

        application_form.addRow(QLabel("Output Directory:"), output_layout)
        layout.addWidget(application_group)

        discovery_group = QGroupBox("Repository Discovery", self)
        discovery_layout = QVBoxLayout(discovery_group)
        discovery_layout.setContentsMargins(12, 12, 12, 12)
        discovery_layout.setSpacing(8)

        controls = QHBoxLayout()
        self.discover_button = QPushButton("Load Repositories", self)
        self.discover_button.clicked.connect(self.discover_repositories)
        controls.addWidget(self.discover_button)

        self.refresh_button = QPushButton("Refresh", self)
        self.refresh_button.clicked.connect(lambda: self.discover_repositories(force_refresh=True))
        controls.addWidget(self.refresh_button)

        self.clear_checked_button = QPushButton("Clear Checked", self)
        self.clear_checked_button.clicked.connect(self._clear_checked_repositories)
        controls.addWidget(self.clear_checked_button)

        self.activate_button = QPushButton("Use Selected Repositories", self)
        self.activate_button.clicked.connect(self.activate_selected_repositories)
        controls.addWidget(self.activate_button)
        controls.addStretch()

        discovery_layout.addLayout(controls)

        self.repo_status = QLabel("No repositories loaded.", self)
        self.repo_status.setWordWrap(True)
        discovery_layout.addWidget(self.repo_status)

        self.repo_search_input = QLineEdit(self)
        self.repo_search_input.setPlaceholderText("Search discovered repositories")
        self.repo_search_input.textChanged.connect(self._filter_repository_list)
        discovery_layout.addWidget(self.repo_search_input)

        self.repo_list = QListWidget(self)
        self.repo_list.itemChanged.connect(self._on_repo_item_changed)
        discovery_layout.addWidget(self.repo_list)

        selected_label = QLabel("Selected Repositories", self)
        discovery_layout.addWidget(selected_label)
        self.selected_repo_list = QListWidget(self)
        discovery_layout.addWidget(self.selected_repo_list)

        layout.addWidget(discovery_group)
        layout.addStretch()

    # ------------------------------------------------------------------
    # Configuration helpers
    def apply_repo_config(self):
        provider = self.config.get_provider()
        self._set_provider(provider)

        self._set_line_edit(self.bb_user_input, self.config.get_bitbucket_username())
        self._set_line_edit(self.bb_password_input, self.config.get_bitbucket_app_password())
        self._set_line_edit(self.bb_workspace_input, self.config.get_bitbucket_workspace())

        self._set_line_edit(self.github_owner_input, self.config.get_github_owner())
        self._set_line_edit(self.github_token_input, self.config.get_github_token())
        self._set_line_edit(self.output_input, self.config.get_output_dir())

        self._selected_repo_map = {
            str((repo or {}).get("id", "")): repo
            for repo in self.config.get_selected_repositories()
            if (repo or {}).get("id")
        }
        self._update_visibility()
        self._apply_selected_repo_selection()

    def _apply_selected_repo_selection(self):
        selected_repos = list(self._selected_repo_map.values())
        selected_ids = set(self._selected_repo_map.keys())

        active_repo = self.config.get_active_repository()
        active_name = active_repo.get("name") or ""
        active_owner = active_repo.get("owner") or ""
        active_provider = active_repo.get("provider") or ""

        if selected_repos:
            self.repo_status.setText(
                f"Selected repositories: {len(selected_repos)} | "
                f"Primary: {active_owner}/{active_name} ({active_provider})"
            )
        elif active_name:
            self.repo_status.setText(f"Primary repository: {active_owner}/{active_name} ({active_provider})")
        else:
            self.repo_status.setText("No repository selection saved.")

        self.repo_list.blockSignals(True)
        for i in range(self.repo_list.count()):
            item = self.repo_list.item(i)
            payload = item.data(Qt.UserRole) or {}
            repo_id = str(payload.get("id", ""))
            item.setCheckState(Qt.Checked if repo_id in selected_ids else Qt.Unchecked)
        self.repo_list.blockSignals(False)
        self._sync_selected_repo_panel()

    @staticmethod
    def _set_line_edit(line_edit, value):
        if line_edit is None:
            return
        block = line_edit.blockSignals(True)
        line_edit.setText(value or "")
        line_edit.blockSignals(block)

    def _set_provider(self, provider):
        provider = (provider or "bitbucket").lower()
        block_bb = self.bitbucket_radio.blockSignals(True)
        block_gh = self.github_radio.blockSignals(True)
        if provider == "github":
            self.github_radio.setChecked(True)
        else:
            self.bitbucket_radio.setChecked(True)
        self.bitbucket_radio.blockSignals(block_bb)
        self.github_radio.blockSignals(block_gh)
        self._update_visibility()

    def _update_visibility(self):
        provider = "bitbucket" if self.bitbucket_radio.isChecked() else "github"
        if self.bitbucket_group:
            self.bitbucket_group.setVisible(provider == "bitbucket")
        if self.github_group:
            self.github_group.setVisible(provider == "github")

    def _set_discovery_busy(self, busy: bool, status: str = ""):
        self.discover_button.setEnabled(not busy)
        self.refresh_button.setEnabled(not busy)
        self.clear_checked_button.setEnabled((not busy) and (not self._activation_in_progress))
        self.activate_button.setEnabled((not busy) and (not self._activation_in_progress))
        self.repo_list.setEnabled((not busy) and (not self._activation_in_progress))
        self.selected_repo_list.setEnabled((not busy) and (not self._activation_in_progress))
        self.repo_search_input.setEnabled((not busy) and (not self._activation_in_progress))
        if status:
            self.repo_status.setText(status)

    # ------------------------------------------------------------------
    # Store handlers
    def _on_provider_toggled(self, checked):
        if not checked:
            return
        provider = "bitbucket" if self.bitbucket_radio.isChecked() else "github"
        self.config.set_provider(provider)
        self._update_visibility()
        self.providerChanged.emit(provider)
        self.settingsUpdated.emit()

    def _store_bitbucket_username(self):
        self.config.set_bitbucket_username(self.bb_user_input.text().strip())
        self.settingsUpdated.emit()

    def _store_bitbucket_password(self):
        self.config.set_bitbucket_app_password(self.bb_password_input.text().strip())
        self.settingsUpdated.emit()

    def _store_bitbucket_workspace(self):
        self.config.set_bitbucket_workspace(self.bb_workspace_input.text().strip())
        self.settingsUpdated.emit()

    def _store_github_owner(self):
        self.config.set_github_owner(self.github_owner_input.text().strip())
        self.settingsUpdated.emit()

    def _store_github_token(self):
        self.config.set_github_token(self.github_token_input.text().strip())
        self.settingsUpdated.emit()

    def _store_output_dir(self):
        self.config.set_output_dir(self.output_input.text().strip())
        self.settingsUpdated.emit()

    def browse_output_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if not directory:
            return
        self._set_line_edit(self.output_input, directory)
        self.config.set_output_dir(directory)
        self.settingsUpdated.emit()

    def open_reports_folder(self):
        output_dir = self.output_input.text().strip() or self.config.get_output_dir()
        if not output_dir:
            QMessageBox.warning(self, "Input Error", "Set an output directory before opening saved reports.")
            return
        if not os.path.isdir(output_dir):
            QMessageBox.warning(self, "Input Error", f"Output directory does not exist:\n{output_dir}")
            return
        self._open_path(output_dir)

    @staticmethod
    def _open_path(path):
        if platform.system() == "Darwin":
            subprocess.run(["open", path])
        elif platform.system() == "Windows":
            os.startfile(path)
        else:
            subprocess.run(["xdg-open", path])

    def discover_repositories(self, force_refresh=False):
        provider = (self.config.get_provider() or "bitbucket").lower()
        valid, message, provider_config = RepositoryProvider.validate_provider_config(provider, self.config)
        if not valid:
            QMessageBox.warning(self, "Configuration Error", message)
            self._focus_provider_config(provider)
            return

        context_key = RepositoryProvider.discovery_context_key(provider, provider_config)

        def render_repos(repos, source_label):
            self._repos = repos
            self.repo_list.clear()
            self.repo_search_input.clear()

            selected_ids = set(self._selected_repo_map.keys())

            self.repo_list.blockSignals(True)
            for repo in repos:
                label = f"{repo.get('owner', '')}/{repo.get('slug', repo.get('name', ''))}"
                item = QListWidgetItem(label)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setData(Qt.UserRole, repo)
                repo_id = str(repo.get("id", ""))
                item.setCheckState(Qt.Checked if repo_id in selected_ids else Qt.Unchecked)
                self.repo_list.addItem(item)
            self.repo_list.blockSignals(False)
            self._sync_selected_repo_panel()

            if repos:
                self.repo_status.setText(
                    f"Loaded {len(repos)} repositories for {provider} ({source_label})."
                )
            else:
                self.repo_status.setText(f"No repositories found for {provider}.")

        cached_repos, cached_timestamp = self.config.get_cached_discovered_repositories(provider, context_key)
        if not force_refresh and cached_repos:
            age_seconds = max(0, int(time.time() - cached_timestamp))
            render_repos(cached_repos, f"cached {age_seconds}s ago")
            return

        def handle_result(repos):
            self.config.set_cached_discovered_repositories(provider, context_key, repos)
            render_repos(repos, "fresh")

        def handle_error(exc: Exception):
            QMessageBox.critical(self, "Discovery Error", f"Failed to discover repositories:\n{exc}")
            self.repo_status.setText("Repository discovery failed.")

        if not self.task_runner:
            self._set_discovery_busy(True, "Discovering repositories…")
            try:
                handle_result(RepositoryProvider.discover_repositories(provider, provider_config))
            except Exception as exc:  # noqa: BLE001
                handle_error(exc)
            finally:
                self._set_discovery_busy(False)
            return

        self._set_discovery_busy(True, "Discovering repositories…")
        self.task_runner.run(
            lambda: RepositoryProvider.discover_repositories(provider, provider_config),
            description="Discover Repositories",
            on_result=handle_result,
            on_error=handle_error,
            on_finished=lambda: self._set_discovery_busy(False),
        )

    def activate_selected_repositories(self):
        repos = list(self._selected_repo_map.values())
        if not repos:
            QMessageBox.warning(self, "Selection Required", "Select at least one repository.")
            return

        primary = repos[0]
        owner = primary.get("owner", "")
        slug = primary.get("slug", primary.get("name", ""))
        self._activation_in_progress = True
        self._set_discovery_busy(
            False,
            f"Preparing {len(repos)} repositories. Primary: {owner}/{slug}...",
        )
        self.activeRepositoriesChanged.emit(repos)

    def has_unsaved_repository_selection(self):
        if not self._selected_repo_map:
            return False

        selected_ids = self._repo_ids(self._selected_repo_map.values())
        saved_ids = self._repo_ids(self.config.get_selected_repositories())
        return selected_ids != saved_ids

    def discard_unsaved_repository_selection(self):
        self._selected_repo_map = {
            str((repo or {}).get("id", "")): repo
            for repo in self.config.get_selected_repositories()
            if (repo or {}).get("id")
        }
        self._apply_selected_repo_selection()

    def clear_pending_repository_selection(self):
        self._selected_repo_map = {}
        self.repo_list.blockSignals(True)
        for i in range(self.repo_list.count()):
            item = self.repo_list.item(i)
            item.setCheckState(Qt.Unchecked)
        self.repo_list.blockSignals(False)
        self._sync_selected_repo_panel()

    @staticmethod
    def _repo_ids(repositories):
        return {
            str((repo or {}).get("id", ""))
            for repo in (repositories or [])
            if (repo or {}).get("id")
        }

    def set_repository_activation_finished(self, success: bool, repos: list = None, active_repo: dict = None):
        self._activation_in_progress = False
        self._set_discovery_busy(False)

        if success:
            saved_repos = repos if isinstance(repos, list) else self.config.get_selected_repositories()
            primary = active_repo or self.config.get_active_repository()
            owner = primary.get("owner", "")
            slug = primary.get("slug", primary.get("name", ""))
            provider = primary.get("provider", "")
            self._apply_selected_repo_selection()
            self.repo_status.setText(
                f"Selected repositories: {len(saved_repos)} | Primary: {owner}/{slug} ({provider})"
            )
            self._selected_repo_map = {
                str((repo or {}).get("id", "")): repo
                for repo in saved_repos
                if (repo or {}).get("id")
            }
            self._apply_selected_repo_selection()

    # ------------------------------------------------------------------
    # Focus helpers
    def focus_bitbucket_credentials(self):
        if self.bb_user_input:
            self.bb_user_input.setFocus()
            self.bb_user_input.selectAll()

    def focus_bitbucket_workspace(self):
        if self.bb_workspace_input:
            self.bb_workspace_input.setFocus()
            self.bb_workspace_input.selectAll()

    def focus_github_owner(self):
        if self.github_owner_input:
            self.github_owner_input.setFocus()
            self.github_owner_input.selectAll()

    def focus_github_token(self):
        if self.github_token_input:
            self.github_token_input.setFocus()
            self.github_token_input.selectAll()

    def _focus_provider_config(self, provider: str):
        if provider == "bitbucket":
            if not (self.config.get_bitbucket_username() or "").strip() or not (
                self.config.get_bitbucket_app_password() or ""
            ).strip():
                self.focus_bitbucket_credentials()
            else:
                self.focus_bitbucket_workspace()
            return

        if not (self.config.get_github_token() or "").strip():
            self.focus_github_token()
        else:
            self.focus_github_owner()

    def _filter_repository_list(self):
        query = (self.repo_search_input.text() or "").strip().lower()
        for i in range(self.repo_list.count()):
            item = self.repo_list.item(i)
            label = item.text().lower()
            item.setHidden(bool(query) and query not in label)

    def _on_repo_item_changed(self, item):
        repo = item.data(Qt.UserRole) or {}
        repo_id = str(repo.get("id", ""))
        if not repo_id:
            return

        if item.checkState() == Qt.Checked:
            self._selected_repo_map[repo_id] = repo
        else:
            self._selected_repo_map.pop(repo_id, None)
        self._sync_selected_repo_panel()

    def _sync_selected_repo_panel(self):
        selected = list(self._selected_repo_map.values())
        self.selected_repo_list.clear()
        for repo in selected:
            label = f"{repo.get('owner', '')}/{repo.get('slug', repo.get('name', ''))}"
            self.selected_repo_list.addItem(label)

    def _clear_checked_repositories(self):
        self.clear_pending_repository_selection()
