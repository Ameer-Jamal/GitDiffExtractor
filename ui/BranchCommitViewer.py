import os
import platform
import subprocess
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QPushButton,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QLabel,
)
from ui.ListDelegates import BranchListDelegate, UI_ROLE


class BranchCommitViewer(QWidget):
    repoChanged = pyqtSignal(str)

    def __init__(self, config_manager, task_runner=None):
        super().__init__()

        self.config_manager = config_manager
        self.task_runner = task_runner
        self._branch_entries = []

        layout = QVBoxLayout()

        self.repo_context_label = QLabel(self)
        layout.addWidget(self.repo_context_label)

        # Active repository (selected in Settings)
        self.repo_input = QLineEdit(self)
        self.repo_input.setPlaceholderText('Select active repository in Settings')
        self.repo_input.setReadOnly(True)
        layout.addWidget(self.repo_input)

        # Base Branch Input
        self.base_branch_input = QLineEdit(self)
        self.base_branch_input.setPlaceholderText('Enter Base Branch (e.g., origin/release/2024c)')
        self.base_branch_input.editingFinished.connect(self._store_origin_branch)
        layout.addWidget(self.base_branch_input)

        # Button to load all branches
        self.load_branches_button = QPushButton('Load All Branches', self)
        self.load_branches_button.clicked.connect(self.loadBranches)
        layout.addWidget(self.load_branches_button)

        # Button to select origin branch
        self.set_origin_button = QPushButton('Set Selected Branch as Origin', self)
        self.set_origin_button.clicked.connect(self.setSelectedBranchAsOrigin)
        layout.addWidget(self.set_origin_button)

        # Branch search field
        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText('Search branch')
        self.search_input.textChanged.connect(self.searchBranches)
        layout.addWidget(self.search_input)

        # List to display branches
        self.branch_list = QListWidget(self)
        self.branch_list.itemDoubleClicked.connect(self.loadCommitsForBranch)
        self.branch_list.setItemDelegate(BranchListDelegate(self.branch_list))
        layout.addWidget(self.branch_list)

        # Button to get all commits for the selected branch
        self.get_commits_button = QPushButton('Get All Diffs for Selected Branch', self)
        self.get_commits_button.clicked.connect(self.loadCommitsForSelectedBranch)
        layout.addWidget(self.get_commits_button)

        self.setLayout(layout)
        self._load_button_label = self.load_branches_button.text()
        self._get_commits_label = self.get_commits_button.text()
        self.apply_repo_config()

    # ------------------------------------------------------------------
    # Configuration helpers
    def apply_repo_config(self):
        repo_dir = self.config_manager.get_repo_dir()
        origin_branch = self.config_manager.get_origin_branch()
        selected_count = len(self.config_manager.get_selected_repositories())

        self._set_line_edit_text(self.repo_input, repo_dir)
        if selected_count > 1:
            self.repo_context_label.setText(
                f"Showing branches across {selected_count} selected repositories."
            )
        elif selected_count == 1:
            self.repo_context_label.setText("Showing branches for selected repository.")
        else:
            self.repo_context_label.setText("No repository selected.")
        if origin_branch:
            self._set_line_edit_text(self.base_branch_input, origin_branch)
        else:
            self.base_branch_input.clear()

    @staticmethod
    def _set_line_edit_text(line_edit, value):
        block = line_edit.blockSignals(True)
        line_edit.setText(value)
        line_edit.blockSignals(block)

    # ------------------------------------------------------------------
    # UI Callbacks
    def loadBranches(self):
        selected_repos = self._selected_repositories()
        if not selected_repos:
            QMessageBox.warning(
                self,
                "Input Error",
                "No repositories selected. Select repositories in Settings first.",
            )
            return

        if not self.task_runner:
            self._load_branches_sync(selected_repos)
            return

        self._set_loading_state(True, self.load_branches_button, "Loading branches…")

        def task():
            entries = []
            for repo in selected_repos:
                repo_dir = (repo.get("local_dir") or "").strip()
                if not repo_dir:
                    continue
                subprocess.run(['git', 'fetch', 'origin'], cwd=repo_dir, check=True, capture_output=True)
                result = subprocess.run(
                    ['git', 'branch', '-r'],
                    capture_output=True,
                    text=True,
                    check=True,
                    cwd=repo_dir,
                )
                repo_label = f"{repo.get('owner', '')}/{repo.get('slug', repo.get('name', ''))}"
                branches = [branch.strip() for branch in result.stdout.strip().splitlines() if branch.strip()]
                for branch in branches:
                    entries.append({
                        "repo": repo,
                        "repo_dir": repo_dir,
                        "repo_label": repo_label,
                        "branch": branch,
                    })
            return entries

        def on_result(entries):
            self._render_branches(entries)

        def on_error(exc: Exception):
            QMessageBox.critical(self, "Error", f"An error occurred while loading branches:\n{exc}")

        self.task_runner.run(
            task,
            description="Load Branches",
            on_result=on_result,
            on_error=on_error,
            on_finished=lambda: self._set_loading_state(False, self.load_branches_button),
        )

    def searchBranches(self):
        search_term = self.search_input.text().strip().lower()
        for i in range(self.branch_list.count()):
            item = self.branch_list.item(i)
            item.setHidden(search_term not in item.text().lower())

    def loadCommitsForBranch(self, item):
        payload = item.data(Qt.UserRole) or {}
        self.getCommitsForBranch(payload.get("branch"), payload.get("repo_dir"), payload.get("repo_label"))

    def loadCommitsForSelectedBranch(self):
        selected_items = self.branch_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Error", "No branch selected.")
            return
        payload = selected_items[0].data(Qt.UserRole) or {}
        self.getCommitsForBranch(payload.get("branch"), payload.get("repo_dir"), payload.get("repo_label"))

    def getCommitsForBranch(self, branch_name, repo_dir=None, repo_label=None):
        repo_dir = (repo_dir or self.repo_input.text().strip()).strip()
        base_branch = self.base_branch_input.text().strip()
        output_dir = self.config_manager.get_output_dir().strip()

        # Ensure the output directory exists, create it if it doesn't
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
            QMessageBox.information(self, "Directory Created", f"Output directory created: {output_dir}")

        if not repo_dir or not branch_name or not base_branch or not output_dir:
            QMessageBox.warning(
                self,
                "Input Error",
                "Repository path, base branch, branch, and output directory must be specified.",
            )
            return

        target_branch = branch_name
        origin_branch = base_branch
        if not branch_name.startswith('origin/'):
            target_branch = f'origin/{branch_name}'
        if not base_branch.startswith('origin/'):
            origin_branch = f'origin/{base_branch}'

        if not self.task_runner:
            self._get_commits_sync(repo_dir, origin_branch, target_branch, output_dir)
            return

        self._set_loading_state(True, self.get_commits_button, "Generating diff…")

        def task():
            subprocess.run(['git', 'fetch', 'origin'], cwd=repo_dir, check=True, capture_output=True)
            merge_base_result = subprocess.run(
                ['git', 'merge-base', origin_branch, target_branch],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            merge_base = merge_base_result.stdout.strip()
            if not merge_base:
                raise RuntimeError(
                    f"Unable to find common ancestor between {origin_branch} and {target_branch}."
                )

            diff_file_path = os.path.join(
                output_dir, f'all_commits_on_{target_branch.replace("/", "_")}.diff'
            )

            with open(diff_file_path, 'w', encoding='utf-8') as diff_file:
                subprocess.run(
                    ['git', 'diff', merge_base, target_branch],
                    cwd=repo_dir,
                    stdout=diff_file,
                    check=True,
                )

            return diff_file_path, target_branch

        def on_result(result):
            diff_file_path, resolved_branch = result
            QMessageBox.information(
                self,
                "Success",
                f"All diffs for branch {resolved_branch} "
                f"{f'({repo_label}) ' if repo_label else ''}saved to {diff_file_path}.",
            )
            self.openFile(diff_file_path)

        def on_error(exc: Exception):
            QMessageBox.critical(self, "Error", f"An error occurred:\n{exc}")

        self.task_runner.run(
            task,
            description="Generate Branch Diff",
            on_result=on_result,
            on_error=on_error,
            on_finished=lambda: self._set_loading_state(False, self.get_commits_button),
        )

    def openFile(self, file_path):
        if not os.path.exists(file_path):
            QMessageBox.critical(self, "File Error", f"File does not exist: {file_path}")
            return

        try:
            if platform.system() == "Darwin":
                subprocess.run(['open', file_path], check=True)
            elif platform.system() == "Windows":
                os.startfile(file_path)
            else:
                subprocess.run(['xdg-open', file_path], check=True)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"Failed to open file:\n{exc}")

    # ------------------------------------------------------------------
    # Internal helper utilities
    def _set_loading_state(self, loading, button, busy_text=None):
        button = button or self.load_branches_button
        if loading:
            if button is self.load_branches_button:
                self.load_branches_button.setText(busy_text or "Loading…")
            elif button is self.get_commits_button:
                self.get_commits_button.setText(busy_text or "Processing…")
        else:
            self.load_branches_button.setText(self._load_button_label)
            self.get_commits_button.setText(self._get_commits_label)

        widgets = [
            self.load_branches_button,
            self.set_origin_button,
            self.search_input,
            self.branch_list,
            self.get_commits_button,
        ]
        for widget in widgets:
            widget.setEnabled(not loading)

    def _load_branches_sync(self, selected_repos):
        try:
            entries = []
            for repo in selected_repos:
                repo_dir = (repo.get("local_dir") or "").strip()
                if not repo_dir:
                    continue
                subprocess.run(['git', 'fetch', 'origin'], cwd=repo_dir, check=True, capture_output=True)
                result = subprocess.run(
                    ['git', 'branch', '-r'],
                    capture_output=True,
                    text=True,
                    check=True,
                    cwd=repo_dir,
                )
                repo_label = f"{repo.get('owner', '')}/{repo.get('slug', repo.get('name', ''))}"
                branches = [branch.strip() for branch in result.stdout.strip().splitlines() if branch.strip()]
                for branch in branches:
                    entries.append({
                        "repo": repo,
                        "repo_dir": repo_dir,
                        "repo_label": repo_label,
                        "branch": branch,
                    })
            self._render_branches(entries)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"An error occurred while loading branches:\n{exc}")

    def _get_commits_sync(self, repo_dir, base_branch, target_branch, output_dir):
        try:
            subprocess.run(['git', 'fetch', 'origin'], cwd=repo_dir, check=True, capture_output=True)
            merge_base_result = subprocess.run(
                ['git', 'merge-base', base_branch, target_branch],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            merge_base = merge_base_result.stdout.strip()
            if not merge_base:
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Unable to find common ancestor between {base_branch} and {target_branch}.",
                )
                return

            diff_file_path = os.path.join(
                output_dir, f'all_commits_on_{target_branch.replace("/", "_")}.diff'
            )
            with open(diff_file_path, 'w', encoding='utf-8') as diff_file:
                subprocess.run(
                    ['git', 'diff', merge_base, target_branch],
                    cwd=repo_dir,
                    stdout=diff_file,
                    check=True,
                )

            QMessageBox.information(
                self, "Success", f"All diffs for branch {target_branch} saved to {diff_file_path}."
            )
            self.openFile(diff_file_path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"An error occurred:\n{exc}")

    def setSelectedBranchAsOrigin(self):
        selected_items = self.branch_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Error", "No branch selected.")
            return

        # Set the selected branch as the base/origin branch
        payload = selected_items[0].data(Qt.UserRole) or {}
        selected_branch = payload.get("branch") or selected_items[0].text().strip()
        self.base_branch_input.setText(selected_branch)
        self.config_manager.set_origin_branch(selected_branch)

    def _store_origin_branch(self):
        origin_branch = self.base_branch_input.text().strip()
        self.config_manager.set_origin_branch(origin_branch)

    def _selected_repositories(self):
        selected = self.config_manager.get_selected_repositories() or []
        if selected:
            return selected
        active = self.config_manager.get_active_repository() or {}
        return [active] if active.get("id") else []

    def _render_branches(self, entries):
        self._branch_entries = entries or []
        self.branch_list.clear()
        self.branch_list.setUpdatesEnabled(False)
        for entry in self._branch_entries:
            repo_label = entry.get('repo_label', 'repo')
            branch_name = entry.get('branch', '')
            item = QListWidgetItem()
            item.setText(f"{repo_label} {branch_name}".lower())
            item.setData(Qt.UserRole, entry)
            item.setData(UI_ROLE, {"repo_label": repo_label, "branch": branch_name})
            self.branch_list.addItem(item)
        self.branch_list.setUpdatesEnabled(True)
