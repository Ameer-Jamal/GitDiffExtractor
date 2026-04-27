# File: create_pr_tab.py

import os
import subprocess
import time
import requests

from PyQt5.QtCore    import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLineEdit, QPushButton, QLabel, QMessageBox
)
from FilterableBranchSelector import FilterableBranchSelector


class CreatePRTab(QWidget):
    repoChanged = pyqtSignal(str)

    def __init__(self, config_manager, task_runner=None):
        super().__init__()
        self.config = config_manager
        self.task_runner = task_runner
        self._last_auto_refresh_repo = ""
        self._last_auto_refresh_ts = 0.0
        self._build_ui()

    def _build_ui(self):
        # Main vertical layout
        main = QVBoxLayout(self)
        main.setContentsMargins(15, 15, 15, 15)
        main.setSpacing(20)

        # ── Repository Settings ───────────────────────────────────────────────
        repo_group = QGroupBox("Repository Settings")
        repo_form  = QFormLayout()
        repo_form.setLabelAlignment(Qt.AlignRight)
        repo_form.setFormAlignment(Qt.AlignLeft)
        repo_form.setHorizontalSpacing(12)
        repo_form.setVerticalSpacing(8)

        # Active repository path (selected in Settings)
        self.repo_input = QLineEdit(self.config.get_repo_dir())
        self.repo_input.setReadOnly(True)
        self.repo_input.setPlaceholderText("Select active repository in Settings")
        path_layout    = QHBoxLayout()
        path_layout.addWidget(self.repo_input)
        repo_form.addRow("Repository Path:", path_layout)
        self.repo_context_label = QLabel(self)
        repo_form.addRow("Selection Context:", self.repo_context_label)

        # Bitbucket credentials & slug
        self.bb_user = QLineEdit(self.config.get_bitbucket_username())
        repo_form.addRow("Username:", self.bb_user)
        self.bb_user.editingFinished.connect(self._store_bitbucket_user)

        self.bb_pwd = QLineEdit(self.config.get_bitbucket_app_password())
        self.bb_pwd.setEchoMode(QLineEdit.Password)
        repo_form.addRow("App Password:", self.bb_pwd)
        self.bb_pwd.editingFinished.connect(self._store_bitbucket_password)

        self.bb_workspace = QLineEdit(self.config.get_bitbucket_workspace())
        self.bb_workspace.setReadOnly(True)
        self.bb_workspace.setPlaceholderText("Set by active repository")
        repo_form.addRow("Workspace:", self.bb_workspace)

        self.bb_slug = QLineEdit(self.config.get_repo_slug())
        self.bb_slug.setReadOnly(True)
        self.bb_slug.setPlaceholderText("Set by active repository")
        repo_form.addRow("Repo Slug:", self.bb_slug)

        repo_group.setLayout(repo_form)
        main.addWidget(repo_group)

        # ── Branch Selection ────────────────────────────────────────────────
        branch_group = QGroupBox("Branch Selection")
        branch_form  = QFormLayout()
        branch_form.setLabelAlignment(Qt.AlignRight)
        branch_form.setFormAlignment(Qt.AlignLeft)
        branch_form.setHorizontalSpacing(12)
        branch_form.setVerticalSpacing(8)

        self.src_selector = FilterableBranchSelector(self)
        branch_form.addRow("Source Branch:", self.src_selector)
        self.src_selector.selectionChanged.connect(self._store_source_branch)

        self.dst_selector = FilterableBranchSelector(self)
        branch_form.addRow("Target Branch:", self.dst_selector)
        self.dst_selector.selectionChanged.connect(self._store_target_branch)

        branch_group.setLayout(branch_form)
        main.addWidget(branch_group)

        # ── Pull Request Details ────────────────────────────────────────────
        pr_group = QGroupBox("Pull Request Details")
        pr_form  = QFormLayout()
        pr_form.setLabelAlignment(Qt.AlignRight)
        pr_form.setFormAlignment(Qt.AlignLeft)
        pr_form.setHorizontalSpacing(12)
        pr_form.setVerticalSpacing(8)

        self.pr_title = QLineEdit()
        pr_form.addRow("PR Title:", self.pr_title)
        self.pr_title.editingFinished.connect(self._store_pr_title)

        pr_group.setLayout(pr_form)
        main.addWidget(pr_group)

        # ── Actions ──────────────────────────────────────────────────────────
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        refresh_btn = QPushButton("Refresh Branches")
        refresh_btn.setFixedHeight(30)
        refresh_btn.clicked.connect(self.refresh_branches)
        btn_layout.addWidget(refresh_btn)
        self.refresh_btn = refresh_btn
        self._refresh_btn_label = refresh_btn.text()

        create_btn = QPushButton("Create PR")
        create_btn.setFixedHeight(30)
        create_btn.clicked.connect(self.create_pr)
        btn_layout.addWidget(create_btn)
        self.create_btn = create_btn
        self._create_btn_label = create_btn.text()

        main.addLayout(btn_layout)


    def _store_bitbucket_user(self):
        self.config.set_bitbucket_username(self.bb_user.text().strip())

    def _store_bitbucket_password(self):
        self.config.set_bitbucket_app_password(self.bb_pwd.text().strip())

    def _store_pr_title(self):
        self.config.set_pr_title(self.pr_title.text().strip())

    def _store_source_branch(self, branch):
        self.config.set_source_branch(branch)

    def _store_target_branch(self, branch):
        self.config.set_target_branch(branch)


    def refresh_branches(self, auto=False):
        if not self._ensure_single_repo_context("refresh branches", show_dialog=not auto):
            return

        repo = self.repo_input.text().strip()
        if not repo:
            if not auto:
                QMessageBox.warning(
                    self,
                    "Input Error",
                    "Active repository is not set. Select one in Settings first.",
                )
            return

        def sync_branch_lists(output):
            branches = [b.strip() for b in output.splitlines() if b.strip().startswith('origin/')]
            self.src_selector.set_items(branches)
            self.dst_selector.set_items(branches)

            stored_source = self.config.get_source_branch()
            stored_target = self.config.get_target_branch()
            if stored_source:
                self.src_selector.set_current_text(stored_source)
            if stored_target:
                self.dst_selector.set_current_text(stored_target)

        if not self.task_runner:
            try:
                output = self._fetch_remote_branches_output(repo)
                sync_branch_lists(output)
            except Exception as e:  # noqa: BLE001
                if not auto:
                    QMessageBox.critical(self, "Error", f"Failed to load branches:\n{e}")
            return

        self._set_refresh_state(True)

        def task():
            try:
                output = self._fetch_remote_branches_output(repo)
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
        if not self._ensure_single_repo_context("create a pull request"):
            return

        u    = self.bb_user.text().strip()
        p    = self.bb_pwd.text().strip()
        workspace = self.bb_workspace.text().strip()
        slug = self.bb_slug.text().strip()
        src  = self.src_selector.current_text().replace('origin/', '').strip()
        dst  = self.dst_selector.current_text().replace('origin/', '').strip()
        title= self.pr_title.text().strip()

        if not all((u, p, workspace, slug, src, dst, title)):
            QMessageBox.warning(self, "Input Error", "All fields are required.")
            return

        url = f"https://api.bitbucket.org/2.0/repositories/{workspace}/{slug}/pullrequests"
        payload = {
            "title": title,
            "source":      {"branch": {"name": src}},
            "destination": {"branch": {"name": dst}},
            "close_source_branch": False
        }

        if not self.task_runner:
            self._create_pr_sync(url, u, p, payload)
            return

        self._set_create_state(True)

        def task():
            response = requests.post(url, auth=(u, p), json=payload, timeout=15)
            response.raise_for_status()
            link = response.json()["links"]["html"]["href"]
            return link

        def on_success(link):
            QMessageBox.information(self, "PR Created", f"Pull request created:\n{link}")

        def on_error(exc: Exception):
            QMessageBox.critical(self, "Error", f"Failed to create PR:\n{exc}")

        self.task_runner.run(
            task,
            description="Create Pull Request",
            on_result=on_success,
            on_error=on_error,
            on_finished=lambda: self._set_create_state(False),
        )

    # ------------------------------------------------------------------
    # Synchronisation helpers
    def set_repo(self, repo_dir):
        block = self.repo_input.blockSignals(True)
        self.repo_input.setText(repo_dir)
        self.repo_input.blockSignals(block)

    def apply_repo_config(self):
        repo_dir = self.config.get_repo_dir()
        selected_count = len(self.config.get_selected_repositories())
        self.set_repo(repo_dir)

        self.bb_user.setText(self.config.get_bitbucket_username())
        self.bb_pwd.setText(self.config.get_bitbucket_app_password())
        active_repo = self.config.get_active_repository()
        self.bb_workspace.setText(active_repo.get("owner") or self.config.get_bitbucket_workspace())
        self.bb_slug.setText(active_repo.get("slug") or "")
        self.pr_title.setText(self.config.get_pr_title())

        if selected_count > 1:
            self.repo_context_label.setText(
                f"Multiple repositories selected ({selected_count}). "
                "Create PR works only with one repository."
            )
        elif selected_count == 1:
            self.repo_context_label.setText("Single repository selected. PR creation enabled.")
        else:
            self.repo_context_label.setText("No repository selected.")

        src_branch = self.config.get_source_branch()
        dst_branch = self.config.get_target_branch()
        if src_branch:
            self.src_selector.set_current_text(src_branch)
        else:
            self.src_selector.set_current_text("")

        if dst_branch:
            self.dst_selector.set_current_text(dst_branch)
        else:
            self.dst_selector.set_current_text("")

        if repo_dir and selected_count == 1:
            now = time.time()
            if (
                repo_dir != self._last_auto_refresh_repo
                or (now - self._last_auto_refresh_ts) > 120
            ):
                self._last_auto_refresh_repo = repo_dir
                self._last_auto_refresh_ts = now
                self.refresh_branches(auto=True)

    def _ensure_single_repo_context(self, action_name, show_dialog=True):
        selected_count = len(self.config.get_selected_repositories())
        if selected_count == 1:
            return True

        if not show_dialog:
            return False

        if selected_count == 0:
            QMessageBox.warning(
                self,
                "Selection Required",
                "No repository selected.\nSelect one repository in Settings first.",
            )
        else:
            QMessageBox.information(
                self,
                "Single Repository Required",
                f"You have {selected_count} repositories selected.\n"
                f"To {action_name}, select exactly one repository in Settings.",
            )
        return False

    # ------------------------------------------------------------------
    # Internal helpers
    def _set_refresh_state(self, busy):
        if not hasattr(self, 'refresh_btn'):
            return
        if busy:
            self.refresh_btn.setText("Refreshing…")
        else:
            self.refresh_btn.setText(self._refresh_btn_label)
        self.refresh_btn.setEnabled(not busy)

    def _set_create_state(self, busy):
        if not hasattr(self, 'create_btn'):
            return
        if busy:
            self.create_btn.setText("Creating…")
        else:
            self.create_btn.setText(self._create_btn_label)
        self.create_btn.setEnabled(not busy)

    def _create_pr_sync(self, url, username, password, payload):
        try:
            response = requests.post(url, auth=(username, password), json=payload, timeout=15)
            response.raise_for_status()
            link = response.json()["links"]["html"]["href"]
            QMessageBox.information(self, "PR Created", f"Pull request created:\n{link}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"Failed to create PR:\n{exc}")

    def _fetch_remote_branches_output(self, repo):
        """
        Fetch remotes with progressively stronger recovery strategies.
        Handles occasional ref-state corruption without crashing background startup refresh.
        """
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
                    ['git', 'branch', '-r'],
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
