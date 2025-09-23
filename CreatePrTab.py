# File: create_pr_tab.py

import os
import subprocess
import requests

from PyQt5.QtCore    import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLineEdit, QPushButton, QLabel, QFileDialog, QMessageBox, QFrame
)
from FilterableBranchSelector import FilterableBranchSelector


class CreatePRTab(QWidget):
    repoChanged = pyqtSignal(str)

    def __init__(self, config_manager):
        super().__init__()
        self.config = config_manager
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

        # Repository path + Browse button
        self.repo_input = QLineEdit(self.config.get_repo_dir())
        browse_btn     = QPushButton("Browse")
        browse_btn.clicked.connect(self._browse_repo)
        path_layout    = QHBoxLayout()
        path_layout.addWidget(self.repo_input)
        path_layout.addWidget(browse_btn)
        repo_form.addRow("Repository Path:", path_layout)
        self.repo_input.editingFinished.connect(self._handle_repo_edited)

        # Bitbucket credentials & slug
        self.bb_user = QLineEdit(self.config.get_bitbucket_username())
        repo_form.addRow("Username:", self.bb_user)
        self.bb_user.editingFinished.connect(self._store_bitbucket_user)

        self.bb_pwd = QLineEdit(self.config.get_bitbucket_app_password())
        self.bb_pwd.setEchoMode(QLineEdit.Password)
        repo_form.addRow("App Password:", self.bb_pwd)
        self.bb_pwd.editingFinished.connect(self._store_bitbucket_password)

        self.bb_workspace = QLineEdit(self.config.get_bitbucket_workspace())
        repo_form.addRow("Workspace:", self.bb_workspace)
        self.bb_workspace.editingFinished.connect(self._store_bitbucket_workspace)

        self.bb_slug = QLineEdit(self.config.get_repo_slug())
        repo_form.addRow("Repo Slug:", self.bb_slug)
        self.bb_slug.editingFinished.connect(self._store_repo_slug)

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

        create_btn = QPushButton("Create PR")
        create_btn.setFixedHeight(30)
        create_btn.clicked.connect(self.create_pr)
        btn_layout.addWidget(create_btn)

        main.addLayout(btn_layout)


    def _browse_repo(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Repository")
        if directory:
            self.repo_input.setText(directory)
            self.repoChanged.emit(directory)

    def _handle_repo_edited(self):
        repo_dir = self.repo_input.text().strip()
        self.repoChanged.emit(repo_dir)

    def _store_bitbucket_user(self):
        self.config.set_bitbucket_username(self.bb_user.text().strip())

    def _store_bitbucket_password(self):
        self.config.set_bitbucket_app_password(self.bb_pwd.text().strip())

    def _store_bitbucket_workspace(self):
        self.config.set_bitbucket_workspace(self.bb_workspace.text().strip())

    def _store_repo_slug(self):
        self.config.set_repo_slug(self.bb_slug.text().strip())

    def _store_pr_title(self):
        self.config.set_pr_title(self.pr_title.text().strip())

    def _store_source_branch(self, branch):
        self.config.set_source_branch(branch)

    def _store_target_branch(self, branch):
        self.config.set_target_branch(branch)


    def refresh_branches(self, auto=False):
        repo = self.repo_input.text().strip()
        if not repo:
            if not auto:
                QMessageBox.warning(self, "Input Error", "Please select a repository directory.")
            return

        try:
            os.chdir(repo)
            subprocess.run(['git', 'fetch', 'origin'], check=True, stdout=subprocess.DEVNULL)
            output = subprocess.run(
                ['git', 'branch', '-r'],
                capture_output=True, text=True, check=True
            ).stdout

            branches = [b.strip() for b in output.splitlines() if b.strip().startswith('origin/')]
            self.src_selector.set_items(branches)
            self.dst_selector.set_items(branches)

            stored_source = self.config.get_source_branch()
            stored_target = self.config.get_target_branch()
            if stored_source:
                self.src_selector.set_current_text(stored_source)
            if stored_target:
                self.dst_selector.set_current_text(stored_target)

        except Exception as e:
            if not auto:
                QMessageBox.critical(self, "Error", f"Failed to load branches:\n{e}")


    def create_pr(self):
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

        try:
            response = requests.post(url, auth=(u, p), json=payload)
            response.raise_for_status()
            link = response.json()["links"]["html"]["href"]
            QMessageBox.information(self, "PR Created", f"Pull request created:\n{link}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to create PR:\n{e}")

    # ------------------------------------------------------------------
    # Synchronisation helpers
    def set_repo(self, repo_dir):
        block = self.repo_input.blockSignals(True)
        self.repo_input.setText(repo_dir)
        self.repo_input.blockSignals(block)

    def apply_repo_config(self):
        repo_dir = self.config.get_repo_dir()
        self.set_repo(repo_dir)

        self.bb_user.setText(self.config.get_bitbucket_username())
        self.bb_pwd.setText(self.config.get_bitbucket_app_password())
        self.bb_workspace.setText(self.config.get_bitbucket_workspace())
        self.bb_slug.setText(self.config.get_repo_slug())
        self.pr_title.setText(self.config.get_pr_title())

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

        if repo_dir:
            self.refresh_branches(auto=True)
