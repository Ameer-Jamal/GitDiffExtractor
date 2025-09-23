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
)


class SettingsTab(QWidget):
    """Central location for provider selection and credential configuration."""

    settingsUpdated = pyqtSignal()
    providerChanged = pyqtSignal(str)

    def __init__(self, config_manager):
        super().__init__()
        self.config = config_manager

        self.bitbucket_radio = None
        self.github_radio = None
        self.bitbucket_group = None
        self.github_group = None

        self.bb_user_input = None
        self.bb_password_input = None
        self.bb_workspace_input = None
        self.bb_slug_input = None

        self.github_owner_input = None
        self.github_repo_input = None
        self.github_token_input = None

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

        self.bb_slug_input = QLineEdit(self)
        self.bb_slug_input.editingFinished.connect(self._store_bitbucket_slug)
        bb_form.addRow(QLabel("Repo Slug:"), self.bb_slug_input)

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
        self.github_owner_input.editingFinished.connect(self._store_github_owner)
        gh_form.addRow(QLabel("Owner:"), self.github_owner_input)

        self.github_repo_input = QLineEdit(self)
        self.github_repo_input.editingFinished.connect(self._store_github_repo)
        gh_form.addRow(QLabel("Repository:"), self.github_repo_input)

        self.github_token_input = QLineEdit(self)
        self.github_token_input.setEchoMode(QLineEdit.Password)
        self.github_token_input.editingFinished.connect(self._store_github_token)
        gh_form.addRow(QLabel("Token (optional):"), self.github_token_input)

        layout.addWidget(self.github_group)
        layout.addStretch()

    # ------------------------------------------------------------------
    # Configuration helpers
    def apply_repo_config(self):
        provider = self.config.get_provider()
        self._set_provider(provider)

        self._set_line_edit(self.bb_user_input, self.config.get_bitbucket_username())
        self._set_line_edit(self.bb_password_input, self.config.get_bitbucket_app_password())
        self._set_line_edit(self.bb_workspace_input, self.config.get_bitbucket_workspace())
        self._set_line_edit(self.bb_slug_input, self.config.get_repo_slug())

        self._set_line_edit(self.github_owner_input, self.config.get_github_owner())
        self._set_line_edit(self.github_repo_input, self.config.get_github_repo())
        self._set_line_edit(self.github_token_input, self.config.get_github_token())

        self._update_visibility()

    @staticmethod
    def _set_line_edit(line_edit, value):
        if line_edit is None:
            return
        block = line_edit.blockSignals(True)
        line_edit.setText(value or "")
        line_edit.blockSignals(block)

    def _set_provider(self, provider):
        provider = (provider or 'bitbucket').lower()
        block_bb = self.bitbucket_radio.blockSignals(True)
        block_gh = self.github_radio.blockSignals(True)
        if provider == 'github':
            self.github_radio.setChecked(True)
        else:
            self.bitbucket_radio.setChecked(True)
        self.bitbucket_radio.blockSignals(block_bb)
        self.github_radio.blockSignals(block_gh)
        self._update_visibility()

    def _update_visibility(self):
        provider = 'bitbucket' if self.bitbucket_radio.isChecked() else 'github'
        if self.bitbucket_group:
            self.bitbucket_group.setVisible(provider == 'bitbucket')
        if self.github_group:
            self.github_group.setVisible(provider == 'github')

    # ------------------------------------------------------------------
    # Store handlers
    def _on_provider_toggled(self, checked):
        if not checked:
            return
        provider = 'bitbucket' if self.bitbucket_radio.isChecked() else 'github'
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

    def _store_bitbucket_slug(self):
        self.config.set_repo_slug(self.bb_slug_input.text().strip())
        self.settingsUpdated.emit()

    def _store_github_owner(self):
        self.config.set_github_owner(self.github_owner_input.text().strip())
        self.settingsUpdated.emit()

    def _store_github_repo(self):
        self.config.set_github_repo(self.github_repo_input.text().strip())
        self.settingsUpdated.emit()

    def _store_github_token(self):
        self.config.set_github_token(self.github_token_input.text().strip())
        self.settingsUpdated.emit()

    # ------------------------------------------------------------------
    # Focus helpers
    def focus_bitbucket_credentials(self):
        if self.bb_user_input:
            self.bb_user_input.setFocus()
            self.bb_user_input.selectAll()

    def focus_bitbucket_slug(self):
        if self.bb_slug_input:
            self.bb_slug_input.setFocus()
            self.bb_slug_input.selectAll()

    def focus_github_owner(self):
        if self.github_owner_input:
            self.github_owner_input.setFocus()
            self.github_owner_input.selectAll()

    def focus_github_repo(self):
        if self.github_repo_input:
            self.github_repo_input.setFocus()
            self.github_repo_input.selectAll()
