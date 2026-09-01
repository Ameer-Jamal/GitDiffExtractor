from __future__ import annotations

import os
import time
from datetime import date, timedelta
from typing import Optional

from PyQt5.QtCore import QDate, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)
from PyQt5.QtCore import QUrl

from ConfigManager import ConfigManager
from ui.TaskRunner import TaskRunner
from services.contribution_exporter import ContributionExportService
from services.contribution_history_service import CancelToken, ContributionHistoryService
from models.contribution_models import ContributionHistoryQuery, ContributionHistoryResult, ContributionRecord, RepositoryRef
from services.provider_api import build_provider_client
from services.scope_manager import ScopeManager


class CheckableComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.view().pressed.connect(self.handle_item_pressed)
        self._changed = False

    def handle_item_pressed(self, index):
        item = self.model().itemFromIndex(index)
        if item.checkState() == Qt.Checked:
            item.setCheckState(Qt.Unchecked)
        else:
            item.setCheckState(Qt.Checked)
        self._changed = True

    def hidePopup(self):
        if self._changed:
            self._changed = False
            return
        super().hidePopup()

    def checked_items(self):
        checked = []
        for i in range(self.count()):
            item = self.model().item(i)
            if item.checkState() == Qt.Checked:
                checked.append(item.data(Qt.UserRole))
        return checked

    def set_checked_items(self, keys):
        keys_set = set(keys)
        for i in range(self.count()):
            item = self.model().item(i)
            repo = item.data(Qt.UserRole)
            if repo and repo.key in keys_set:
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)
        self.update_display_text()

    def update_display_text(self):
        checked = self.checked_items()
        if not checked:
            self.setEditText("Select repositories...")
        elif len(checked) == 1:
            self.setEditText(checked[0].display_name)
        else:
            self.setEditText(f"{len(checked)} repositories selected")


class ContributionDetailDialog(QDialog):
    def __init__(self, record: ContributionRecord, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Contribution Details")
        self.resize(700, 420)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("Repository:", QLabel(record.repository_display))
        form.addRow("Type:", QLabel(record.record_type.upper()))
        form.addRow("Author:", QLabel(record.author or ""))
        form.addRow("Date:", QLabel((record.effective_date or record.created_at).isoformat() if (record.effective_date or record.created_at) else ""))
        if record.record_type == "pr":
            form.addRow("PR ID:", QLabel(record.pr_id))
            form.addRow("Source branch:", QLabel(record.source_branch))
            form.addRow("Destination branch:", QLabel(record.destination_branch))
            form.addRow("State:", QLabel(record.state))
        else:
            form.addRow("Commit:", QLabel(record.commit_hash))
            form.addRow("Branch:", QLabel(record.branch))
        if record.ticket_id:
            form.addRow("Ticket:", QLabel(record.ticket_id))
        if record.labels:
            form.addRow("Labels:", QLabel(", ".join(record.labels)))
        layout.addLayout(form)

        text_browser = QTextBrowser(self)
        details = record.primary_text
        if record.record_type == "pr" and record.description:
            details = f"{details}\n\n{record.description}"
        text_browser.setPlainText(details)
        layout.addWidget(text_browser)

        button_row = QHBoxLayout()
        button_row.addStretch()
        if record.link:
            open_button = QPushButton("Open Link")
            open_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(record.link)))
            button_row.addWidget(open_button)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)


