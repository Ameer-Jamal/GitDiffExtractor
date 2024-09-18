import os
import platform
import re
import shutil
import subprocess

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QLabel, QLineEdit,
                             QPushButton, QFileDialog, QMessageBox, QHBoxLayout, QListWidget,
                             QListWidgetItem, QTabWidget, QCheckBox, QRadioButton, QButtonGroup)

from BranchCommitViewer import BranchCommitViewer
from ConfigManager import ConfigManager

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
        if (self.repo_input.text and self.output_input.text):
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

        # Set the "Only Pull Requests" radio button as checked by default
        self.all_diffs_radio.setChecked(True)

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
            self.config_manager.set_repo_dir(directory)  # Save to config

    def browseOutput(self):
        directory = self.selectDirectory("Select Output Directory")
        if directory:
            self.output_input.setText(directory)
            self.config_manager.set_output_dir(directory)  # Save to config

    def selectDirectory(self, title):
        """ Open a standard directory selection dialog using QFileDialog. """
        return QFileDialog.getExistingDirectory(self, title)

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
                # Get the parent(s) of the commit
                result = subprocess.run(['git', 'rev-list', '--parents', '-n', '1', commit_hash],
                                        capture_output=True, text=True)
                parents = result.stdout.strip().split()

                if len(parents) == 1:
                    # This is an initial commit with no parents (rare but possible)
                    QMessageBox.warning(self, "Warning",
                                        f"The commit {commit_hash} has no parents (initial commit). Skipping.")
                    continue

                elif len(parents) == 2:
                    # Not a merge commit, use the single parent
                    parent1 = parents[1]
                    QMessageBox.warning(self, "Warning",
                                        f"The specified commit {commit_hash} is not a merge commit. Generating diff with its single parent.")
                    diff_file_path = os.path.join(output_dir, f'{commit_hash}_diff.txt')
                    with open(diff_file_path, 'w') as diff_file:
                        subprocess.run(['git', 'diff', parent1, commit_hash], stdout=diff_file)

                elif len(parents) >= 3:
                    # Merge commit with two parents
                    parent1 = parents[1]
                    parent2 = parents[2]
                    diff_file_path = os.path.join(output_dir, f'{commit_hash}_diff.txt')
                    with open(diff_file_path, 'w') as diff_file:
                        subprocess.run(['git', 'diff', parent1, parent2], stdout=diff_file)

                # Open the diff file after it's generated
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
            subprocess.run(['git', 'fetch', 'origin'], check=True)

            # Check which radio button is selected
            if self.only_pr_radio.isChecked():
                # Show only pull requests (case-insensitive grep for "pull request")
                result = subprocess.run(['git', 'log', '--merges', '--grep=pull request'], capture_output=True,
                                        text=True)
            elif self.only_merges_radio.isChecked():
                # Show only merge commits
                result = subprocess.run(['git', 'log', '--merges'], capture_output=True, text=True)

            elif self.all_diffs_radio.isChecked():
                result = subprocess.run(['git', 'log'], capture_output=True, text=True)

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
                match = re.search(commit_hash_regex, pr)
                if match:
                    commit_hash = match.group(0)  # Get the matched commit hash
                    # Extract the rest of the message starting after the matched commit hash
                    message = pr[match.end():].strip()

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

    @staticmethod
    def openFile(file_path):
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
