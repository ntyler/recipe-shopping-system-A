"""
embedded_store_browser.py

Opens a desktop embedded browser window for a store login / store selector page.
The Flask app launches this script when you click the Credentials button for a store.

Install once if needed:
    py -3.11 -m pip install PyQt5 PyQtWebEngine

Manual test:
    py -3.11 embedded_store_browser.py --store-key aldi --store-label Aldi --url https://www.aldi.us/store/aldi/storefront
"""

import argparse
import sys

from PyQt5.QtCore import QUrl
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QHBoxLayout, QLabel
from PyQt5.QtWebEngineWidgets import QWebEngineView


class EmbeddedStoreBrowser(QWidget):
    def __init__(self, store_key: str, store_label: str, url: str):
        super().__init__()

        self.store_key = store_key
        self.store_label = store_label or store_key.title()
        self.url = url

        self.setWindowTitle(f"Store Credentials - {self.store_label}")
        self.resize(1600, 1000)

        root = QVBoxLayout()
        self.setLayout(root)

        toolbar = QHBoxLayout()

        title = QLabel(f"{self.store_label} credential browser")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        toolbar.addWidget(title)
        toolbar.addStretch(1)

        close_button = QPushButton("Close Window")
        close_button.clicked.connect(self.close)
        toolbar.addWidget(close_button)

        root.addLayout(toolbar)

        self.browser = QWebEngineView()
        self.browser.load(QUrl(self.url))
        root.addWidget(self.browser)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--store-key", default="store")
    parser.add_argument("--store-label", default="Store")
    parser.add_argument("--url", required=True)
    return parser.parse_args()


def main():
    args = parse_args()

    app = QApplication(sys.argv)
    window = EmbeddedStoreBrowser(
        store_key=args.store_key,
        store_label=args.store_label,
        url=args.url,
    )
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
