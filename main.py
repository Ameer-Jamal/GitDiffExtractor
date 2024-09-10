import os
import platform
import re
import shutil
import subprocess

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QLabel, QLineEdit,
                             QPushButton, QFileDialog, QMessageBox, QHBoxLayout, QListWidget,
                             QListWidgetItem, QTabWidget)

from BranchCommitViewer import BranchCommitViewer
from ConfigManager import ConfigManager

#CONSTS:
INPUT_ERROR = "Input Error"


class GitDiffExtractor(QWidget):

    def __init__(self):
        super().__init__()
        # Initialize the ConfigManager
        self.config_manager = ConfigManager()
        self.default_output_dir = self.config_manager.get_output_dir();
        self.prs = []  # List to hold PRs
        # Initialize the QTabWidget
        self.tabs = QTabWidget()

        # Create the PR Diff Extractor UI and Branch Commit Viewer UI as separate widgets
        self.initUI()

        # Add both tabs to the QTabWidget
        self.tabs.addTab(self.prExtractDiffWidget(), "PR Diff Extractor")  # Default tab
        self.tabs.addTab(BranchCommitViewer(), "Branch Commit Viewer")

        # Set the layout for the main window
        main_layout = QVBoxLayout()
        main_layout.addWidget(self.tabs)
        self.setLayout(main_layout)

    def initUI(self):
        self.setWindowTitle('Git Diff Extractor')
        self.setGeometry(100, 100, 500, 600)

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
        commit_layout.addWidget(self.commit_input)
        layout.addLayout(commit_layout)

        # Output Directory
        output_layout = QHBoxLayout()
        self.output_label = QLabel('Output Directory:')
        output_layout.addWidget(self.output_label)
        self.output_input = QLineEdit(self)
        self.output_input.setText(self.config_manager.get_output_dir())  # Load last used output dir
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
        layout.addWidget(self.pr_list)

        # Load PRs Button
        self.pr_button = QPushButton('List Pull Requests', self)
        self.pr_button.clicked.connect(self.listPRs)
        layout.addWidget(self.pr_button)

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
            self.config_manager.set_repo_dir(directory)  # Save to config

    def browseOutput(self):
        directory = self.selectDirectory("Select Output Directory")
        if directory:
            self.output_input.setText(directory)
            self.config_manager.set_output_dir(directory)  # Save to config

    def selectDirectory(self, title):
        if platform.system() == "Darwin" and self.is_fman_available():
            return self.fman_select_directory(title)
        else:
            return QFileDialog.getExistingDirectory(self, title)

    def is_fman_available(self):
        return shutil.which("fman") is not None

    def fman_select_directory(self, title):
        subprocess.run(["fman", "--command", "select_directory"])
        file_path = "/tmp/fman_selected_directory.txt"
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                selected_directory = f.read().strip()
                return selected_directory
        else:
            QMessageBox.warning(self, "Error", "Failed to retrieve directory from fman.")
            return None

    def generateDiff(self):
        repo_dir = self.repo_input.text()
        commit_hashes = self.commit_input.text().replace(',', ' ').split()
        output_dir = self.output_input.text()

        if not repo_dir or not commit_hashes or not output_dir:
            QMessageBox.warning(self, INPUT_ERROR, "All fields must be filled out.")
            return

        try:
            os.chdir(repo_dir)

            for commit_hash in commit_hashes:
                result = subprocess.run(['git', 'rev-list', '--parents', '-n', '1', commit_hash],
                                        capture_output=True, text=True)
                parents = result.stdout.strip().split()

                if len(parents) < 3:
                    QMessageBox.warning(self, "Error", f"The specified commit {commit_hash} is not a merge commit.")
                    continue

                parent1 = parents[1]
                parent2 = parents[2]

                diff_file_path = os.path.join(output_dir, f'{commit_hash}_diff.txt')
                with open(diff_file_path, 'w') as diff_file:
                    subprocess.run(['git', 'diff', parent1, parent2], stdout=diff_file)

                self.openFile(diff_file_path)

            QMessageBox.information(self, "Success", "Diff files created and opened.")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"An error occurred: {str(e)}")

    def listPRs(self):
        repo_dir = self.repo_input.text()

        if not repo_dir:
            QMessageBox.warning(self, INPUT_ERROR, "Repository directory must be filled out.")
            return

        try:
            os.chdir(repo_dir)

            # Run the git command to list all pull requests
            result = subprocess.run(['git', 'log', '--merges', '--grep=pull request'],
                                    capture_output=True, text=True)

            if result.returncode != 0:
                print(f"Error: {result.stderr}")
                return

            # Split PRs by commit message separator
            self.prs = result.stdout.split("\ncommit ")
            self.displayPRs()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"An error occurred: {str(e)}")



    def displayPRs(self):
        """ Display PRs in the QListWidget with a separator. """
        self.pr_list.clear()
        # Regular expression to capture valid Git commit hashes (7 to 40 hexadecimal characters)
        commit_hash_regex = r'\b[0-9a-f]{7,40}\b'

        for pr in self.prs:
            if pr.strip():
                # Use regex to extract the commit hash (7 to 40 hexadecimal characters)
                match = re.match(commit_hash_regex, pr)
                if match:
                    commit_hash = match.group(0)  # Get the matched commit hash
                    message = pr[len(commit_hash):].strip()  # Extract the rest as the message

                    # Store the PR with commit hash and message
                    pr_item = QListWidgetItem(f"\n PR: {commit_hash} \n {message}\n{'_' * 75}")
                    pr_item.setData(Qt.UserRole, commit_hash)  # Store the commit hash in the item
                    self.pr_list.addItem(pr_item)

    def searchPRs(self):
        """ Filter PRs based on search input. """
        query = self.search_input.text().lower()
        filtered_prs = [pr for pr in self.prs if query in pr.lower()]
        self.pr_list.clear()
        commit_hash_regex = r'\b[0-9a-f]{7,40}\b'

        for pr in filtered_prs:
            if pr.strip():
                # Use regex to extract the commit hash (7 to 40 hexadecimal characters)
                match = re.match(commit_hash_regex, pr)
                if match:
                    commit_hash = match.group(0)  # Get the matched commit hash
                    message = pr[len(commit_hash):].strip()  # Extract the rest as the message

                    # Store the PR with commit hash and message
                    pr_item = QListWidgetItem(f"PR: {commit_hash} - {message}\n{'-' * 40}")
                    pr_item.setData(Qt.UserRole, commit_hash)  # Store the commit hash in the item
                    self.pr_list.addItem(pr_item)

    def onPRClick(self, item):
        """ When a PR is clicked, insert the commit hash into the commit input box. """
        commit_hash = item.data(Qt.UserRole)  # Retrieve the stored commit hash
        self.commit_input.setText(commit_hash)

    def openFile(self, file_path):
        if platform.system() == "Darwin":
            subprocess.run(['open', file_path])
        elif platform.system() == "Windows":
            os.startfile(file_path)
        else:
            subprocess.run(['xdg-open', file_path])


if __name__ == '__main__':
    app = QApplication([])
    extractor = GitDiffExtractor()
    extractor.show()
    app.exec_()
