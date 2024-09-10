import os
import platform
import subprocess
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLineEdit, QListWidget, QMessageBox

from ConfigManager import ConfigManager


class BranchCommitViewer(QWidget):
    def __init__(self):
        super().__init__()

        layout = QVBoxLayout()

        # UI for repository input
        self.repo_input = QLineEdit(self)
        self.config_manager = ConfigManager()
        self.default_output_dir = self.config_manager.get_output_dir()
        self.default_repo_dir = self.config_manager.get_repo_dir()

        # Corrected conditional check
        if not self.default_repo_dir:
            self.repo_input.setPlaceholderText('Enter repository path')
        else:
            self.repo_input.setText(self.default_repo_dir)

        layout.addWidget(self.repo_input)

        # Base Branch Input
        self.base_branch_input = QLineEdit(self)
        self.default_base_branch = self.config_manager.get_origin_branch()
        if not self.default_base_branch:
            self.base_branch_input.setPlaceholderText('Enter Base Branch (e.g., origin/release/2024c)')
        else:
            self.base_branch_input.setText(self.default_base_branch)
        layout.addWidget(self.base_branch_input)

        # Button to load all branches
        self.load_branches_button = QPushButton('Load All Branches', self)
        self.load_branches_button.clicked.connect(self.loadBranches)
        layout.addWidget(self.load_branches_button)

        # Button to select origin branch
        self.load_branches_button = QPushButton('Set Selected Branch as Origin', self)
        self.load_branches_button.clicked.connect(self.setSelectedBranchAsOrigin)
        layout.addWidget(self.load_branches_button)

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

        if not repo_dir or not branch_name or not base_branch or not output_dir:
            QMessageBox.warning(self, "Input Error",
                                "Repository path, base branch, branch, and output directory must be specified.")
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
            merge_base_result = subprocess.run(['git', 'merge-base', base_branch, branch_name], capture_output=True,
                                               text=True)
            merge_base = merge_base_result.stdout.strip()

            if not merge_base:
                QMessageBox.critical(self, "Error",
                                     f"Unable to find common ancestor between {base_branch} and {branch_name}.")
                return

            # Generate diff from the point where the branch diverged from the base
            diff_file_path = os.path.join(output_dir, f'all_commits_on_{branch_name.replace("/", "_")}.diff')

            with open(diff_file_path, 'w') as diff_file:
                subprocess.run(['git', 'diff', merge_base, branch_name], stdout=diff_file)

            # Inform the user and open the file
            QMessageBox.information(self, "Success", f"All diffs for branch {branch_name} saved to {diff_file_path}.")
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
        self.default_base_branch = self.config_manager.set_origin_branch(selected_branch)
