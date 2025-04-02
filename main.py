import sys
import os
import time
import hashlib
import shutil
import tempfile
import requests
import subprocess
import re

from PyQt5.QtGui import QPixmap, QFont, QIcon
from PyQt5.QtWidgets import (
    QApplication, QWidget, QMainWindow, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QListWidget, QTextEdit, QSplitter, QLabel, QListWidgetItem,
    QTabWidget, QProgressBar, QComboBox, QFileDialog, QStackedWidget, QFrame,
    QScrollArea
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

QUALITY_MAPPING = {
    "Low": "worstaudio",
    "Medium": "bestaudio[abr<=128]",
    "High": "bestaudio"
}

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

class DescriptionFetcher(QThread):
    descriptionFetched = pyqtSignal(str)
    def __init__(self, href):
        super().__init__()
        self.href = href
    def run(self):
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        driver = webdriver.Chrome(options=chrome_options)
        description = ""
        try:
            driver.get(self.href)
            time.sleep(3)
            try:
                driver.find_element(By.CLASS_NAME, 'sc-c-synopsis__button').click()
                time.sleep(2)
            except Exception:
                pass
            try:
                description = driver.find_element(By.CLASS_NAME, 'sc-c-synopsis').text
            except Exception as e:
                description = f"Error retrieving description: {e}"
        except Exception as ex:
            description = f"Error fetching page: {ex}"
        finally:
            driver.quit()
        self.descriptionFetched.emit(description)

class CoverImageFetcher(QThread):
    coverFetched = pyqtSignal(str)
    def __init__(self, href, temp_dir):
        super().__init__()
        self.href = href
        self.temp_dir = temp_dir
    def run(self):
        local_file = ""
        try:
            response = requests.get(self.href)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                picture_tag = soup.find("picture")
                if picture_tag:
                    img_tag = picture_tag.find("img")
                    if img_tag:
                        img_url = img_tag.get("src", "")
                        if img_url.startswith("/"):
                            img_url = "https://www.bbc.co.uk" + img_url
                        img_response = requests.get(img_url)
                        if img_response.status_code == 200:
                            hash_name = hashlib.md5(img_url.encode("utf-8")).hexdigest()
                            ext = ".jpg"
                            if ".webp" in img_url:
                                ext = ".webp"
                            elif ".png" in img_url:
                                ext = ".png"
                            local_file = os.path.join(self.temp_dir, f"{hash_name}{ext}")
                            with open(local_file, "wb") as f:
                                f.write(img_response.content)
        except Exception as e:
            local_file = f"Error: {e}"
        self.coverFetched.emit(local_file)

class DownloadWorker(QThread):
    progressChanged = pyqtSignal(int)
    downloadFinished = pyqtSignal(str, str)
    def __init__(self, episode_url, download_location, download_quality):
        super().__init__()
        self.episode_url = episode_url
        self.download_location = download_location
        self.download_quality = download_quality
    def run(self):
        try:
            cmd = ["yt-dlp", "--newline", "-o",
                   os.path.join(self.download_location, "%(title)s.%(ext)s"),
                   "-f", self.download_quality, self.episode_url]
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True)
            for line in process.stdout:
                match = re.search(r"\[download\]\s+(\d+(?:\.\d+)?)%", line)
                if match:
                    percentage = float(match.group(1))
                    self.progressChanged.emit(int(percentage))
            process.wait()
            if process.returncode == 0:
                self.downloadFinished.emit("Download completed successfully.", self.episode_url)
            else:
                self.downloadFinished.emit("Download failed.", self.episode_url)
        except Exception as e:
            self.downloadFinished.emit(f"Error: {str(e)}", self.episode_url)

class DownloadManager(QObject):
    progressChanged = pyqtSignal(int)
    downloadFinished = pyqtSignal(str, str)
    queueUpdated = pyqtSignal()
    def __init__(self, download_location, download_quality):
        super().__init__()
        self.download_location = download_location
        self.download_quality = download_quality
        self.queue = []
        self.current_worker = None
    def addDownload(self, episode_url):
        self.queue.append(episode_url)
        self.queueUpdated.emit()
        if not self.current_worker:
            self.startNextDownload()
    def startNextDownload(self):
        if self.queue:
            episode_url = self.queue.pop(0)
            self.current_worker = DownloadWorker(episode_url, self.download_location, self.download_quality)
            self.current_worker.progressChanged.connect(self.progressChanged.emit)
            self.current_worker.downloadFinished.connect(self.onDownloadFinished)
            self.current_worker.start()
            self.queueUpdated.emit()
    def onDownloadFinished(self, message, episode_url):
        self.downloadFinished.emit(message, episode_url)
        self.current_worker = None
        self.startNextDownload()

