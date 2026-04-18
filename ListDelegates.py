from PyQt5.QtCore import Qt, QRect, QSize
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import QStyledItemDelegate, QStyle


UI_ROLE = Qt.UserRole + 2


class PRListDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option, index):
        data = index.data(UI_ROLE) or {}
        header = data.get("header", "")
        repo_label = data.get("repo_label", "")
        branch_line = data.get("branch_line", "")
        title = data.get("title", "")
        author = data.get("author", "")

        painter.save()
        rect = option.rect.adjusted(6, 4, -6, -4)

        bg = QColor("#2a2d33")
        border = QColor("#4a4f57")
        text = QColor("#e8ecf1")
        muted = QColor("#aeb7c2")
        chip_bg = QColor("#3a475a")
        chip_border = QColor("#6a7d96")

        if option.state & QStyle.State_Selected:
            bg = QColor("#2e5fba")
            border = QColor("#4f86e6")
            chip_bg = QColor("#3567be")
            chip_border = QColor("#75a2f2")

        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(border, 1))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 8, 8)

        x = rect.left() + 10
        y = rect.top() + 8
        width = rect.width() - 20

        header_font = QFont(option.font)
        header_font.setBold(True)
        header_font.setPointSize(max(10, option.font.pointSize() + 1))
        painter.setFont(header_font)
        painter.setPen(text)
        painter.drawText(QRect(x, y, width, 20), Qt.AlignLeft | Qt.AlignVCenter, header)
        y += 24

        chip_text = repo_label or "unknown/repo"
        chip_font = QFont(option.font)
        chip_font.setBold(True)
        painter.setFont(chip_font)
        chip_w = min(width, max(90, painter.fontMetrics().horizontalAdvance(chip_text) + 14))
        chip_rect = QRect(x, y, chip_w, 18)
        painter.setPen(QPen(chip_border, 1))
        painter.setBrush(chip_bg)
        painter.drawRoundedRect(chip_rect, 7, 7)
        painter.setPen(text)
        painter.drawText(chip_rect.adjusted(6, 0, -6, 0), Qt.AlignLeft | Qt.AlignVCenter, chip_text)
        y += 22

        body_font = QFont(option.font)
        painter.setFont(body_font)
        painter.setPen(muted)
        painter.drawText(QRect(x, y, width, 18), Qt.AlignLeft | Qt.AlignVCenter, branch_line)
        y += 20

        painter.setPen(text)
        painter.drawText(QRect(x, y, width, 18), Qt.AlignLeft | Qt.AlignVCenter, f"Title: {title}")
        y += 20

        painter.setPen(muted)
        painter.drawText(QRect(x, y, width, 18), Qt.AlignLeft | Qt.AlignVCenter, f"Author: {author}")

        painter.restore()

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 106)


class BranchListDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option, index):
        data = index.data(UI_ROLE) or {}
        repo_label = data.get("repo_label", "")
        branch_name = data.get("branch", "")

        painter.save()
        rect = option.rect.adjusted(6, 3, -6, -3)

        bg = QColor("#2a2d33")
        border = QColor("#4a4f57")
        text = QColor("#e8ecf1")
        chip_bg = QColor("#3a475a")
        chip_border = QColor("#6a7d96")

        if option.state & QStyle.State_Selected:
            bg = QColor("#2e5fba")
            border = QColor("#4f86e6")
            chip_bg = QColor("#3567be")
            chip_border = QColor("#75a2f2")

        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(border, 1))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 7, 7)

        x = rect.left() + 10
        y = rect.top() + 7
        width = rect.width() - 20

        chip_font = QFont(option.font)
        chip_font.setBold(True)
        painter.setFont(chip_font)
        chip_text = repo_label or "unknown/repo"
        chip_w = min(width, max(90, painter.fontMetrics().horizontalAdvance(chip_text) + 14))
        chip_rect = QRect(x, y, chip_w, 18)
        painter.setPen(QPen(chip_border, 1))
        painter.setBrush(chip_bg)
        painter.drawRoundedRect(chip_rect, 7, 7)
        painter.setPen(text)
        painter.drawText(chip_rect.adjusted(6, 0, -6, 0), Qt.AlignLeft | Qt.AlignVCenter, chip_text)

        y += 22
        painter.setFont(option.font)
        painter.setPen(text)
        painter.drawText(QRect(x, y, width, 18), Qt.AlignLeft | Qt.AlignVCenter, branch_name)

        painter.restore()

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 54)
