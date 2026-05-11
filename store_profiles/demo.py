# embedded_aldi_browser.py

import sys

from PyQt5.QtCore import QUrl
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
)
from PyQt5.QtWebEngineWidgets import (
    QWebEngineView,
)


class EmbeddedBrowser(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Embedded Aldi Browser")
        self.resize(1600, 1000)

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.browser = QWebEngineView()

        self.browser.load(
            QUrl(
                "https://www.aldi.us/store/aldi/storefront"
            )
        )

        layout.addWidget(self.browser)


def main():
    app = QApplication(sys.argv)

    window = EmbeddedBrowser()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