class ContributionHistoryTab(QWidget):
    progressUpdated = pyqtSignal(str)
    COLUMN_KEYS = [
        "date",
        "repository",
        "type",
        "text",
        "description",
        "ticket",
        "author",
        "state",
        "source",
        "destination",
        "branch",
        "identifier",
        "link",
    ]
    COLUMN_LABELS = [
        "Date",
        "Repository",
        "Type",
        "Title / Message",
        "PR Description",
        "Ticket",
        "Author",
        "State",
        "Source",
        "Destination",
        "Branch",
        "ID / Commit",
        "Link",
    ]

    def __init__(self, config: ConfigManager, task_runner: Optional[TaskRunner] = None):
        super().__init__()
        self.config = config
        self.task_runner = task_runner or TaskRunner(self)
        self.export_service = ContributionExportService()
        self.provider = build_provider_client(config)
        self.scope_manager = ScopeManager(config, self.provider)
        self.history_service = ContributionHistoryService(self.provider, self.scope_manager)
        self.cancel_token: Optional[CancelToken] = None
        self.current_result: Optional[ContributionHistoryResult] = None
        self.current_accessible_repositories: list[RepositoryRef] = []
        self._defaults_initialized = False
        self._query_started_at = 0.0
        self._busy_status_prefix = "Running…"
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_elapsed_status)
        self.progressUpdated.connect(self._on_progress_update)
        self._developer_suggestions_loading = False
        self._default_developer = ""

        self._build_ui()
        self.apply_provider_context()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        filter_group = QGroupBox("Contribution Query")
        filter_layout = QGridLayout(filter_group)

        self.developer_combo = QComboBox(self)
        self.developer_combo.setEditable(True)
        self.developer_combo.setInsertPolicy(QComboBox.NoInsert)
        self.developer_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        if self.developer_combo.lineEdit():
            self.developer_combo.lineEdit().setPlaceholderText("Username, display name, or email")
        self.add_developer_button = QPushButton("Add")
        self.add_developer_button.clicked.connect(self._add_current_developer)
        self.remove_developer_button = QPushButton("Remove")
        self.remove_developer_button.clicked.connect(self._remove_selected_developers)
        self.clear_developers_button = QPushButton("Clear")
        self.clear_developers_button.clicked.connect(self._clear_selected_developers)
        self.selected_developers_list = QListWidget(self)
        self.selected_developers_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.selected_developers_list.setMaximumHeight(70)
        self.selected_developers_list.setToolTip("Selected developers are matched as OR filters.")

        developer_container = QWidget(self)
        developer_layout = QVBoxLayout(developer_container)
        developer_layout.setContentsMargins(0, 0, 0, 0)
        developer_layout.setSpacing(4)
        developer_layout.addWidget(self.developer_combo)
        developer_buttons = QHBoxLayout()
        developer_buttons.addWidget(self.add_developer_button)
        developer_buttons.addWidget(self.remove_developer_button)
        developer_buttons.addWidget(self.clear_developers_button)
        developer_buttons.addStretch()
        developer_layout.addLayout(developer_buttons)
        developer_layout.addWidget(self.selected_developers_list)
        filter_layout.addWidget(QLabel("Developer"), 0, 0)
        filter_layout.addWidget(developer_container, 0, 1)

        self.preset_combo = QComboBox(self)
        self.preset_combo.addItem("Last 30 days", "30d")
        self.preset_combo.addItem("Last 90 days", "90d")
        self.preset_combo.addItem("Last 6 months", "6m")
        self.preset_combo.addItem("Last 12 months", "12m")
        self.preset_combo.addItem("Year to date", "ytd")
        self.preset_combo.addItem("All time", "all")
        self.preset_combo.addItem("Custom", "custom")
        self.preset_combo.currentIndexChanged.connect(self._apply_date_preset)
        filter_layout.addWidget(QLabel("Date range"), 0, 2)
        filter_layout.addWidget(self.preset_combo, 0, 3)

        self.start_date_edit = QDateEdit(self)
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.end_date_edit = QDateEdit(self)
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.start_label = QLabel("Start")
        self.end_label = QLabel("End")
        filter_layout.addWidget(self.start_label, 1, 0)
        filter_layout.addWidget(self.start_date_edit, 1, 1)
        filter_layout.addWidget(self.end_label, 1, 2)
        filter_layout.addWidget(self.end_date_edit, 1, 3)

        self.scope_combo = QComboBox(self)
        self.scope_combo.addItem("Contributed repos (fast, PR-discovered)", "contributed_repos")
        self.scope_combo.addItem("Selected repos (Settings)", "selected_repos")
        self.scope_combo.addItem("Custom repo selection", "custom_repos")
        self.scope_combo.addItem("All repos", "all_repos")
        self.scope_combo.currentIndexChanged.connect(self._refresh_developer_suggestions)
        self.scope_combo.currentIndexChanged.connect(self._on_scope_mode_changed)
        filter_layout.addWidget(QLabel("Scope"), 2, 0)
        filter_layout.addWidget(self.scope_combo, 2, 1)

        self.custom_repo_combo = CheckableComboBox(self)
        self.custom_repo_combo.setEditable(True)
        self.custom_repo_combo.lineEdit().setReadOnly(True)
        self.custom_repo_combo.setVisible(False)
        self.custom_repo_combo.view().pressed.connect(lambda: QTimer.singleShot(0, self._on_custom_repo_changed))
        filter_layout.addWidget(self.custom_repo_combo, 2, 2, 1, 2)

        self.contribution_type_combo = QComboBox(self)
        self.contribution_type_combo.addItem("Merged PRs only", "merged_prs")
        self.contribution_type_combo.addItem("Commits only", "commits")
        self.contribution_type_combo.addItem("Merged PRs + standalone commits", "prs_and_commits")
        filter_layout.addWidget(QLabel("Contribution type"), 3, 0)
        filter_layout.addWidget(self.contribution_type_combo, 3, 1)

        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("Search titles, commit messages, or ticket keyword")
        self.search_input.textChanged.connect(self._rerender_current_result)
        filter_layout.addWidget(QLabel("Search"), 3, 2)
        filter_layout.addWidget(self.search_input, 3, 3)

        self.advanced_toggle_button = QPushButton("Show Advanced Filters")
        self.advanced_toggle_button.setCheckable(True)
        self.advanced_toggle_button.toggled.connect(self._toggle_advanced_filters)
        filter_layout.addWidget(self.advanced_toggle_button, 4, 0, 1, 4)
        self.query_hint_label = QLabel(
            "Tip: Use scope + contribution type first, then add branch/search filters only if needed."
        )
        self.query_hint_label.setWordWrap(True)
        filter_layout.addWidget(self.query_hint_label, 5, 0, 1, 4)

        self.branch_filter_label = QLabel("Branch filter")
        self.branch_filter_input = QLineEdit(self)
        self.branch_filter_input.setPlaceholderText("Optional branch name (source or destination)")
        filter_layout.addWidget(self.branch_filter_label, 6, 0)
        filter_layout.addWidget(self.branch_filter_input, 6, 1)

        self.group_by_label = QLabel("Group by")
        self.group_by_combo = QComboBox(self)
        self.group_by_combo.addItem("None", "none")
        self.group_by_combo.addItem("Repository", "repository")
        self.group_by_combo.addItem("Month", "month")
        self.group_by_combo.addItem("Quarter", "quarter")
        self.group_by_combo.addItem("Year", "year")
        self.group_by_combo.addItem("Contribution type", "type")
        self.group_by_combo.addItem("Ticket ID", "ticket")
        self.group_by_combo.currentIndexChanged.connect(self._rerender_current_result)
        filter_layout.addWidget(self.group_by_label, 6, 2)
        filter_layout.addWidget(self.group_by_combo, 6, 3)

        toggle_row = QHBoxLayout()
        self.exclude_bots_checkbox = QCheckBox("Exclude bots/system users")
        self.exclude_bots_checkbox.setChecked(True)
        toggle_row.addWidget(self.exclude_bots_checkbox)
        self.titles_only_checkbox = QCheckBox("Titles/messages only")
        self.titles_only_checkbox.toggled.connect(self._apply_titles_only_visibility)
        toggle_row.addWidget(self.titles_only_checkbox)
        self.view_mode_combo = QComboBox(self)
        self.view_mode_combo.addItem("Summary", "summary")
        self.view_mode_combo.addItem("Titles/messages only", "titles")
        self.view_mode_combo.addItem("Detailed", "detailed")
        self.view_mode_combo.currentIndexChanged.connect(self._on_view_mode_changed)
        toggle_row.addWidget(self.view_mode_combo)
        toggle_row.addStretch()
        filter_layout.addLayout(toggle_row, 7, 0, 1, 4)

        action_row = QHBoxLayout()
        self.run_button = QPushButton("Run Query")
        self.run_button.setStyleSheet(
            "QPushButton {"
            "background-color: #0b63ce;"
            "color: white;"
            "font-weight: 700;"
            "border: 1px solid #084b9e;"
            "border-radius: 6px;"
            "padding: 6px 12px;"
            "}"
            "QPushButton:hover {"
            "background-color: #0958b8;"
            "}"
            "QPushButton:pressed {"
            "background-color: #074894;"
            "}"
            "QPushButton:disabled {"
            "background-color: #7aa8df;"
            "color: #f3f7ff;"
            "}"
        )
        self.run_button.clicked.connect(self.run_query)
        action_row.addWidget(self.run_button)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_query)
        self.cancel_button.setEnabled(False)
        action_row.addWidget(self.cancel_button)
        action_row.addStretch()
        filter_layout.addLayout(action_row, 8, 0, 1, 4)

        root.addWidget(filter_group)

        summary_group = QGroupBox("Summary")
        summary_layout = QGridLayout(summary_group)
        self.total_prs_label = QLabel("0")
        self.total_commits_label = QLabel("0")
        self.repo_count_label = QLabel("0")
        self.fully_scanned_label = QLabel("0/0")
        self.range_label = QLabel("Not run")
        self.top_repos_label = QLabel("—")
        self.ticket_prefix_label = QLabel("—")
        summary_layout.addWidget(QLabel("Merged PRs"), 0, 0)
        summary_layout.addWidget(self.total_prs_label, 0, 1)
        summary_layout.addWidget(QLabel("Standalone commits"), 0, 2)
        summary_layout.addWidget(self.total_commits_label, 0, 3)
        summary_layout.addWidget(QLabel("Repositories"), 1, 0)
        summary_layout.addWidget(self.repo_count_label, 1, 1)
        summary_layout.addWidget(QLabel("Fully scanned"), 1, 2)
        summary_layout.addWidget(self.fully_scanned_label, 1, 3)
        summary_layout.addWidget(QLabel("Active date range"), 2, 0)
        summary_layout.addWidget(self.range_label, 2, 1, 1, 3)
        summary_layout.addWidget(QLabel("Most active repositories"), 3, 0)
        summary_layout.addWidget(self.top_repos_label, 3, 1, 1, 3)
        summary_layout.addWidget(QLabel("Common ticket prefixes"), 4, 0)
        summary_layout.addWidget(self.ticket_prefix_label, 4, 1, 1, 3)
        root.addWidget(summary_group)

        # Status and local table controls
        status_row = QHBoxLayout()
        self.status_label = QLabel("Status: Ready. Configure filters and click 'Run Query'.")
        status_row.addWidget(self.status_label)
        status_row.addStretch()
        root.addLayout(status_row)

        table_controls = QHBoxLayout()
        table_controls.addWidget(QLabel("Filter Results by Repository:"))
        self.repo_filter_combo = QComboBox(self)
        self.repo_filter_combo.addItem("All repositories", "")
        self.repo_filter_combo.currentIndexChanged.connect(self._rerender_current_result)
        table_controls.addWidget(self.repo_filter_combo)
        table_controls.addStretch()
        root.addLayout(table_controls)

        # Export Settings Group
        export_group = QGroupBox("Export Settings")
        export_layout = QHBoxLayout(export_group)
        export_layout.setContentsMargins(10, 10, 10, 10)
        
        export_layout.addWidget(QLabel("Export Format:"))
        self.export_format_combo = QComboBox(self)
        self.export_format_combo.addItem("CSV", "csv")
        self.export_format_combo.addItem("Markdown", "md")
        self.export_format_combo.addItem("JSON", "json")
        self.export_format_combo.setToolTip("Choose file format for export.")
        export_layout.addWidget(self.export_format_combo)
        
        export_layout.addSpacing(10)
        export_layout.addWidget(QLabel("Content Mode:"))
        self.export_mode_combo = QComboBox(self)
        self.export_mode_combo.addItem("Raw records", "raw")
        self.export_mode_combo.addItem("Titles/messages only", "titles")
        self.export_mode_combo.addItem("Grouped summary", "grouped")
        self.export_mode_combo.setToolTip("Choose whether export contains full details or a compact view.")
        export_layout.addWidget(self.export_mode_combo)
        
        export_layout.addStretch()
        self.export_button = QPushButton("Export Results")
        self.export_button.clicked.connect(self.export_results)
        export_layout.addWidget(self.export_button)
        
        root.addWidget(export_group)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        root.addWidget(self.progress_bar)

        self.results_table = QTableWidget(self)
        self.results_table.setColumnCount(len(self.COLUMN_LABELS))
        self.results_table.setHorizontalHeaderLabels(self.COLUMN_LABELS)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results_table.cellDoubleClicked.connect(self._show_detail_for_row)
        header = self.results_table.horizontalHeader()
        header.setStretchLastSection(True)
        self.results_table.setAlternatingRowColors(True)
        root.addWidget(self.results_table, 1)
        self._toggle_advanced_filters(False)
        self._on_scope_mode_changed()

    def apply_provider_context(self):
        self.provider = build_provider_client(self.config)
        self.scope_manager = ScopeManager(self.config, self.provider)
        self.history_service = ContributionHistoryService(self.provider, self.scope_manager)
        smart_index = self.scope_combo.findData("contributed_repos")
        if smart_index >= 0:
            item = self.scope_combo.model().item(smart_index)
            is_bitbucket = (self.provider.provider_name or "").lower() == "bitbucket"
            item.setEnabled(is_bitbucket)
            item.setToolTip(
                "Uses Bitbucket's workspace pull-request API to find repositories the developer authored PRs in."
                if is_bitbucket
                else "Fast contributed-repository discovery is currently available for Bitbucket only."
            )
            if not is_bitbucket and self.scope_combo.currentData() == "contributed_repos":
                self.scope_combo.setCurrentIndex(self.scope_combo.findData("selected_repos"))
        self.current_result = None
        self.current_accessible_repositories = []
        if not self._defaults_initialized:
            self._set_default_dates()
            self._restore_persisted_state()
            self._defaults_initialized = True
        self._load_default_developer()
        self._load_scope_repositories(force_refresh=False, silent=True)

    def run_query(self):
        self._save_persisted_state()
        query = self._build_query()
        if query.scope_type == "custom_repos" and not (query.scope_repositories or ()):
            QMessageBox.warning(
                self,
                "Custom Scope Empty",
                "No custom repository selected.\nPlease select a repository from the dropdown.",
            )
            return
        self.cancel_token = CancelToken()
        self._set_busy(
            True,
            "Running contribution query. Large scopes may take longer; you can cancel anytime.",
        )
        self.status_label.setText("Starting query…")

        def task():
            return self.history_service.execute_query(
                query,
                progress_callback=self.progressUpdated.emit,
                cancel_token=self.cancel_token,
            )

        def on_result(result: ContributionHistoryResult):
            self.current_result = result
            self._render_result(result)
            if result.partial_errors:
                QMessageBox.warning(
                    self,
                    "Partial Results",
                    "Some repositories failed while scanning:\n\n" + "\n".join(result.partial_errors[:10]),
                )
            elif not result.records:
                scope_label = result.scope.label
                developer = query.developer or "(any developer)"
                date_label = (
                    f"{query.start_date.isoformat()} -> {query.end_date.isoformat()}"
                    if query.start_date and query.end_date
                    else "all time"
                )
                QMessageBox.information(
                    self,
                    "No Contributions",
                    "No contributions matched the current filters.\n\n"
                    f"Developer: {developer}\n"
                    f"Scope: {scope_label}\n"
                    f"Type: {query.contribution_type}\n"
                    f"Date: {date_label}\n"
                    f"Branch filter: {(query.branch_filter or '(none)')}\n"
                    f"Search: {(query.search_text or '(none)')}",
                )

        def on_error(exc: Exception):
            QMessageBox.critical(self, "Contribution History", str(exc))

        self.task_runner.run(
            task,
            description="Contribution History Query",
            on_result=on_result,
            on_error=on_error,
            on_finished=lambda: self._set_busy(False, "Ready"),
        )

    def cancel_query(self):
        if self.cancel_token:
            self.cancel_token.cancel()
            self.status_label.setText("Cancellation requested. Finishing current provider request…")
            self.cancel_button.setEnabled(False)

    def export_results(self):
        if not self.current_result or not self.current_result.records:
            QMessageBox.information(self, "Export", "Run a query before exporting results.")
            return

        selected_records = self._selected_records()
        records = selected_records or self.current_result.records
        export_format = self.export_format_combo.currentData()
        export_mode = self.export_mode_combo.currentData()

        if export_format == "csv":
            content = self.export_service.export_csv(records, titles_only=(export_mode == "titles"))
            suffix = "csv"
        elif export_format == "json":
            content = self.export_service.export_json(records)
            suffix = "json"
        else:
            content = self.export_service.export_markdown(
                self.current_result,
                records,
                titles_only=(export_mode == "titles"),
                grouped_summary=(export_mode == "grouped"),
            )
            suffix = "md"

        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export Contribution History",
            os.path.join(self.config.get_output_dir() or "", f"contribution_history.{suffix}"),
            f"*.{suffix}",
        )
        if not filename:
            return

        with open(filename, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)

        mode_label = self.export_mode_combo.currentText()
        format_label = self.export_format_combo.currentText()
        QMessageBox.information(
            self,
            "Export Complete",
            f"Saved {mode_label} as {format_label}:\n{filename}",
        )

    def _build_query(self) -> ContributionHistoryQuery:
        start_date = self.start_date_edit.date().toPyDate()
        end_date = self.end_date_edit.date().toPyDate()
        preset = self.preset_combo.currentData()
        if preset == "all":
            start_date = None
            end_date = None
        developers = self._selected_developers()
        current_value = self.developer_combo.currentText().strip()
        if current_value and not any(current_value.lower() == item.lower() for item in developers):
            developers.append(current_value)
        scope_type = self.scope_combo.currentData()
        scope_repositories = None
        scope_label_override = ""
        if scope_type == "custom_repos":
            selected_repos = self.custom_repo_combo.checked_items()
            if selected_repos:
                scope_repositories = tuple(selected_repos)
                scope_label_override = f"Custom ({len(scope_repositories)} repos)"
            else:
                scope_repositories = ()
                scope_label_override = "Custom: No repository selected"
        return ContributionHistoryQuery(
            developer=", ".join(developers),
            start_date=start_date,
            end_date=end_date,
            scope_type=scope_type,
            contribution_type=self.contribution_type_combo.currentData(),
            search_text=self.search_input.text().strip(),
            branch_filter=self.branch_filter_input.text().strip(),
            exclude_bots=self.exclude_bots_checkbox.isChecked(),
            group_by=self.group_by_combo.currentData(),
            titles_only=self.titles_only_checkbox.isChecked() or self.view_mode_combo.currentData() == "titles",
            scope_repositories=scope_repositories,
            scope_label_override=scope_label_override,
        )

    def _render_result(self, result: ContributionHistoryResult):
        self.total_prs_label.setText(str(result.total_prs))
        self.total_commits_label.setText(str(result.total_commits))
        self.repo_count_label.setText(str(len(result.active_repositories)))
        total_scanned = len(result.repositories_scanned)
        failed_repos = set()
        for message in result.partial_errors:
            text = (message or "").strip()
            if ":" in text:
                failed_repos.add(text.split(":", 1)[0].strip())
        fully_scanned = max(0, total_scanned - len(failed_repos))
        self.fully_scanned_label.setText(f"{fully_scanned}/{total_scanned}")
        query = self._build_query()
        if query.start_date and query.end_date:
            self.range_label.setText(f"{query.start_date.isoformat()} to {query.end_date.isoformat()}")
        else:
            self.range_label.setText("All time")
        self.top_repos_label.setText(", ".join(result.top_repositories) or "—")
        self.ticket_prefix_label.setText(", ".join(result.ticket_prefixes) or "—")

        # Update repo filter combo
        current_repo_filter = self.repo_filter_combo.currentData()
        block = self.repo_filter_combo.blockSignals(True)
        self.repo_filter_combo.clear()
        self.repo_filter_combo.addItem("All repositories", "")
        for repo_name in sorted(result.active_repositories):
            self.repo_filter_combo.addItem(repo_name, repo_name)
        
        index = self.repo_filter_combo.findData(current_repo_filter)
        if index >= 0:
            self.repo_filter_combo.setCurrentIndex(index)
        else:
            self.repo_filter_combo.setCurrentIndex(0)
        self.repo_filter_combo.blockSignals(block)

        self._populate_results_table(result)

    def _populate_results_table(self, result: ContributionHistoryResult):
        groups = result.grouped_records if result.grouped_records else [("All results", result.records)]
        self.results_table.setRowCount(0)
        row = 0

        for label, records in groups:
            if self.group_by_combo.currentData() != "none":
                self.results_table.insertRow(row)
                header_item = QTableWidgetItem(label)
                header_item.setFlags(Qt.ItemIsEnabled)
                header_item.setData(Qt.UserRole, {"kind": "group"})
                self.results_table.setItem(row, 0, header_item)
                self.results_table.setSpan(row, 0, 1, len(self.COLUMN_LABELS))
                row += 1

            for record in records:
                self.results_table.insertRow(row)
                self._set_row_items(row, record)
                row += 1

        self.results_table.resizeColumnsToContents()
        self._apply_results_table_defaults()
        self._apply_titles_only_visibility()

    def _set_row_items(self, row: int, record: ContributionRecord):
        full_description = (record.description or "").strip().replace("\n", " ")
        description = self._preview_text(full_description, limit=140)
        values = [
            (record.effective_date or record.created_at).strftime("%Y-%m-%d") if (record.effective_date or record.created_at) else "",
            record.repository_display,
            record.record_type.upper(),
            record.primary_text,
            description,
            record.ticket_id,
            record.author,
            record.state,
            record.source_branch,
            record.destination_branch,
            record.branch,
            record.pr_id if record.record_type == "pr" else record.commit_hash[:12],
            record.link,
        ]
        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setData(Qt.UserRole, {"kind": "record", "record": record})
            if col == self.COLUMN_KEYS.index("link") and value:
                item.setForeground(Qt.cyan)
            if col == self.COLUMN_KEYS.index("description"):
                if full_description:
                    item.setToolTip(full_description)
                if description.endswith("Show more..."):
                    item.setToolTip(f"{full_description}\n\nDouble-click row to view full details.")
            self.results_table.setItem(row, col, item)

    @staticmethod
    def _preview_text(text: str, limit: int = 140) -> str:
        value = (text or "").strip()
        if not value:
            return ""
        if len(value) <= limit:
            return value
        trimmed = value[:limit].rstrip()
        return f"{trimmed}... Show more..."

    def _rerender_current_result(self):
        if not self.current_result:
            return
        
        records = self.current_result.records
        
        # Apply repo filter
        repo_filter = self.repo_filter_combo.currentData()
        if repo_filter:
            records = [r for r in records if r.repository_display == repo_filter]
        
        # Apply local search filter (if any, though query already does some)
        query = self.search_input.text().strip().lower()
        if query:
            records = [r for r in records if query in (r.primary_text or "").lower() or query in (r.description or "").lower() or query in (r.ticket_id or "").lower()]

        self.current_result.grouped_records = self.history_service._group_records(  # noqa: SLF001
            records,
            self.group_by_combo.currentData(),
        )
        self._populate_results_table(self.current_result)

    def _show_detail_for_row(self, row: int, _column: int):
        item = self.results_table.item(row, 0)
        if not item:
            return
        payload = item.data(Qt.UserRole) or {}
        if payload.get("kind") != "record":
            return
        dialog = ContributionDetailDialog(payload["record"], self)
        dialog.exec_()

    def _selected_records(self) -> list[ContributionRecord]:
        rows = {index.row() for index in self.results_table.selectionModel().selectedRows()}
        records: list[ContributionRecord] = []
        for row in sorted(rows):
            item = self.results_table.item(row, 0)
            if not item:
                continue
            payload = item.data(Qt.UserRole) or {}
            if payload.get("kind") == "record":
                records.append(payload["record"])
        return records

    def _set_busy(self, busy: bool, status: str):
        widgets = [
            self.run_button,
            self.export_button,
            self.custom_repo_combo,
            self.scope_combo,
            self.contribution_type_combo,
            self.search_input,
            self.branch_filter_input,
            self.group_by_combo,
            self.developer_combo,
            self.add_developer_button,
            self.remove_developer_button,
            self.clear_developers_button,
            self.selected_developers_list,
            self.preset_combo,
            self.start_date_edit,
            self.end_date_edit,
            self.exclude_bots_checkbox,
            self.titles_only_checkbox,
            self.view_mode_combo,
            self.repo_filter_combo,
            self.export_format_combo,
            self.export_mode_combo,
        ]
        for widget in widgets:
            widget.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.progress_bar.setVisible(busy)
        self.progress_bar.setRange(0, 0 if busy else 1)
        if busy:
            self._busy_status_prefix = status
            self._query_started_at = time.monotonic()
            self._elapsed_timer.start()
            self.status_label.setText(status)
        else:
            self._elapsed_timer.stop()
            self._query_started_at = 0.0
            self._started_dt = None
            self.cancel_token = None
            self.status_label.setText(status if status else "Ready")

    def _on_progress_update(self, text: str):
        text = (text or "").strip()
        if not text:
            return
        self._busy_status_prefix = text
        self.status_label.setText(text)

    def _update_elapsed_status(self):
        if not self.cancel_token:
            return
        if self._query_started_at <= 0:
            return
        seconds = int(max(0.0, time.monotonic() - self._query_started_at))
        self.status_label.setText(f"{self._busy_status_prefix} (elapsed {seconds}s)")

    def _load_default_developer(self):
        if self.developer_combo.currentText().strip():
            return

        def task():
            return self.history_service.build_default_developer()

        def on_result(value: str):
            value = (value or "").strip()
            if not value:
                return
            self._default_developer = value
            if not self.developer_combo.currentText().strip():
                self._set_developer_text(value)
            self._merge_developer_candidates([value])

        self.task_runner.run(
            task,
            description="Load Authenticated User",
            on_result=on_result,
            on_error=lambda _exc: None,
        )

    def _load_scope_repositories(self, force_refresh: bool = False, silent: bool = False):
        self._set_status_if_idle("Loading repository scope…")

        def task():
            return self.scope_manager.list_accessible_repositories(force_refresh=force_refresh)

        def on_result(repositories: list[RepositoryRef]):
            self.current_accessible_repositories = sorted(repositories, key=lambda r: r.display_name.lower())
            
            # Populate custom repo combo
            block = self.custom_repo_combo.blockSignals(True)
            self.custom_repo_combo.clear()
            model = self.custom_repo_combo.model()
            for i, repo in enumerate(self.current_accessible_repositories):
                self.custom_repo_combo.addItem(repo.display_name, repo)
                item = model.item(i)
                item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                item.setCheckState(Qt.Unchecked)
            self.custom_repo_combo.update_display_text()
            self.custom_repo_combo.blockSignals(block)

            self._set_status_if_idle(f"Repository scope ready ({len(repositories)} repos)")
            self._refresh_developer_suggestions()
            self._restore_custom_repo_selection()

        def on_error(exc: Exception):
            if not silent:
                QMessageBox.warning(self, "Repositories", str(exc))

        self.task_runner.run(
            task,
            description="Load Repositories",
            on_result=on_result,
            on_error=on_error,
        )

    def _set_default_dates(self):
        self.preset_combo.setCurrentIndex(self.preset_combo.findData("12m"))
        self._apply_date_preset()
        default_scope = (
            "contributed_repos"
            if (self.config.get_provider() or "bitbucket").lower() == "bitbucket"
            else "selected_repos"
        )
        self.scope_combo.setCurrentIndex(self.scope_combo.findData(default_scope))
        self.contribution_type_combo.setCurrentIndex(self.contribution_type_combo.findData("merged_prs"))

    def _apply_date_preset(self):
        today = date.today()
        preset = self.preset_combo.currentData()
        start = today - timedelta(days=365)
        end = today
        if preset == "30d":
            start = today - timedelta(days=30)
        elif preset == "90d":
            start = today - timedelta(days=90)
        elif preset == "6m":
            start = today - timedelta(days=183)
        elif preset == "12m":
            start = today - timedelta(days=365)
        elif preset == "ytd":
            start = date(today.year, 1, 1)
        elif preset == "all":
            start = date(2000, 1, 1)
        elif preset == "custom":
            self._set_custom_date_visibility(True)
            return
        self.start_date_edit.setDate(QDate(start.year, start.month, start.day))
        self.end_date_edit.setDate(QDate(end.year, end.month, end.day))
        self._set_custom_date_visibility(False)

    def _set_custom_date_visibility(self, visible: bool):
        self.start_label.setVisible(visible)
        self.start_date_edit.setVisible(visible)
        self.end_label.setVisible(visible)
        self.end_date_edit.setVisible(visible)

    def _toggle_advanced_filters(self, visible: bool):
        self.advanced_toggle_button.setText(
            "Hide Advanced Filters" if visible else "Show Advanced Filters"
        )
        for widget in (
            self.branch_filter_label,
            self.branch_filter_input,
            self.group_by_label,
            self.group_by_combo,
            self.exclude_bots_checkbox,
        ):
            widget.setVisible(visible)

    def _on_scope_mode_changed(self):
        scope_mode = self.scope_combo.currentData()
        self.custom_repo_combo.setVisible(scope_mode == "custom_repos")
        if scope_mode == "contributed_repos":
            self.query_hint_label.setText(
                "Fast scope: Bitbucket finds repositories from this developer's merged PRs first. "
                "Direct-commit-only repositories require All repos."
            )
        else:
            self.query_hint_label.setText(
                "Tip: Use scope + contribution type first, then add branch/search filters only if needed."
            )
        self._refresh_developer_suggestions()

    def _on_custom_repo_changed(self):
        self.custom_repo_combo.update_display_text()
        self._refresh_developer_suggestions()
        self._save_persisted_state()

    def _restore_custom_repo_selection(self):
        state = self.config.get_contribution_history_state()
        if state and "custom_repo_keys" in state:
            keys = state.get("custom_repo_keys", [])
            self.custom_repo_combo.set_checked_items(keys)

    def _set_developer_text(self, text: str):
        block = self.developer_combo.blockSignals(True)
        self.developer_combo.setEditText(text)
        self.developer_combo.blockSignals(block)

    def _selected_developers(self) -> list[str]:
        values = []
        seen = set()
        for index in range(self.selected_developers_list.count()):
            text = (self.selected_developers_list.item(index).text() or "").strip()
            key = text.lower()
            if not text or key in seen:
                continue
            seen.add(key)
            values.append(text)
        return values

    def _add_current_developer(self):
        text = (self.developer_combo.currentText() or "").strip()
        if not text:
            return
        if any(text.lower() == item.lower() for item in self._selected_developers()):
            return
        self.selected_developers_list.addItem(text)
        self._save_persisted_state()

    def _remove_selected_developers(self):
        for item in self.selected_developers_list.selectedItems():
            self.selected_developers_list.takeItem(self.selected_developers_list.row(item))
        self._save_persisted_state()

    def _clear_selected_developers(self):
        self.selected_developers_list.clear()
        self._save_persisted_state()

    def _known_developer_aliases(self) -> list[str]:
        aliases = []
        current = (self.developer_combo.currentText() or "").strip()
        if current:
            aliases.append(current)
        default_user = (self._default_developer or "").strip()
        if default_user:
            aliases.append(default_user)
        provider = (self.config.get_provider() or "bitbucket").lower()
        if provider == "bitbucket":
            aliases.append((self.config.get_bitbucket_username() or "").strip())
        else:
            aliases.append((self.config.get_github_owner() or "").strip())

        deduped = []
        seen = set()
        for alias in aliases:
            key = alias.lower()
            if not alias or key in seen:
                continue
            seen.add(key)
            deduped.append(alias)
        return deduped

    def _merge_developer_candidates(self, candidates: list[str]):
        current_text = (self.developer_combo.currentText() or "").strip()
        existing = []
        for index in range(self.developer_combo.count()):
            text = (self.developer_combo.itemText(index) or "").strip()
            if text:
                existing.append(text)

        merged = []
        seen = set()
        for value in [*self._known_developer_aliases(), *existing, *(candidates or [])]:
            text = (value or "").strip()
            key = text.lower()
            if not text or key in seen:
                continue
            seen.add(key)
            merged.append(text)

        merged.sort(key=lambda item: item.lower())
        self.developer_combo.clear()
        self.developer_combo.addItem("")
        for item in merged:
            self.developer_combo.addItem(item)

        if current_text:
            self._set_developer_text(current_text)
        elif merged:
            self._set_developer_text(merged[0])

    def _refresh_developer_suggestions(self):
        if self._developer_suggestions_loading:
            return
        self._developer_suggestions_loading = True
        current_text = self.developer_combo.currentText().strip()
        self._set_status_if_idle("Loading developer suggestions…")

        def task():
            scope_mode = self.scope_combo.currentData()
            if scope_mode == "custom_repos":
                repositories = self.custom_repo_combo.checked_items()
            elif scope_mode == "contributed_repos":
                repositories = self.scope_manager.get_selected_repositories()
                if not repositories:
                    repositories = self.current_accessible_repositories[:10]
            else:
                scope = self.scope_manager.resolve_scope(scope_mode)
                repositories = list(scope.repositories)

            if not repositories:
                return []
            if len(repositories) > 10:
                repositories = repositories[:10]
            seen: set[str] = set()
            candidates: list[str] = []
            for repository in repositories:
                for item in self.provider.list_developer_candidates(repository, limit=40):
                    candidate = (item or "").strip()
                    key = candidate.lower()
                    if not candidate or key in seen:
                        continue
                    seen.add(key)
                    candidates.append(candidate)
            return sorted(candidates, key=lambda value: value.lower())

        def on_result(candidates: list[str]):
            live_text = self.developer_combo.currentText().strip() or current_text
            if live_text:
                self._set_developer_text(live_text)
            self._merge_developer_candidates(candidates)
            self._set_status_if_idle(
                f"Developer suggestions ready ({len(candidates)} found)"
            )

        def on_error(_exc: Exception):
            live_text = self.developer_combo.currentText().strip() or current_text
            if live_text:
                self._set_developer_text(live_text)
            self._merge_developer_candidates([])
            self._set_status_if_idle("Developer suggestions unavailable")

        def on_finished():
            self._developer_suggestions_loading = False

        self.task_runner.run(
            task,
            description="Load Developer Suggestions",
            on_result=on_result,
            on_error=on_error,
            on_finished=on_finished,
        )

    def _apply_titles_only_visibility(self):
        mode = self.view_mode_combo.currentData()
        titles_only = self.titles_only_checkbox.isChecked() or mode == "titles"
        detailed = mode == "detailed"
        hidden = {
            "description": titles_only,
            "author": titles_only,
            "state": titles_only,
            "source": titles_only,
            "destination": titles_only,
            "branch": titles_only,
            "identifier": titles_only,
            "link": False,
        }
        if detailed:
            hidden = dict.fromkeys(hidden,False)

        for key, column in zip(self.COLUMN_KEYS, range(len(self.COLUMN_KEYS))):
            if key in {"date", "repository", "type", "text", "ticket"}:
                self.results_table.setColumnHidden(column, False)
            else:
                self.results_table.setColumnHidden(column, hidden.get(key, False))

    def _restore_persisted_state(self):
        state = self.config.get_contribution_history_state()
        if not state:
            return
        self._set_developer_text((state.get("developer_input") or "").strip())
        self.selected_developers_list.clear()
        for value in state.get("developers", []):
            text = (value or "").strip()
            if text:
                self.selected_developers_list.addItem(text)
        
        self._restore_custom_repo_selection()

        self._set_combo_data(self.preset_combo, state.get("preset", "12m"))
        self._set_combo_data(self.scope_combo, state.get("scope", "all_repos"))
        self._set_combo_data(self.contribution_type_combo, state.get("contribution_type", "merged_prs"))
        self._set_combo_data(self.group_by_combo, state.get("group_by", "none"))
        self._set_combo_data(self.view_mode_combo, state.get("view_mode", "summary"))

        self.search_input.setText(state.get("search_text", ""))
        self.branch_filter_input.setText(state.get("branch_filter", ""))
        self.exclude_bots_checkbox.setChecked(bool(state.get("exclude_bots", True)))
        self.titles_only_checkbox.setChecked(bool(state.get("titles_only", False)))
        self.advanced_toggle_button.setChecked(bool(state.get("advanced_visible", False)))

        start_text = (state.get("start_date") or "").strip()
        end_text = (state.get("end_date") or "").strip()
        start_date = QDate.fromString(start_text, "yyyy-MM-dd")
        end_date = QDate.fromString(end_text, "yyyy-MM-dd")
        if start_date.isValid():
            self.start_date_edit.setDate(start_date)
        if end_date.isValid():
            self.end_date_edit.setDate(end_date)
        self._apply_date_preset()

    def _save_persisted_state(self):
        checked_repos = self.custom_repo_combo.checked_items()
        state = {
            "developers": self._selected_developers(),
            "developer_input": self.developer_combo.currentText().strip(),
            "preset": self.preset_combo.currentData(),
            "scope": self.scope_combo.currentData(),
            "contribution_type": self.contribution_type_combo.currentData(),
            "search_text": self.search_input.text().strip(),
            "branch_filter": self.branch_filter_input.text().strip(),
            "group_by": self.group_by_combo.currentData(),
            "titles_only": self.titles_only_checkbox.isChecked(),
            "view_mode": self.view_mode_combo.currentData(),
            "exclude_bots": self.exclude_bots_checkbox.isChecked(),
            "advanced_visible": self.advanced_toggle_button.isChecked(),
            "start_date": self.start_date_edit.date().toString("yyyy-MM-dd"),
            "end_date": self.end_date_edit.date().toString("yyyy-MM-dd"),
            "custom_repo_keys": [repo.key for repo in checked_repos],
        }
        self.config.set_contribution_history_state(state)

    @staticmethod
    def _set_combo_data(combo: QComboBox, value):
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _on_view_mode_changed(self):
        mode = self.view_mode_combo.currentData()
        if mode == "titles":
            self.titles_only_checkbox.setChecked(True)
        elif self.titles_only_checkbox.isChecked():
            self.titles_only_checkbox.setChecked(False)
        self._apply_titles_only_visibility()

    def _set_status_if_idle(self, text: str):
        if self.progress_bar.isVisible():
            return
        self.status_label.setText(text)

    def _apply_results_table_defaults(self):
        default_widths = {
            "date": 110,
            "repository": 200,
            "type": 90,
            "text": 360,
            "ticket": 110,
            "description": 280,
        }
        for key, width in default_widths.items():
            if key in self.COLUMN_KEYS:
                self.results_table.setColumnWidth(self.COLUMN_KEYS.index(key), width)
