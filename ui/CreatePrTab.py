import os
import subprocess
import time

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QPushButton,
    QLabel,
    QMessageBox,
    QComboBox,
    QTextEdit,
    QToolButton,
    QFileDialog,
    QCheckBox,
)

from services.pr_creation_service import PullRequestCreateRequest, PullRequestCreationService
from ui.FilterableBranchSelector import FilterableBranchSelector


class CreatePRTab(QWidget):
    repoChanged = pyqtSignal(str)

    def __init__(self, config_manager, task_runner=None):
        super().__init__()
        self.config = config_manager
        self.task_runner = task_runner
        self.pr_creation_service = PullRequestCreationService(self.config)
        self._last_auto_refresh_repo = ""
        self._last_auto_refresh_ts = 0.0
        self._build_ui()

    def _info_button(self, text: str) -> QToolButton:
        button = QToolButton(self)
        button.setText("i")
        button.setAutoRaise(True)
        button.setCursor(Qt.PointingHandCursor)
        button.setStyleSheet(
            "QToolButton {"
            "color: #0b63ce;"
            "font-weight: 700;"
            "border: 1px solid #0b63ce;"
            "border-radius: 9px;"
            "min-width: 18px;"
            "max-width: 18px;"
            "min-height: 18px;"
            "max-height: 18px;"
            "padding: 0px;"
            "}"
        )
        button.clicked.connect(lambda: QMessageBox.information(self, "Create PR Info", text))
        return button

    def _build_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(15, 15, 15, 15)
        main.setSpacing(14)

        repo_group = QGroupBox("Target Repository")
        repo_form = QFormLayout(repo_group)
        repo_form.setLabelAlignment(Qt.AlignRight)
        repo_form.setFormAlignment(Qt.AlignLeft)
        repo_form.setHorizontalSpacing(12)
        repo_form.setVerticalSpacing(10)
        repo_form.setContentsMargins(12, 12, 12, 12)
        repo_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        repo_select_row = QHBoxLayout()
        self.repo_combo = QComboBox(self)
        self.repo_combo.setMinimumWidth(460)
        self.repo_combo.currentIndexChanged.connect(self._on_repository_changed)
        repo_select_row.addWidget(self.repo_combo, 1)
        repo_select_row.addWidget(
            self._info_button(
                "Choose which selected repository receives the pull request. "
                "Credentials come from Settings. Owner/workspace and slug come from the selected repository. "
                "This tab only creates a PR from one existing remote branch into another."
            )
        )
        repo_form.addRow("Repository:", repo_select_row)

        self.repo_summary_label = QLabel("No repository selected.", self)
        self.repo_summary_label.setWordWrap(True)
        repo_form.addRow("Details:", self.repo_summary_label)

        self.repo_input = QLineEdit(self)
        self.repo_input.setReadOnly(True)
        self.repo_input.setMinimumWidth(640)
        self.repo_input.setPlaceholderText("Selected repository local checkout")
        repo_path_row = QHBoxLayout()
        repo_path_row.addWidget(self.repo_input, 1)
        browse_repo_btn = QPushButton("Browse")
        browse_repo_btn.clicked.connect(self.browse_local_checkout)
        repo_path_row.addWidget(browse_repo_btn)
        repo_form.addRow("Local Path:", repo_path_row)

        main.addWidget(repo_group)

        branch_group = QGroupBox("Branches")
        branch_form = QFormLayout(branch_group)
        branch_form.setLabelAlignment(Qt.AlignRight)
        branch_form.setFormAlignment(Qt.AlignLeft)
        branch_form.setHorizontalSpacing(12)
        branch_form.setVerticalSpacing(10)
        branch_form.setContentsMargins(12, 12, 12, 12)
        branch_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.src_selector = FilterableBranchSelector(self)
        self.src_selector.setMinimumWidth(640)
        self.src_selector.selectionChanged.connect(self._store_source_branch)
        branch_form.addRow("Source:", self.src_selector)

        self.dst_selector = FilterableBranchSelector(self)
        self.dst_selector.setMinimumWidth(640)
        self.dst_selector.selectionChanged.connect(self._store_target_branch)
        branch_form.addRow("Target:", self.dst_selector)

        branch_action_row = QHBoxLayout()
        branch_action_row.addStretch()
        refresh_btn = QPushButton("Refresh Branches")
        refresh_btn.setFixedHeight(32)
        refresh_btn.clicked.connect(self.refresh_branches)
        branch_action_row.addWidget(refresh_btn)
        self.refresh_btn = refresh_btn
        self._refresh_btn_label = refresh_btn.text()
        branch_form.addRow(branch_action_row)

        main.addWidget(branch_group)

        pr_group = QGroupBox("Pull Request")
        pr_form = QFormLayout(pr_group)
        pr_form.setLabelAlignment(Qt.AlignRight)
        pr_form.setFormAlignment(Qt.AlignLeft)
        pr_form.setHorizontalSpacing(12)
        pr_form.setVerticalSpacing(10)
        pr_form.setContentsMargins(12, 12, 12, 12)
        pr_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        pr_help_row = QHBoxLayout()
        pr_help_label = QLabel("Creates a GitHub or Bitbucket PR from one existing branch into another.")
        pr_help_label.setWordWrap(True)
        pr_help_row.addWidget(pr_help_label, 1)
        pr_help_row.addWidget(
            self._info_button(
                "This only creates a pull request record with the provider. "
                "It does not commit, push, merge, rebase, modify files, or change your local repository. "
                "Your work must already be committed and pushed to the selected source branch. "
                "If the source and target branches have conflicts, the provider will show that on the PR."
            )
        )
        pr_form.addRow(pr_help_row)

        self.pr_title = QLineEdit()
        self.pr_title.setMinimumWidth(640)
        self.pr_title.setPlaceholderText("Short, descriptive PR title")
        self.pr_title.editingFinished.connect(self._store_pr_title)
        pr_form.addRow("Title:", self.pr_title)

        self.pr_description = QTextEdit(self)
        self.pr_description.setMinimumWidth(640)
        self.pr_description.setPlaceholderText("Optional PR description")
        self.pr_description.setFixedHeight(160)
        self.pr_description.textChanged.connect(self._store_pr_description)
        pr_form.addRow("Description:", self.pr_description)

        self.draft_checkbox = QCheckBox("Create as draft when supported", self)
        pr_form.addRow("Draft:", self.draft_checkbox)

        main.addWidget(pr_group)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        create_btn = QPushButton("Create PR")
        create_btn.setFixedHeight(34)
        create_btn.setStyleSheet(
            "QPushButton {"
            "background-color: #0b63ce;"
            "color: white;"
            "font-weight: 700;"
            "border: 1px solid #084b9e;"
            "border-radius: 6px;"
            "padding: 6px 14px;"
            "}"
            "QPushButton:hover { background-color: #0958b8; }"
            "QPushButton:pressed { background-color: #074894; }"
            "QPushButton:disabled { background-color: #7aa8df; color: #f3f7ff; }"
        )
        create_btn.clicked.connect(self.create_pr)
        btn_layout.addWidget(create_btn)
        self.create_btn = create_btn
        self._create_btn_label = create_btn.text()

        main.addLayout(btn_layout)
        main.addStretch()

    def _store_pr_title(self):
        self.config.set_pr_title(self.pr_title.text().strip())

    def _store_pr_description(self):
        self.config.set_pr_description(self.pr_description.toPlainText().strip())

    def _store_source_branch(self, branch):
        self.config.set_source_branch(branch)

    def _store_target_branch(self, branch):
        self.config.set_target_branch(branch)

    def browse_local_checkout(self):
        selected_repo = self._selected_repo()
        if not selected_repo:
            QMessageBox.warning(self, "Selection Required", "Select a repository first.")
            return

        start_dir = self._repo_local_dir(selected_repo) or os.path.expanduser("~")
        directory = QFileDialog.getExistingDirectory(self, "Select Local Repository Checkout", start_dir)
        if not directory:
            return
        if not self._is_git_checkout(directory):
            QMessageBox.warning(
                self,
                "Invalid Checkout",
                "Select a local Git checkout for the selected repository.",
            )
            return

        repo_id = str(selected_repo.get("id", ""))
        selected_repo["local_dir"] = directory
        index = self.repo_combo.currentIndex()
        if index >= 0:
            self.repo_combo.setItemData(index, dict(selected_repo))

        selected_repos = []
        for repo in self.config.get_selected_repositories() or []:
            repo_copy = dict(repo or {})
            if str(repo_copy.get("id", "")) == repo_id:
                repo_copy["local_dir"] = directory
            selected_repos.append(repo_copy)
        if selected_repos:
            self.config.set_selected_repositories(selected_repos)

        active_repo = self.config.get_active_repository() or {}
        if str(active_repo.get("id", "")) == repo_id:
            active_repo = dict(active_repo)
            active_repo["local_dir"] = directory
            self.config.set_active_repository(active_repo)

        self._apply_selected_repository(auto_refresh=True)

    def refresh_branches(self, auto=False):
        selected_repo = self._selected_repo()
        if not selected_repo:
            if not auto:
                QMessageBox.warning(self, "Selection Required", "Select a repository first.")
            return

        repo_dir = self._repo_local_dir(selected_repo)
        if not repo_dir:
            if not auto:
                QMessageBox.warning(
                    self,
                    "Local Checkout Required",
                    "The selected repository does not have a local checkout yet. Use Settings to prepare repositories.",
                )
            return

        def sync_branch_lists(output):
            branches = [b.strip() for b in output.splitlines() if b.strip().startswith("origin/")]
            self.src_selector.set_items(branches)
            self.dst_selector.set_items(branches)

            stored_source = self.config.get_source_branch()
            stored_target = self.config.get_target_branch()
            self.src_selector.set_current_text(stored_source or "")
            self.dst_selector.set_current_text(stored_target or "")

        if not self.task_runner:
            try:
                output = self._fetch_remote_branches_output(repo_dir)
                sync_branch_lists(output)
            except Exception as exc:  # noqa: BLE001
                if not auto:
                    QMessageBox.critical(self, "Error", f"Failed to load branches:\n{exc}")
            return

        self._set_refresh_state(True)

        def task():
            try:
                output = self._fetch_remote_branches_output(repo_dir)
                return {"ok": True, "output": output}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": str(exc)}

        def on_success(result):
            if not isinstance(result, dict):
                if not auto:
                    QMessageBox.critical(self, "Error", "Failed to load branches.")
                return
            if result.get("ok"):
                sync_branch_lists(result.get("output", ""))
                return
            if not auto:
                QMessageBox.critical(self, "Error", f"Failed to load branches:\n{result.get('error', '')}")

        def on_error(exc: Exception):
            if not auto:
                QMessageBox.critical(self, "Error", f"Failed to load branches:\n{exc}")

        self.task_runner.run(
            task,
            description="Refresh Branches",
            on_result=on_success,
            on_error=on_error,
            on_finished=lambda: self._set_refresh_state(False),
        )

    def create_pr(self):
        selected_repo = self._selected_repo()
        if not selected_repo:
            QMessageBox.warning(self, "Selection Required", "Select a repository first.")
            return

        source = self.src_selector.current_text().replace("origin/", "").strip()
        target = self.dst_selector.current_text().replace("origin/", "").strip()
        title = self.pr_title.text().strip()
        description = self.pr_description.toPlainText().strip()

        if not all(((selected_repo.get("owner") or "").strip(), (selected_repo.get("slug") or selected_repo.get("name") or "").strip(), source, target, title)):
            QMessageBox.warning(
                self,
                "Input Error",
                "Repository, source branch, target branch, and title are required.",
            )
            return
        request = PullRequestCreateRequest(
            title=title,
            description=description,
            source_branch=source,
            target_branch=target,
            draft=self.draft_checkbox.isChecked(),
        )

        if not self.task_runner:
            self._create_pr_sync(selected_repo, request)
            return

        self._set_create_state(True)

        def task():
            return self.pr_creation_service.create_pull_request(selected_repo, request)

        def on_success(result):
            message = f"Pull request created:\n{result.get('url') or '(no URL returned)'}"
            warnings = result.get("warnings") or []
            if warnings:
                message += "\n\nWarnings:\n- " + "\n- ".join(str(item) for item in warnings)
            QMessageBox.information(self, "PR Created", message)

        def on_error(exc: Exception):
            QMessageBox.critical(self, "Error", f"Failed to create PR:\n{exc}")

        self.task_runner.run(
            task,
            description="Create Pull Request",
            on_result=on_success,
            on_error=on_error,
            on_finished=lambda: self._set_create_state(False),
        )

    def set_repo(self, repo_dir):
        block = self.repo_input.blockSignals(True)
        self.repo_input.setText(repo_dir)
        self.repo_input.blockSignals(block)

    def apply_repo_config(self):
        self._populate_repository_combo()
        self.pr_title.setText(self.config.get_pr_title())
        self.pr_description.blockSignals(True)
        self.pr_description.setPlainText(self.config.get_pr_description())
        self.pr_description.blockSignals(False)

        self.src_selector.set_current_text(self.config.get_source_branch() or "")
        self.dst_selector.set_current_text(self.config.get_target_branch() or "")
        self._apply_selected_repository(auto_refresh=True)

    def _populate_repository_combo(self):
        repositories = [
            dict(repo or {})
            for repo in (self.config.get_selected_repositories() or [])
            if (repo or {}).get("id")
        ]
        active_repo = self.config.get_active_repository() or {}
        if not repositories and active_repo.get("id"):
            repositories = [dict(active_repo)]

        current_id = ""
        current = self._selected_repo()
        if current:
            current_id = str(current.get("id", ""))
        if not current_id:
            current_id = str(active_repo.get("id", ""))

        block = self.repo_combo.blockSignals(True)
        self.repo_combo.clear()
        for repo in repositories:
            self.repo_combo.addItem(self._repo_label(repo), repo)
        if current_id:
            for index in range(self.repo_combo.count()):
                repo = self.repo_combo.itemData(index) or {}
                if str(repo.get("id", "")) == current_id:
                    self.repo_combo.setCurrentIndex(index)
                    break
        self.repo_combo.blockSignals(block)

    def _on_repository_changed(self):
        self._apply_selected_repository(auto_refresh=True)

    def _apply_selected_repository(self, auto_refresh=False):
        selected_repo = self._selected_repo()
        if not selected_repo:
            self.set_repo("")
            self.repo_summary_label.setText("No selected repository is available. Choose repositories in Settings.")
            self.refresh_btn.setEnabled(False)
            self.create_btn.setEnabled(False)
            return

        repo_dir = self._repo_local_dir(selected_repo)
        workspace = selected_repo.get("owner") or self.config.get_bitbucket_workspace() or "(missing workspace)"
        slug = selected_repo.get("slug") or selected_repo.get("name") or "(missing slug)"
        self.set_repo(repo_dir)
        self.repo_summary_label.setText(f"{workspace}/{slug}")
        self.refresh_btn.setEnabled(bool(repo_dir))
        self.create_btn.setEnabled(True)
        self.repoChanged.emit(repo_dir)

        if repo_dir and auto_refresh:
            now = time.time()
            if (
                repo_dir != self._last_auto_refresh_repo
                or (now - self._last_auto_refresh_ts) > 120
            ):
                self._last_auto_refresh_repo = repo_dir
                self._last_auto_refresh_ts = now
                self.refresh_branches(auto=True)

    def _selected_repo(self):
        if not hasattr(self, "repo_combo") or self.repo_combo.count() <= 0:
            return None
        repo = self.repo_combo.currentData()
        return repo if isinstance(repo, dict) else None

    @staticmethod
    def _repo_label(repo):
        owner = repo.get("owner") or ""
        slug = repo.get("slug") or repo.get("name") or ""
        return f"{owner}/{slug}".strip("/") or "Unknown repository"

    @staticmethod
    def _repo_local_dir(repo):
        local_dir = (repo.get("local_dir") or "").strip()
        return local_dir if local_dir and os.path.isdir(local_dir) else ""

    @staticmethod
    def _is_git_checkout(path):
        if not path or not os.path.isdir(path):
            return False
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=path,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError:
            return False
        return result.stdout.strip().lower() == "true"

    def _set_refresh_state(self, busy):
        if not hasattr(self, "refresh_btn"):
            return
        self.refresh_btn.setText("Refreshing..." if busy else self._refresh_btn_label)
        self.refresh_btn.setEnabled(not busy and bool(self._repo_local_dir(self._selected_repo() or {})))

    def _set_create_state(self, busy):
        if not hasattr(self, "create_btn"):
            return
        self.create_btn.setText("Creating..." if busy else self._create_btn_label)
        self.create_btn.setEnabled(not busy and self._selected_repo() is not None)

    def _create_pr_sync(self, selected_repo, request: PullRequestCreateRequest):
        try:
            result = self.pr_creation_service.create_pull_request(selected_repo, request)
            message = f"Pull request created:\n{result.get('url') or '(no URL returned)'}"
            warnings = result.get("warnings") or []
            if warnings:
                message += "\n\nWarnings:\n- " + "\n- ".join(str(item) for item in warnings)
            QMessageBox.information(self, "PR Created", message)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"Failed to create PR:\n{exc}")

    def _fetch_remote_branches_output(self, repo):
        strategies = [
            [["git", "fetch", "origin"]],
            [["git", "fetch", "--prune", "origin"]],
            [["git", "remote", "prune", "origin"], ["git", "fetch", "--prune", "origin"]],
            [["git", "fetch", "origin", "+refs/heads/*:refs/remotes/origin/*"]],
        ]
        last_error = ""

        for commands in strategies:
            try:
                for command in commands:
                    subprocess.run(
                        command,
                        check=True,
                        cwd=repo,
                        capture_output=True,
                        text=True,
                    )
                result = subprocess.run(
                    ["git", "branch", "-r"],
                    capture_output=True,
                    text=True,
                    check=True,
                    cwd=repo,
                )
                return result.stdout
            except subprocess.CalledProcessError as exc:
                stderr = (exc.stderr or "").strip()
                stdout = (exc.stdout or "").strip()
                details = stderr or stdout or str(exc)
                last_error = details
                continue

        raise RuntimeError(last_error or "git fetch failed")