class QueueItemWidget(QWidget):
    def __init__(self, episode_url, is_active=False):
        super().__init__()
        self.episode_url = episode_url
        self.init_ui(is_active)
    def init_ui(self, is_active):
        self.setStyleSheet("""
            QWidget {
                background-color: #222222;
                border: 1px solid #FF8200;
                border-radius: 8px;
                padding: 10px;
                margin: 5px;
            }
            QLabel {
                font-weight: bold;
                color: white;
            }
        """)
        layout = QHBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        self.label = QLabel(self.episode_url)
        layout.addWidget(self.label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(is_active)
        self.progress.setFixedWidth(150)
        self.progress.setStyleSheet("""
            QProgressBar {
                background-color: #444444;
                border: 1px solid #FF8200;
                border-radius: 5px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #FF8200;
                border-radius: 5px;
            }
        """)
        layout.addWidget(self.progress)
        self.setLayout(layout)
    def setProgress(self, value):
        self.progress.setVisible(True)
        self.progress.setValue(value)

class QueuePage(QWidget):
    def __init__(self, download_manager):
        super().__init__()
        self.download_manager = download_manager
        self.queue_widgets = {}
        self.init_ui()
        self.download_manager.queueUpdated.connect(self.update_queue)
        self.download_manager.progressChanged.connect(self.update_active_progress)
    def init_ui(self):
        main_layout = QVBoxLayout(self)
        header = QLabel("Download Queue:")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: white;")
        main_layout.addWidget(header)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setAlignment(Qt.AlignTop)
        self.scroll_area.setWidget(self.scroll_content)
        main_layout.addWidget(self.scroll_area)
        self.update_queue()
    def update_queue(self):
        for i in reversed(range(self.scroll_layout.count())):
            widget = self.scroll_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        self.queue_widgets.clear()
        if self.download_manager.current_worker:
            active_widget = QueueItemWidget(self.download_manager.current_worker.episode_url, is_active=True)
            self.queue_widgets[self.download_manager.current_worker.episode_url] = active_widget
            self.scroll_layout.addWidget(active_widget)
        for url in self.download_manager.queue:
            widget = QueueItemWidget(url, is_active=False)
            self.queue_widgets[url] = widget
            self.scroll_layout.addWidget(widget)
    def update_active_progress(self, percentage):
        if self.download_manager.current_worker:
            url = self.download_manager.current_worker.episode_url
            if url in self.queue_widgets:
                self.queue_widgets[url].setProgress(percentage)

class EpisodesWidget(QWidget):
    def __init__(self, show_url, main_window, download_manager):
        super().__init__()
        self.show_url = show_url
        self.main_window = main_window
        self.download_manager = download_manager
        self.episodes_data = []
        self.description_cache = {}
        self.cover_cache = {}
        self.fetcher = None
        self.cover_fetcher = None
        self._is_active = True
        self.current_episode_href = None
        self.temp_dir = tempfile.mkdtemp(prefix="bbc_podcast_")
        self.init_ui()
        self.load_episodes()
    def init_ui(self):
        main_layout = QVBoxLayout()
        self.back_button = QPushButton("Back to Search")
        self.back_button.clicked.connect(self.main_window.show_search_page)
        main_layout.addWidget(self.back_button)
        splitter = QSplitter(Qt.Horizontal)
        self.episode_list = QListWidget()
        splitter.addWidget(self.episode_list)
        right_widget = QWidget()
        right_layout = QVBoxLayout()
        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setAcceptRichText(True)
        right_layout.addWidget(self.info_text)
        self.download_button = QPushButton("Download Episode")
        self.download_button.setEnabled(False)
        self.download_button.clicked.connect(self.download_episode)
        right_layout.addWidget(self.download_button)
        self.download_progress = QProgressBar()
        self.download_progress.setRange(0, 100)
        self.download_progress.setValue(0)
        self.download_progress.setVisible(False)
        right_layout.addWidget(self.download_progress)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        right_layout.addWidget(self.progress_bar)
        self.cover_progress_bar = QProgressBar()
        self.cover_progress_bar.setRange(0, 0)
        self.cover_progress_bar.setVisible(False)
        right_layout.addWidget(self.cover_progress_bar)
        right_widget.setLayout(right_layout)
        splitter.addWidget(right_widget)
        splitter.setSizes([250, 400])
        main_layout.addWidget(splitter)
        self.setLayout(main_layout)
        self.episode_list.itemClicked.connect(self.display_episode_info)
    def load_episodes(self):
        page = 1
        found_any = True
        self.episodes_data.clear()
        self.episode_list.clear()
        while found_any:
            url = f"{self.show_url}?page={page}"
            response = requests.get(url)
            if response.status_code != 200:
                break
            soup = BeautifulSoup(response.text, "html.parser")
            page_items = soup.find_all("div", class_="sw-grow sw--ml-2 m:sw--ml-4 sw-relative")
            if not page_items:
                found_any = False
            else:
                for item in page_items:
                    a_tag = item.find("a")
                    if a_tag:
                        href = a_tag.get("href", "")
                        if href.startswith("/"):
                            href = "https://www.bbc.co.uk" + href
                        aria_label = a_tag.get("aria-label", "")
                        parts = aria_label.split(",")
                        if len(parts) >= 2:
                            series_name = parts[0].strip()
                            episode_name = parts[1].strip()
                        else:
                            series_name = "Unknown Series"
                            episode_name = "Unknown Episode"
                        self.episodes_data.append((series_name, episode_name, href))
                        self.episode_list.addItem(f"{series_name} - {episode_name}")
                page += 1
        if not self.episodes_data:
            self.episode_list.addItem("Failed to retrieve any episodes.")
    def display_episode_info(self, item):
        index = self.episode_list.row(item)
        if index < len(self.episodes_data):
            series_name, episode_name, href = self.episodes_data[index]
            self.current_episode_href = href
            info_html = (f"<b>Series:</b> {series_name}<br>"
                         f"<b>Episode:</b> {episode_name}<br>"
                         f"<b>URL:</b> <a href='{href}'>{href}</a><br><br>")
            self.info_text.setHtml(info_html + "Loading description and cover image...")
            try:
                self.progress_bar.setVisible(True)
                self.cover_progress_bar.setVisible(True)
            except RuntimeError:
                return
            self.download_button.setEnabled(True)
            if href in self.description_cache:
                description = self.description_cache[href]
            else:
                description = None
                self.fetcher = DescriptionFetcher(href)
                self.fetcher.descriptionFetched.connect(
                    lambda d, s=series_name, e=episode_name, url=href: self.on_description_fetched(s, e, url, d)
                )
                self.fetcher.start()
            if href in self.cover_cache:
                cover_image_path = self.cover_cache[href]
            else:
                cover_image_path = None
                self.cover_fetcher = CoverImageFetcher(href, self.temp_dir)
                self.cover_fetcher.coverFetched.connect(
                    lambda path, url=href: self.on_cover_fetched(url, path)
                )
                self.cover_fetcher.start()
            if description is not None and href in self.cover_cache:
                self.update_info(series_name, episode_name, href, description)
                try:
                    self.progress_bar.setVisible(False)
                    self.cover_progress_bar.setVisible(False)
                except RuntimeError:
                    return
        else:
            self.info_text.setPlainText("Error retrieving episode details.")
    def on_description_fetched(self, series_name, episode_name, href, description):
        if not self._is_active:
            return
        self.description_cache[href] = description
        if href in self.cover_cache:
            try:
                self.progress_bar.setVisible(False)
            except RuntimeError:
                return
            self.update_info(series_name, episode_name, href, description)
    def on_cover_fetched(self, href, local_path):
        if not self._is_active:
            return
        try:
            self.cover_progress_bar.setVisible(False)
        except RuntimeError:
            return
        if not local_path.startswith("Error"):
            self.cover_cache[href] = local_path
        else:
            self.cover_cache[href] = ""
        for s, e, h in self.episodes_data:
            if h == href and href in self.description_cache:
                self.update_info(s, e, href, self.description_cache[href])
                break
    def update_info(self, series_name, episode_name, href, description):
        description_html = description.replace("\n", "<br>")
        if href in self.cover_cache and self.cover_cache[href]:
            local_path = self.cover_cache[href]
            file_url = "file:///" + local_path.replace("\\", "/")
            cover_html = f"<img src='{file_url}' alt='Cover Image'><br><br>"
        else:
            cover_html = "Cover image not available.<br><br>"
        info_html = (f"<b>Series:</b> {series_name}<br>"
                     f"<b>Episode:</b> {episode_name}<br><br>"
                     f"<b>Cover Image:</b><br>{cover_html}"
                     f"<b>Description:</b><br>{description_html}<br><br>"
                     f"<b>URL:</b> <a href='{href}'>{href}</a>")
        self.info_text.setHtml(info_html)
    def download_episode(self):
        if self.current_episode_href:
            self.download_manager.addDownload(self.current_episode_href)
            self.info_text.append("<br><i>Episode added to download queue.</i>")
    def closeEvent(self, event):
        self._is_active = False
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
        event.accept()

class SearchWidget(QWidget):
    showSelected = pyqtSignal(str, str, str)
    def __init__(self):
        super().__init__()
        self.selected_show = None
        self.init_ui()
    def init_ui(self):
        main_layout = QVBoxLayout()
        top_layout = QHBoxLayout()
        instruction = QLabel("Enter search term for BBC Sounds shows:")
        top_layout.addWidget(instruction)
        self.search_edit = QLineEdit()
        top_layout.addWidget(self.search_edit)
        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self.perform_search)
        top_layout.addWidget(self.search_button)
        main_layout.addLayout(top_layout)
        splitter = QSplitter(Qt.Horizontal)
        self.results_list = QListWidget()
        self.results_list.itemClicked.connect(self.select_show)
        splitter.addWidget(self.results_list)
        details_widget = QWidget()
        details_layout = QVBoxLayout()
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setAcceptRichText(True)
        details_layout.addWidget(self.details_text)
        self.go_to_show_button = QPushButton("Go to Show")
        self.go_to_show_button.clicked.connect(self.go_to_show)
        self.go_to_show_button.setEnabled(False)
        details_layout.addWidget(self.go_to_show_button)
        details_widget.setLayout(details_layout)
        splitter.addWidget(details_widget)
        splitter.setSizes([250, 350])
        main_layout.addWidget(splitter)
        self.setLayout(main_layout)
    def perform_search(self):
        search_term = self.search_edit.text().strip()
        if not search_term:
            return
        self.results_list.clear()
        self.details_text.clear()
        self.go_to_show_button.setEnabled(False)
        self.selected_show = None
        url = f'https://www.bbc.co.uk/sounds/search?q={search_term}'
        try:
            response = requests.get(url)
        except Exception as e:
            self.results_list.addItem("Error fetching search results.")
            return
        if response.status_code != 200:
            self.results_list.addItem("Failed to retrieve search results.")
            return
        soup = BeautifulSoup(response.text, 'html.parser')
        results = []
        for div in soup.find_all("div", class_="sw-relative sw-pt-2"):
            title_tag = div.find("span", class_=lambda x: x and "sw-text-primary" in x)
            desc_tag = div.find("p", class_=lambda x: x and "sw-text-brevier" in x)
            a_tag = div.find_parent("a", href=True)
            if a_tag:
                href = a_tag["href"]
                if href.startswith("/"):
                    href = "https://www.bbc.co.uk" + href
                title = title_tag.get_text(strip=True) if title_tag else a_tag.get_text(strip=True)
                description = desc_tag.get_text(strip=True) if desc_tag else ""
                if title and (title, description, href) not in results:
                    results.append((title, description, href))
        if not results:
            self.results_list.addItem("No shows found.")
        else:
            for title, description, href in results:
                item = QListWidgetItem(title)
                item.setData(Qt.UserRole, {"url": href, "description": description})
                self.results_list.addItem(item)
    def select_show(self, item):
        data = item.data(Qt.UserRole)
        show_url = data["url"]
        show_description = data["description"]
        show_title = item.text()
        details_html = f"<h2>{show_title}</h2>"
        if show_description:
            details_html += f"<p>{show_description}</p>"
        else:
            details_html += "<p>No description available.</p>"
        self.details_text.setHtml(details_html)
        self.selected_show = (show_url, show_title, show_description)
        self.go_to_show_button.setEnabled(True)
    def go_to_show(self):
        if self.selected_show:
            show_url, show_title, show_description = self.selected_show
            self.showSelected.emit(show_url, show_title, show_description)

