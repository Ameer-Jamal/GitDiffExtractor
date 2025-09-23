import os
import platform
import subprocess
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QPushButton,
    QLineEdit,
    QListWidget,
    QMessageBox,
)


class BranchCommitViewer(QWidget):
    repoChanged = pyqtSignal(str)

    def __init__(self, config_manager):
        super().__init__()

        self.config_manager = config_manager

        layout = QVBoxLayout()

        # UI for repository input
        self.repo_input = QLineEdit(self)
        self.repo_input.setPlaceholderText('Enter repository path')
        self.repo_input.editingFinished.connect(self._on_repo_finished)
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
        layout.addWidget(self.branch_list)

        # Button to get all commits for the selected branch
        self.get_commits_button = QPushButton('Get All Diffs for Selected Branch', self)
        self.get_commits_button.clicked.connect(self.loadCommitsForSelectedBranch)
        layout.addWidget(self.get_commits_button)

        self.setLayout(layout)
        self.apply_repo_config()

    # ------------------------------------------------------------------
    # Configuration helpers
    def apply_repo_config(self):
        repo_dir = self.config_manager.get_repo_dir()
        origin_branch = self.config_manager.get_origin_branch()

        self._set_line_edit_text(self.repo_input, repo_dir)
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
        repo_dir = self.repo_input.text().strip()
        if not repo_dir:
            QMessageBox.warning(self, "Input Error", "Repository path must be provided.")
            return

        try:
            os.chdir(repo_dir)
            # Ensure the local repo is up to date with the remote
            subprocess.run(['git', 'fetch', 'origin'], check=True)

            # Load all branches (including remote)
            result = subprocess.run(['git', 'branch', '-r'], capture_output=True, text=True)
            branches = result.stdout.strip().splitlines()

            self.branch_list.clear()
            for branch in branches:
                self.branch_list.addItem(branch.strip())

        except Exception as e:
            QMessageBox.critical(self, "Error", f"An error occurred while loading branches: {str(e)}")

    def searchBranches(self):
        search_term = self.search_input.text().strip().lower()
        for i in range(self.branch_list.count()):
            item = self.branch_list.item(i)
            item.setHidden(search_term not in item.text().lower())

    def loadCommitsForBranch(self, item):
        branch_name = item.text().strip()
        self.getCommitsForBranch(branch_name)

    def loadCommitsForSelectedBranch(self):
        selected_items = self.branch_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Error", "No branch selected.")
            return
        branch_name = selected_items[0].text().strip()
        self.getCommitsForBranch(branch_name)

    def getCommitsForBranch(self, branch_name):
        repo_dir = self.repo_input.text().strip()
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

        try:
            os.chdir(repo_dir)

            # Ensure branches are up to date
            subprocess.run(['git', 'fetch', 'origin'], check=True)

            # If the branch is remote, ensure we are using the correct format for remote branches
            if not branch_name.startswith('origin/'):
                branch_name = f'origin/{branch_name}'

            # Use the base branch as inputted by the user
            if not base_branch.startswith('origin/'):
                base_branch = f'origin/{base_branch}'

            # Find the common ancestor (where the branch diverged from the base branch)
            merge_base_result = subprocess.run(
                ['git', 'merge-base', base_branch, branch_name], capture_output=True, text=True
            )
            merge_base = merge_base_result.stdout.strip()

            if not merge_base:
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Unable to find common ancestor between {base_branch} and {branch_name}.",
                )
                return

            # Generate diff from the point where the branch diverged from the base
            diff_file_path = os.path.join(
                output_dir, f'all_commits_on_{branch_name.replace("/", "_")}.diff'
            )

            with open(diff_file_path, 'w') as diff_file:
                subprocess.run(['git', 'diff', merge_base, branch_name], stdout=diff_file)

            # Inform the user and open the file
            QMessageBox.information(
                self, "Success", f"All diffs for branch {branch_name} saved to {diff_file_path}."
            )
            self.openFile(diff_file_path)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"An error occurred: {str(e)}")

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
        except subprocess.CalledProcessError as e:
            QMessageBox.critical(self, "Error", f"Failed to open file: {str(e)}")

    def setSelectedBranchAsOrigin(self):
        selected_items = self.branch_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Error", "No branch selected.")
            return

        # Set the selected branch as the base/origin branch
        selected_branch = selected_items[0].text().strip()
        self.base_branch_input.setText(selected_branch)
        self.config_manager.set_origin_branch(selected_branch)

    def _on_repo_finished(self):
        repo_dir = self.repo_input.text().strip()
        self.repoChanged.emit(repo_dir)

    def _store_origin_branch(self):
        origin_branch = self.base_branch_input.text().strip()
        self.config_manager.set_origin_branch(origin_branch)