class DownloadsPage(QWidget):
    def __init__(self, download_manager):
        super().__init__()
        self.download_manager = download_manager
        self.init_ui()
        self.download_manager.downloadFinished.connect(self.on_download_finished)
        self.download_manager.progressChanged.connect(self.on_progress_changed)
        self.update_downloads_list()
    def init_ui(self):
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Downloaded Episodes (mp4 only):"))
        self.downloads_list = QListWidget()
        layout.addWidget(self.downloads_list)
        self.current_progress = QProgressBar()
        self.current_progress.setRange(0, 100)
        self.current_progress.setValue(0)
        layout.addWidget(QLabel("Current Download Progress:"))
        layout.addWidget(self.current_progress)
        self.setLayout(layout)
    def on_progress_changed(self, percentage):
        self.current_progress.setValue(percentage)
    def on_download_finished(self, message, episode_url):
        self.update_downloads_list()
        self.current_progress.setValue(0)
    def update_downloads_list(self):
        self.downloads_list.clear()
        files = [f for f in os.listdir(self.download_manager.download_location)
                 if f.lower().endswith(".mp4")]
        for f in files:
            self.downloads_list.addItem(f)

class SettingsPage(QWidget):
    settingsChanged = pyqtSignal(str, str)
    def __init__(self, current_location, current_quality):
        super().__init__()
        self.current_location = current_location
        self.current_quality = current_quality
        self.init_ui()
    def init_ui(self):
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background-color: #222222;
                border: 1px solid #FF8200;
                border-radius: 8px;
                padding: 20px;
            }
            QLabel {
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            QLineEdit, QComboBox {
                background-color: #333333;
                border: 1px solid #FF8200;
                color: white;
                padding: 5px;
                border-radius: 4px;
            }
            QPushButton {
                background-color: #FF8200;
                color: black;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #E57300;
            }
            QPushButton:pressed {
                background-color: #CC6600;
            }
        """)
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Download Location:"))
        self.location_edit = QLineEdit(self.current_location)
        layout.addWidget(self.location_edit)
        self.browse_button = QPushButton("Browse")
        self.browse_button.clicked.connect(self.browse_location)
        layout.addWidget(self.browse_button)
        layout.addWidget(QLabel("Download Quality:"))
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["Low", "Medium", "High"])
        index = self.quality_combo.findText(self.current_quality)
        if index >= 0:
            self.quality_combo.setCurrentIndex(index)
        layout.addWidget(self.quality_combo)
        self.save_button = QPushButton("Save Settings")
        self.save_button.clicked.connect(self.save_settings)
        layout.addWidget(self.save_button)
        frame.setLayout(layout)
        main_layout = QVBoxLayout()
        main_layout.addWidget(frame)
        self.setLayout(main_layout)
    def browse_location(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Download Folder", self.current_location)
        if directory:
            self.location_edit.setText(directory)
    def save_settings(self):
        self.current_location = self.location_edit.text().strip()
        self.current_quality = self.quality_combo.currentText()
        self.settingsChanged.emit(self.current_location, QUALITY_MAPPING[self.current_quality])

class MainMenuScreen(QWidget):
    startClicked = pyqtSignal()
    def __init__(self):
        super().__init__()
        self.init_ui()
    def init_ui(self):
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignCenter)
        self.logo_label = QLabel()
        pixmap = QPixmap(resource_path("logo.png"))
        scaled_pixmap = pixmap.scaledToWidth(600, Qt.SmoothTransformation)
        self.logo_label.setPixmap(scaled_pixmap)
        self.logo_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.logo_label)
        layout.addSpacing(50)
        self.start_button = QPushButton("Start")
        self.start_button.setFixedWidth(300)
        self.start_button.setFixedHeight(50)
        self.start_button.clicked.connect(self.startClicked.emit)
        layout.addWidget(self.start_button, alignment=Qt.AlignCenter)
        self.setLayout(layout)

class SearchContainer(QWidget):
    def __init__(self, download_manager, main_window):
        super().__init__()
        self.download_manager = download_manager
        self.main_window = main_window
        self.stack = QStackedWidget()
        layout = QVBoxLayout()
        layout.addWidget(self.stack)
        self.setLayout(layout)
        self.search_widget = SearchWidget()
        self.search_widget.showSelected.connect(self.show_episodes)
        self.stack.addWidget(self.search_widget)
    def show_episodes(self, show_url, show_title, show_description):
        self.episodes_widget = EpisodesWidget(show_url, self.main_window, self.download_manager)
        self.stack.addWidget(self.episodes_widget)
        self.stack.setCurrentWidget(self.episodes_widget)
    def showSearch(self):
        self.stack.setCurrentWidget(self.search_widget)
        if hasattr(self, 'episodes_widget'):
            self.episodes_widget.deleteLater()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BBC Sounds Downloader")
        self.setWindowIcon(QIcon(resource_path("app_icon.png")))
        self.resize(900, 600)
        self.download_location = os.getcwd()
        self.download_quality = QUALITY_MAPPING["Medium"]
        self.download_manager = DownloadManager(self.download_location, self.download_quality)
        self.stacked_widget = QStackedWidget()
        self.setCentralWidget(self.stacked_widget)
        self.main_menu = MainMenuScreen()
        self.main_menu.startClicked.connect(self.show_main_app)
        self.stacked_widget.addWidget(self.main_menu)
        self.tab_widget = QTabWidget()
        self.search_container = SearchContainer(self.download_manager, self)
        self.tab_widget.addTab(self.search_container, "Search")
        self.downloads_page = DownloadsPage(self.download_manager)
        self.tab_widget.addTab(self.downloads_page, "Downloads")
        self.queue_page = QueuePage(self.download_manager)
        self.tab_widget.addTab(self.queue_page, "Queue")
        self.settings_page = SettingsPage(self.download_location, "Medium")
        self.settings_page.settingsChanged.connect(self.update_settings)
        self.tab_widget.addTab(self.settings_page, "Settings")
        self.stacked_widget.addWidget(self.tab_widget)
    def show_main_app(self):
        self.stacked_widget.setCurrentWidget(self.tab_widget)
    def update_settings(self, location, quality):
        self.download_location = location
        self.download_quality = quality
        self.download_manager.download_location = location
        self.download_manager.download_quality = quality
    def show_search_page(self):
        self.search_container.showSearch()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    style = """
    QMainWindow { background-color: #000000; }
    QWidget { font-family: Arial; font-size: 14px; color: white; background-color: #000000; }
    QTabWidget::pane { background-color: #000000; }
    QTabWidget { background-color: #000000; }
    QPushButton { background-color: #FF8200; color: black; border: none; padding: 6px 12px; border-radius: 4px; font-size: 20px; }
    QPushButton:hover { background-color: #E57300; }
    QPushButton:pressed { background-color: #CC6600; }
    QLineEdit, QTextEdit, QListWidget { background-color: #333333; border: 1px solid #FF8200; color: white; padding: 4px; border-radius: 4px; }
    QProgressBar { background-color: #333333; border: 1px solid #FF8200; text-align: center; height: 15px; border-radius: 7px; color: white; }
    QProgressBar::chunk { background-color: #FF8200; border-radius: 7px; }
    QScrollBar:vertical { background: #333333; width: 12px; margin: 0px; }
    QScrollBar::handle:vertical { background: #FF8200; min-height: 20px; border-radius: 4px; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { background: none; }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
    QScrollBar:horizontal { background: #333333; height: 12px; margin: 0px; }
    QScrollBar::handle:horizontal { background: #FF8200; min-width: 20px; border-radius: 4px; }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { background: none; }
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: none; }
    QSplitter::handle { background-color: #000000; }
    QTabBar::tab { background: #333333; color: white; padding: 10px; border: 1px solid #FF8200; border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px; }
    QTabBar::tab:selected { background: #FF8200; color: black; border-bottom: 1px solid #FF8200; }
    QTabBar::tab:hover { background: #555555; }
    """
    app.setStyleSheet(style)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
