#!/usr/bin/env python3
"""Arizona Launcher for Linux — неофициальный нативный лаунчер Arizona RP / Rodina RP.

Интерфейс на Qt (PySide6). Файлы игры скачиваются с тех же серверов, что и в
официальном лаунчере; сама игра (gta_sa.exe) запускается через Wine.
"""

import hashlib
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import PySide6  # noqa: F401
except ImportError:
    _msg = "Не установлен PySide6. Выполните ./install.sh или: pip install --user PySide6"
    print(_msg, file=sys.stderr)
    if shutil.which("kdialog"):
        subprocess.run(["kdialog", "--error", _msg])
    sys.exit(1)

from PySide6.QtCore import QObject, QPointF, QRectF, QSize, QSortFilterProxyModel, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QAction, QColor, QDesktopServices, QFont, QIcon, QImage, QPainter, QPainterPath, QPen,
                           QPixmap, QRegularExpressionValidator, QStandardItem, QStandardItemModel)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSpinBox, QSplitter,
    QSystemTrayIcon, QTabWidget, QTableView, QTextBrowser, QToolButton, QVBoxLayout, QWidget,
)
from PySide6.QtCore import QRegularExpression

import arizona_core as core
from arizona_core import GAMES, OPTION_INFO

APP_NAME = "Arizona Launcher for Linux"
POOL = ThreadPoolExecutor(max_workers=8)
IMG_POOL = ThreadPoolExecutor(max_workers=6)

STYLE = """
QWidget { font-size: 10.5pt; }
QMainWindow, QDialog { background: #15171c; }
QWidget#central, QTabWidget::pane, QScrollArea, QScrollArea > QWidget > QWidget { background: #15171c; }
QLabel { color: #e6e6e6; }
QLabel[muted="true"] { color: #8b8f99; }
QLabel#title { font-size: 15pt; font-weight: 700; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: transparent; color: #8b8f99; padding: 10px 18px; border: none;
               border-bottom: 2px solid transparent; font-weight: 600; }
QTabBar::tab:selected { color: #fff; border-bottom: 2px solid #f0a020; }
QTabBar::tab:hover { color: #ddd; }
QLineEdit, QComboBox, QSpinBox { background: #20232b; color: #eee; border: 1px solid #2d313b;
               border-radius: 6px; padding: 6px 8px; }
QLineEdit:focus, QComboBox:focus { border-color: #f0a020; }
QComboBox QAbstractItemView { background: #20232b; color: #eee; selection-background-color: #f0a020; }
QPushButton, QToolButton { background: #262a33; color: #e6e6e6; border: 1px solid #323743;
               border-radius: 6px; padding: 7px 14px; }
QPushButton:hover, QToolButton:hover { background: #2e333e; }
QPushButton:disabled { color: #666; }
QPushButton#play { background: #f0a020; color: #15171c; font-size: 13pt; font-weight: 800;
               border: none; padding: 10px 34px; border-radius: 8px; min-width: 150px; }
QPushButton#play:hover { background: #ffb436; }
QPushButton#play[cancel="true"] { background: #3a3f4b; color: #fff; }
QProgressBar { background: #20232b; border: none; border-radius: 4px; height: 8px; text-align: center;
               color: transparent; }
QProgressBar::chunk { background: #f0a020; border-radius: 4px; }
QTableView, QListWidget, QTextBrowser { background: #1a1d23; color: #e6e6e6; border: 1px solid #262a33;
               border-radius: 8px; alternate-background-color: #1d2027; gridline-color: transparent;
               selection-background-color: #3a2f18; selection-color: #fff; }
QHeaderView::section { background: #1a1d23; color: #8b8f99; border: none; padding: 6px; font-weight: 600; }
QCheckBox { color: #e6e6e6; spacing: 8px; }
QFrame#panel { background: #1a1d23; border: 1px solid #262a33; border-radius: 10px; }
QFrame#bottom { background: #101216; border-top: 1px solid #262a33; }
QMenu { background: #20232b; color: #eee; border: 1px solid #323743; }
QMenu::item:selected { background: #3a2f18; }
QScrollBar:vertical { background: transparent; width: 10px; }
QScrollBar::handle:vertical { background: #323743; border-radius: 5px; min-height: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
"""


ICON_NAME = "arizona-launcher"
ORIGINAL_ICON = "arizona-launcher-original"   # иконка из официального лаунчера пользователя
XDG_DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
ICON_SIZES = (256, 128, 64, 48, 32, 16)


def _desktop_file():
    """Ярлык лаунчера: пользовательский, а если его нет (установка пакетом) — системный."""
    user = XDG_DATA / "applications" / "arizona-launcher.desktop"
    if user.exists():
        return user, user
    for d in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":"):
        f = Path(d) / "applications" / "arizona-launcher.desktop"
        if f.exists():
            return f, user     # системный не трогаем — копия в ~/.local главнее
    return None, user


def install_original_icon(cfg, exe=None):
    """Взять иконку из официального лаунчера Arizona (если он найден) и поставить её
    лаунчеру: ярлык, док, окно. Повторно — только если файл-источник изменился.
    Возвращает True, если оригинальная иконка установлена."""
    icons = XDG_DATA / "icons" / "hicolor"
    have = (icons / "256x256" / "apps" / f"{ORIGINAL_ICON}.png").exists()
    exe = Path(exe) if exe else core.find_official_launcher(cfg)
    if not exe or not exe.is_file():
        return have
    st = exe.stat()
    stamp = f"{exe.resolve()}:{st.st_size}:{int(st.st_mtime)}"
    marker = core.DATA_DIR / "icon-source"
    try:
        if have and marker.read_text() == stamp:
            return True
    except OSError:
        pass
    data = core.exe_icon_bytes(exe)
    img = QImage.fromData(data) if data else QImage()
    if img.isNull():
        return have
    for sz in ICON_SIZES:
        dst = icons / f"{sz}x{sz}" / "apps" / f"{ORIGINAL_ICON}.png"
        dst.parent.mkdir(parents=True, exist_ok=True)
        img.scaled(sz, sz, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(str(dst), "PNG")
    src, dst = _desktop_file()
    if src:
        lines = src.read_text(encoding="utf-8").splitlines()
        new = [f"Icon={ORIGINAL_ICON}" if ln.startswith("Icon=") else ln for ln in lines]
        if new != lines or src != dst:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text("\n".join(new) + "\n", encoding="utf-8")
    for cmd in (["gtk-update-icon-cache", "-f", "-t", str(icons)],
                ["update-desktop-database", str(XDG_DATA / "applications")], ["kbuildsycoca6"]):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    core.DATA_DIR.mkdir(parents=True, exist_ok=True)
    marker.write_text(stamp)
    return True


def app_icon():
    """Иконка окна: из официального лаунчера, если есть, иначе своя."""
    for name in (ORIGINAL_ICON, ICON_NAME):
        icon = QIcon()
        for sz in ICON_SIZES:
            f = XDG_DATA / "icons/hicolor" / f"{sz}x{sz}/apps/{name}.png"
            if f.exists():
                icon.addFile(str(f))
        if icon.isNull():
            icon = QIcon.fromTheme(name)
        if not icon.isNull():
            return icon
    return QIcon.fromTheme("applications-games")


def human_size(n):
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if abs(n) < 1024 or unit == "ГБ":
            return f"{n:.1f} {unit}" if unit != "Б" else f"{int(n)} {unit}"
        n /= 1024


def muted(text=""):
    lab = QLabel(text)
    lab.setProperty("muted", True)
    lab.setWordWrap(True)
    return lab


def open_path(p):
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))


def open_url(u):
    QDesktopServices.openUrl(QUrl(u))


# ---------------------------------------------------------------- фоновые задачи → Qt

class Bridge(QObject):
    servers = Signal(object, str)          # dict | None, error
    projects = Signal(object)
    cdn = Signal(object)
    progress = Signal(str, float, float, str)
    task_done = Signal(str, object, str)   # kind, result, error
    log = Signal(str)
    image = Signal(str, bytes)
    mods = Signal(object, object, str)     # top, mods, error
    mod_done = Signal(int, bool, str)      # mod id, installed, error
    mod_progress = Signal(str)
    game_exit = Signal()
    icon_ready = Signal()


class Images:
    """Загрузка картинок по URL с кэшем на диске."""

    def __init__(self, bridge):
        self.bridge = bridge
        self.mem = {}
        self.pending = set()
        self.dir = core.CACHE_DIR / "img"
        bridge.image.connect(self._loaded)
        self.waiters = {}

    def get(self, url, cb):
        if not url:
            return
        if url in self.mem:
            cb(self.mem[url])
            return
        self.waiters.setdefault(url, []).append(cb)
        if url in self.pending:
            return
        self.pending.add(url)
        IMG_POOL.submit(self._fetch, url)

    def _fetch(self, url):
        f = self.dir / hashlib.sha1(url.encode()).hexdigest()
        try:
            if f.exists() and time.time() - f.stat().st_mtime < 7 * 86400:
                data = f.read_bytes()
            else:
                data = core.http_get(url.replace("http://", "https://", 1), timeout=20)
                self.dir.mkdir(parents=True, exist_ok=True)
                f.write_bytes(data)
        except Exception:  # noqa: BLE001
            data = b""
        self.bridge.image.emit(url, data)

    def _loaded(self, url, data):
        self.pending.discard(url)
        pm = QPixmap()
        if data:
            pm.loadFromData(data)
        if pm.isNull():
            self.waiters.pop(url, None)
            return
        self.mem[url] = pm
        for cb in self.waiters.pop(url, []):
            try:
                cb(pm)
            except RuntimeError:
                pass   # виджет уже удалён


def rounded(pm, size, radius=10):
    pm = pm.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    out = QPixmap(size, size)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    p.setClipPath(path)
    p.drawPixmap((size - pm.width()) // 2, (size - pm.height()) // 2, pm)
    p.end()
    return out


# ---------------------------------------------------------------- виджеты

class OnlineGraph(QWidget):
    """График онлайна сервера за последние сутки (plotPoints из API)."""

    def __init__(self):
        super().__init__()
        self.points = []
        self.max = 1000
        self.setMinimumHeight(110)

    def set_data(self, points, maxplayers):
        self.points = [(p.get("time", 0), p.get("online", 0)) for p in points or []]
        self.max = max(maxplayers or 1, max((o for _, o in self.points), default=1))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(4, 8, -4, -18)
        p.setPen(QPen(QColor("#2a2e37"), 1))
        for k in range(5):
            y = r.top() + r.height() * k / 4
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        if len(self.points) < 2:
            p.setPen(QColor("#8b8f99"))
            p.drawText(self.rect(), Qt.AlignCenter, "Нет данных")
            return
        n = len(self.points)
        pts = [QPointF(r.left() + r.width() * i / (n - 1), r.bottom() - r.height() * o / self.max)
               for i, (_, o) in enumerate(self.points)]
        fill = QPainterPath(QPointF(pts[0].x(), r.bottom()))
        for pt in pts:
            fill.lineTo(pt)
        fill.lineTo(QPointF(pts[-1].x(), r.bottom()))
        c = QColor("#f0a020")
        c.setAlpha(45)
        p.fillPath(fill, c)
        line = QPainterPath(pts[0])
        for pt in pts[1:]:
            line.lineTo(pt)
        p.setPen(QPen(QColor("#f0a020"), 2))
        p.drawPath(line)
        p.setPen(QColor("#8b8f99"))
        f = p.font()
        f.setPointSizeF(8)
        p.setFont(f)
        first = time.strftime("%H:%M", time.localtime(self.points[0][0]))
        last = time.strftime("%H:%M", time.localtime(self.points[-1][0]))
        p.drawText(QRectF(r.left(), r.bottom() + 2, 80, 14), Qt.AlignLeft, first)
        p.drawText(QRectF(r.right() - 80, r.bottom() + 2, 80, 14), Qt.AlignRight, last)
        p.drawText(QRectF(r.left() + 2, r.top() - 8, 120, 14), Qt.AlignLeft, f"макс. {self.max}")


SORT = Qt.UserRole + 1
DATA = Qt.UserRole + 2


class ServersTab(QWidget):
    play_requested = Signal(dict)

    def __init__(self, images):
        super().__init__()
        self.images = images
        self.sorted_once = False
        self.model = QStandardItemModel(0, 5)
        self.model.setHorizontalHeaderLabels(["Сервер", "№", "Онлайн", "Очередь", "Бонусы"])
        self.proxy = QSortFilterProxyModel()
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(SORT)
        self.proxy.setFilterKeyColumn(0)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)

        self.search = QLineEdit(placeholderText="Поиск сервера...")
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        self.refresh_btn = QPushButton("Обновить")

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setIconSize(QSize(30, 30))
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, 5):
            h.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.selectionModel().currentRowChanged.connect(self._selected)
        self.table.doubleClicked.connect(lambda _: self.current() and self.play_requested.emit(self.current()))

        # панель сервера
        self.panel = QFrame(objectName="panel")
        self.panel.setMinimumWidth(300)
        pl = QVBoxLayout(self.panel)
        top = QHBoxLayout()
        self.icon = QLabel()
        self.icon.setFixedSize(72, 72)
        top.addWidget(self.icon)
        nb = QVBoxLayout()
        self.name = QLabel("Выберите сервер", objectName="title")
        self.addr = muted()
        nb.addWidget(self.name)
        nb.addWidget(self.addr)
        top.addLayout(nb, 1)
        pl.addLayout(top)
        self.stats = QLabel()
        self.stats.setWordWrap(True)
        self.stats.setTextFormat(Qt.RichText)
        pl.addWidget(self.stats)
        pl.addWidget(muted("Онлайн за сутки"))
        self.graph = OnlineGraph()
        pl.addWidget(self.graph)
        links = QHBoxLayout()
        self.tg = QPushButton("Telegram")
        self.vk = QPushButton("VK")
        for b in (self.tg, self.vk):
            b.clicked.connect(lambda _=False, b=b: b.property("url") and open_url(b.property("url")))
            links.addWidget(b)
        links.addStretch()
        pl.addLayout(links)
        pl.addStretch()
        self.play_here = QPushButton("Играть на этом сервере", objectName="play")
        self.play_here.clicked.connect(lambda: self.current() and self.play_requested.emit(self.current()))
        pl.addWidget(self.play_here)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.addWidget(self.search, 1)
        bar.addWidget(self.refresh_btn)
        ll.addLayout(bar)
        ll.addWidget(self.table)
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(self.panel)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        lay = QVBoxLayout(self)
        lay.addWidget(split)

    def set_servers(self, servers, select_number=None):
        self.model.setRowCount(0)
        for s in servers:
            name = QStandardItem(("★ " if s.get("recomend") else "") + s["name"])
            name.setData(s["name"].lower(), SORT)
            name.setData(s, DATA)
            if s.get("recomend"):
                name.setToolTip("Рекомендуемый сервер")
            num = QStandardItem(str(s.get("number", "")))
            num.setData(s.get("number", 0), SORT)
            online = QStandardItem(f"{s.get('online', 0)} / {s.get('maxplayers', 0)}")
            online.setData(s.get("online", 0), SORT)
            q = s.get("queue") or 0
            queue = QStandardItem(str(q) if q else "—")
            queue.setData(q, SORT)
            bonus = []
            if (s.get("experienceMultiplier") or 1) > 1:
                bonus.append(f"опыт x{s['experienceMultiplier']}")
            if (s.get("donateMultiplier") or 1) > 1:
                bonus.append(f"донат x{s['donateMultiplier']}")
            b = QStandardItem(", ".join(bonus))
            b.setData(len(bonus), SORT)
            for it in (num, online, queue):
                it.setTextAlignment(Qt.AlignCenter)
            if s.get("password"):
                name.setText(name.text() + "  🔒")
            row = [name, num, online, queue, b]
            self.model.appendRow(row)
            self.images.get(s.get("icon"), lambda pm, it=name: it.setIcon(QIcon(rounded(pm, 60, 12))))
        if not self.sorted_once:
            self.sorted_once = True
            self.table.sortByColumn(2, Qt.DescendingOrder)
        self.select(select_number)

    def select(self, number):
        target = None
        for r in range(self.proxy.rowCount()):
            s = self.proxy.index(r, 0).data(DATA)
            if number is not None and s.get("number") == number:
                target = r
                break
        if target is None and self.proxy.rowCount():
            target = 0
        if target is not None:
            self.table.selectRow(target)

    def current(self):
        idx = self.table.currentIndex()
        if not idx.isValid():
            return None
        return self.proxy.index(idx.row(), 0).data(DATA)

    def _selected(self, *_):
        s = self.current()
        if not s:
            return
        self.name.setText(s["name"])
        self.addr.setText(f"{s['ip']}:{s['port']}")
        self.icon.clear()
        num = s.get("number")
        self.images.get(s.get("icon"), lambda pm: (self.current() or {}).get("number") == num
                        and self.icon.setPixmap(rounded(pm, 72, 14)))
        parts = [f"<b>Онлайн:</b> {s.get('online', 0)} из {s.get('maxplayers', 0)}"]
        if s.get("queue"):
            parts.append(f"<b>Очередь:</b> {s['queue']}")
        if s.get("experienceMultiplier"):
            parts.append(f"<b>Опыт:</b> x{s['experienceMultiplier']}")
        if s.get("donateMultiplier"):
            parts.append(f"<b>Донат:</b> x{s['donateMultiplier']}")
        if s.get("recomend"):
            parts.append("<span style='color:#f0a020'>★ Рекомендуемый для новичков</span>")
        self.stats.setText("<br>".join(parts))
        self.graph.set_data(s.get("plotPoints"), s.get("maxplayers"))
        self.tg.setProperty("url", s.get("tg"))
        self.vk.setProperty("url", s.get("vk"))
        self.tg.setVisible(bool(s.get("tg")))
        self.vk.setVisible(bool(s.get("vk")))


class NewsTab(QWidget):
    def __init__(self, images):
        super().__init__()
        self.images = images
        lay = QVBoxLayout(self)
        self.links = QHBoxLayout()
        lay.addLayout(self.links)
        self.list = QListWidget()
        self.list.setIconSize(QSize(192, 108))
        self.list.setSpacing(4)
        self.list.setWordWrap(True)
        self.list.itemActivated.connect(lambda it: it.data(DATA) and open_url(it.data(DATA)))
        self.list.itemClicked.connect(lambda it: it.data(DATA) and open_url(it.data(DATA)))
        lay.addWidget(self.list)
        self.empty = muted("Новостей нет.")
        lay.addWidget(self.empty)

    def set_game(self, game, projects):
        while self.links.count():
            w = self.links.takeAt(0).widget()
            if w:
                w.deleteLater()
        for title, url in GAMES[game]["links"].items():
            b = QPushButton(title)
            b.clicked.connect(lambda _=False, u=url: open_url(u))
            self.links.addWidget(b)
        self.links.addStretch()
        self.list.clear()
        proj = next((p for p in projects or [] if p.get("gameId") == game), None)
        news = (proj or {}).get("news") or []
        for n in news:
            it = QListWidgetItem(f"{n.get('title', '')}\n{n.get('date', '')}\n{n.get('description', '')}")
            it.setData(DATA, n.get("url"))
            it.setToolTip(n.get("url") or "")
            ph = QPixmap(192, 108)
            ph.fill(QColor("#20232b"))
            it.setIcon(QIcon(ph))
            self.list.addItem(it)
            self.images.get(n.get("imageUrl"), lambda pm, it=it: it.setIcon(QIcon(
                pm.scaled(192, 108, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation).copy(0, 0, 192, 108))))
        self.list.setVisible(bool(news))
        self.empty.setVisible(not news)


class ModsTab(QWidget):
    install = Signal(dict)
    uninstall = Signal(dict)
    reload = Signal()

    CATEGORIES = {"script": "Скрипты", "graphic": "Графика", "visual": "Визуал", "sound": "Звук", "transport": "Транспорт",
                  "weapon": "Оружие", "interface": "Интерфейс", "other": "Другое"}

    def __init__(self, images):
        super().__init__()
        self.images = images
        self.mods = []
        self.installed = {}
        self.busy = set()
        self.search = QLineEdit(placeholderText="Поиск мода...")
        self.cat = QComboBox()
        self.only_inst = QCheckBox("Установленные")
        self.refresh_btn = QPushButton("Обновить")
        self.refresh_btn.clicked.connect(self.reload)
        for w in (self.search,):
            w.textChanged.connect(self._fill)
        self.cat.currentIndexChanged.connect(self._fill)
        self.only_inst.toggled.connect(self._fill)
        self.list = QListWidget()
        self.list.setIconSize(QSize(48, 48))
        self.list.setWordWrap(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.currentItemChanged.connect(self._show)

        self.panel = QFrame(objectName="panel")
        pl = QVBoxLayout(self.panel)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setMinimumHeight(160)
        self.title = QLabel(objectName="title")
        self.title.setWordWrap(True)
        self.meta = muted()
        self.desc = QTextBrowser()
        self.desc.setOpenExternalLinks(True)
        self.action = QPushButton(objectName="play")
        self.action.clicked.connect(self._action)
        for w in (self.image, self.title, self.meta):
            pl.addWidget(w)
        pl.addWidget(self.desc, 1)
        pl.addWidget(self.action)
        self.note = muted("Моды скачиваются с серверов проекта. Файлы, заменённые модом, вернутся "
                          "к оригиналу после удаления мода и проверки файлов.")
        pl.addWidget(self.note)
        self.status = muted("Загрузка списка модов...")

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.addWidget(self.search, 1)
        bar.addWidget(self.cat)
        bar.addWidget(self.only_inst)
        bar.addWidget(self.refresh_btn)
        ll.addLayout(bar)
        ll.addWidget(self.status)
        ll.addWidget(self.list)
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(self.panel)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        QVBoxLayout(self).addWidget(split)
        self.panel.hide()

    def set_mods(self, top, mods, installed, error=""):
        top_ids = {m["id"] for m in top}
        self.mods = [dict(m, top=True) for m in top] + [m for m in mods if m["id"] not in top_ids]
        self.mods = [m for m in self.mods if m.get("visible", True) is not False]
        self.installed = installed
        cats = sorted({m.get("category") or "other" for m in self.mods})
        cur = self.cat.currentData()
        self.cat.blockSignals(True)
        self.cat.clear()
        self.cat.addItem("Все категории", None)
        for c in cats:
            self.cat.addItem(self.CATEGORIES.get(c, c.capitalize()), c)
        i = self.cat.findData(cur)
        self.cat.setCurrentIndex(max(i, 0))
        self.cat.blockSignals(False)
        self.status.setText(f"Не удалось загрузить моды: {error}" if error else "")
        self.status.setVisible(bool(error))
        self._fill()

    def set_installed(self, installed):
        self.installed = installed
        self._fill()

    def _fill(self):
        cur = self.list.currentItem().data(DATA)["id"] if self.list.currentItem() else None
        self.list.clear()
        q = self.search.text().lower()
        cat = self.cat.currentData()
        for m in self.mods:
            inst = str(m["id"]) in self.installed
            if q and q not in (m.get("title", "") + " " + m.get("author", "")).lower():
                continue
            if cat and (m.get("category") or "other") != cat:
                continue
            if self.only_inst.isChecked() and not inst:
                continue
            mark = ""
            if inst:
                iv = self.installed[str(m["id"])].get("version")
                mark = "  ✔ установлен" if iv == m.get("version") else "  ⟳ есть обновление"
            top = "🔥 " if m.get("top") else ""
            it = QListWidgetItem(f"{top}{m.get('title')}{mark}\n{m.get('shortDescription') or ''}")
            it.setData(DATA, m)
            self.list.addItem(it)
            self.images.get(m.get("image"), lambda pm, it=it: it.setIcon(QIcon(rounded(pm, 48, 8))))
            if m["id"] == cur:
                self.list.setCurrentItem(it)

    def _show(self, it, _prev=None):
        if not it:
            self.panel.hide()
            return
        m = it.data(DATA)
        self.panel.show()
        self.title.setText(m.get("title", ""))
        deps = [d for d in (m.get("dependencyModsIds") or [])]
        dep_names = [next((x["title"] for x in self.mods if x["id"] == d), f"#{d}") for d in deps]
        meta = [f"Автор: {m.get('author', '—')}", f"Версия: {m.get('version', '—')}",
                f"Скачиваний: {m.get('totalDownloads', 0)}"]
        if dep_names:
            meta.append("Требует: " + ", ".join(dep_names))
        self.meta.setText(" · ".join(meta))
        desc = (m.get("description") or "").replace("\r", "")
        if m.get("changes"):
            desc += f"\n\nИзменения: {m['changes']}"
        self.desc.setPlainText(desc)
        self.image.clear()
        self.images.get(m.get("image"), lambda pm: self.list.currentItem() is it and self.image.setPixmap(
            pm.scaled(360, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
        self._update_action(m)

    def _update_action(self, m):
        inst = self.installed.get(str(m["id"]))
        if m["id"] in self.busy:
            self.action.setText("Подождите...")
            self.action.setEnabled(False)
            return
        self.action.setEnabled(True)
        if not inst:
            self.action.setText("Установить")
        elif inst.get("version") != m.get("version"):
            self.action.setText("Обновить")
        else:
            self.action.setText("Удалить")

    def _action(self):
        it = self.list.currentItem()
        if not it:
            return
        m = it.data(DATA)
        inst = self.installed.get(str(m["id"]))
        if inst and inst.get("version") == m.get("version"):
            self.uninstall.emit(m)
        else:
            self.install.emit(m)

    def set_busy(self, mod_id, busy):
        (self.busy.add if busy else self.busy.discard)(mod_id)
        it = self.list.currentItem()
        if it and it.data(DATA)["id"] == mod_id:
            self._update_action(it.data(DATA))


class GameSettingsTab(QScrollArea):
    changed = Signal()
    choose_dir = Signal()
    verify = Signal()
    repair = Signal()

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.inner = QWidget()
        self.setWidget(self.inner)
        self.lay = QVBoxLayout(self.inner)
        self.gs = None

    def build(self, cfg, game):
        self.gs = core.game_settings(cfg, game)
        while self.lay.count():
            it = self.lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
            elif it.layout():
                QWidget().setLayout(it.layout())

        form = QFormLayout()
        self.memory = QComboBox()
        for v in core.MEMORY_VALUES:
            self.memory.addItem(f"{v} МБ", v)
        self.memory.setCurrentIndex(max(self.memory.findData(self.gs["memory"]), 0))
        self.memory.currentIndexChanged.connect(self._save)
        form.addRow("Память для игры:", self.memory)

        dir_row = QHBoxLayout()
        self.dir = QLineEdit(str(core.game_dir(cfg, game)))
        self.dir.setReadOnly(True)
        b = QPushButton("Изменить...")
        b.clicked.connect(self.choose_dir)
        o = QPushButton("Открыть")
        o.clicked.connect(lambda: open_path(core.game_dir(cfg, game)))
        dir_row.addWidget(self.dir, 1)
        dir_row.addWidget(b)
        dir_row.addWidget(o)
        form.addRow("Папка игры:", dir_row)
        self.lay.addLayout(form)

        box = QFrame(objectName="panel")
        grid = QGridLayout(box)
        self.checks = {}
        for i, (oid, _) in enumerate(GAMES[game]["options"].items()):
            label, desc = OPTION_INFO[oid]
            cb = QCheckBox(label)
            cb.setChecked(bool(self.gs["options"].get(oid)))
            cb.toggled.connect(self._save)
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(4, 4, 4, 8)
            v.addWidget(cb)
            v.addWidget(muted(desc))
            grid.addWidget(w, i // 2, i % 2)
            self.checks[oid] = cb
        self.lay.addWidget(box)

        self.pw_row = QWidget()
        pr = QHBoxLayout(self.pw_row)
        pr.setContentsMargins(0, 0, 0, 0)
        pr.addWidget(QLabel("Пароль тестовой ветки:"))
        self.pw = QLineEdit(self.gs.get("password", ""))
        self.pw.setEchoMode(QLineEdit.Password)
        self.pw.editingFinished.connect(self._save)
        pr.addWidget(self.pw, 1)
        self.lay.addWidget(self.pw_row)
        self.pw_row.setVisible("testBranch" in self.checks and self.checks["testBranch"].isChecked())

        actions = QHBoxLayout()
        v = QPushButton("Проверить файлы")
        v.clicked.connect(self.verify)
        r = QPushButton("Починить игру...")
        r.clicked.connect(self.repair)
        actions.addWidget(v)
        actions.addWidget(r)
        actions.addStretch()
        self.lay.addLayout(actions)
        self.lay.addStretch()

    def _save(self, *_):
        if not self.gs:
            return
        old_ng = self.gs["options"].get("newGraphics")
        self.gs["memory"] = self.memory.currentData()
        for oid, cb in self.checks.items():
            self.gs["options"][oid] = cb.isChecked()
        self.gs["password"] = self.pw.text()
        self.pw_row.setVisible("testBranch" in self.checks and self.checks["testBranch"].isChecked())
        self.changed.emit()
        if old_ng != self.gs["options"].get("newGraphics"):
            self.verify.emit()   # другой набор текстур — нужно докачать файлы


class LauncherSettings(QDialog):
    def __init__(self, cfg, parent, run_setup):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Настройки лаунчера")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        form = QFormLayout()

        def path_row(value, directory=True):
            row = QHBoxLayout()
            e = QLineEdit(value)
            b = QPushButton("...")

            def pick():
                p = (QFileDialog.getExistingDirectory(self, "", e.text()) if directory
                     else QFileDialog.getOpenFileName(self, "", e.text())[0])
                if p:
                    e.setText(p)
            b.clicked.connect(pick)
            row.addWidget(e, 1)
            row.addWidget(b)
            return row, e

        r, self.root = path_row(cfg["games_root"])
        form.addRow("Папка для игр:", r)
        r, self.wine = path_row(cfg["wine"], directory=False)
        form.addRow("Wine:", r)
        r, self.prefix = path_row(cfg["prefix"])
        form.addRow("Префикс Wine:", r)
        self.threads = QSpinBox()
        self.threads.setRange(1, 16)
        self.threads.setValue(int(cfg.get("threads", 4)))
        form.addRow("Потоков загрузки:", self.threads)
        self.vsync = QCheckBox("Вертикальная синхронизация (VSync)")
        self.vsync.setChecked(cfg.get("vsync", False))
        self.esync = QCheckBox("Esync/Fsync (быстрее, если поддерживается)")
        self.esync.setChecked(cfg.get("esync", True))
        self.hide = QCheckBox("Сворачивать лаунчер в трей во время игры")
        self.hide.setChecked(cfg.get("minimize_on_play", True))
        for w in (self.vsync, self.esync, self.hide):
            form.addRow("", w)
        lay.addLayout(form)

        tools = QHBoxLayout()
        b1 = QPushButton("Установить компоненты Wine")
        b1.setToolTip("DXVK, DirectX 9, Visual C++ 2010/2013/2022, шрифты — аналог «Установить драйвера»")
        b1.clicked.connect(lambda: (self.accept(), run_setup()))
        b2 = QPushButton("winecfg")
        b2.clicked.connect(lambda: core.Wine(cfg).winecfg())
        b3 = QPushButton("Журнал Wine")
        b3.clicked.connect(lambda: core.LOG_FILE.exists() and open_path(core.LOG_FILE))
        b4 = QPushButton("Закрыть игру")
        b4.setToolTip("Принудительно завершить все процессы Wine этого лаунчера")
        b4.clicked.connect(lambda: core.Wine(cfg).kill())
        b5 = QPushButton("Иконка из .exe...")
        b5.setToolTip("Взять иконку из официального лаунчера Arizona (установщика или Arizona Games Launcher.exe)")
        b5.clicked.connect(lambda: (self.accept(), parent.pick_icon_exe()))
        for b in (b1, b2, b3, b4, b5):
            tools.addWidget(b)
        lay.addLayout(tools)
        lay.addWidget(muted(f"Неофициальный лаунчер, версия {core.APP_VERSION}. "
                            "Не связан с администрацией проекта."))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def apply(self):
        self.cfg["games_root"] = self.root.text().strip() or self.cfg["games_root"]
        self.cfg["wine"] = self.wine.text().strip() or "wine"
        self.cfg["prefix"] = self.prefix.text().strip() or self.cfg["prefix"]
        self.cfg["threads"] = self.threads.value()
        self.cfg["vsync"] = self.vsync.isChecked()
        self.cfg["esync"] = self.esync.isChecked()
        self.cfg["minimize_on_play"] = self.hide.isChecked()


# ---------------------------------------------------------------- главное окно

class State:
    UNKNOWN, CHECKING, NOT_INSTALLED, NEED_UPDATE, DOWNLOADING, READY, RUNNING, SETUP = range(8)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = core.load_config()
        if self.cfg.get("game") not in GAMES:
            self.cfg["game"] = "arizona"
        self.bridge = Bridge()
        self.images = Images(self.bridge)
        self.servers_data = {}
        self.projects = []
        self.cdn_idx = None
        self.updater = None
        self.state = State.UNKNOWN
        self.pending = []          # что скачать
        self.after_task = None     # что сделать после проверки/загрузки (запуск игры)
        self.speed_mark = (time.monotonic(), 0)
        self.dl_done = 0

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1200, 760)
        self._build()
        self._connect()
        self._game_changed(initial=True)
        self._load_servers()
        POOL.submit(self._bg_projects)
        POOL.submit(lambda: self.bridge.cdn.emit(core.cdn_indexes()))
        POOL.submit(lambda: install_original_icon(self.cfg) and self.bridge.icon_ready.emit())

    # ---- интерфейс
    def _build(self):
        central = QWidget(objectName="central")
        self.setCentralWidget(central)
        v = QVBoxLayout(central)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        top = QHBoxLayout()
        top.setContentsMargins(16, 12, 16, 4)
        self.game_box = QComboBox()
        for gid, g in GAMES.items():
            self.game_box.addItem(g["title"], gid)
        self.game_box.setCurrentIndex(self.game_box.findData(self.cfg["game"]))
        self.game_box.setMinimumWidth(180)
        f = self.game_box.font()
        f.setBold(True)
        self.game_box.setFont(f)
        top.addWidget(self.game_box)
        top.addStretch()
        top.addWidget(QLabel("Ник:"))
        self.nick = QLineEdit(placeholderText="Nick_Name")
        self.nick.setValidator(QRegularExpressionValidator(QRegularExpression(r"[A-Za-z0-9_]{0,20}")))
        self.nick.setFixedWidth(220)
        top.addWidget(self.nick)
        self.settings_btn = QToolButton(text="⚙")
        self.settings_btn.setToolTip("Настройки лаунчера")
        top.addWidget(self.settings_btn)
        v.addLayout(top)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.servers_tab = ServersTab(self.images)
        self.news_tab = NewsTab(self.images)
        self.mods_tab = ModsTab(self.images)
        self.game_tab = GameSettingsTab()
        self.tabs.addTab(self.servers_tab, "Серверы")
        self.tabs.addTab(self.news_tab, "Новости")
        self.tabs.addTab(self.mods_tab, "Моды")
        self.tabs.addTab(self.game_tab, "Настройки игры")
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(12, 0, 12, 8)
        wl.addWidget(self.tabs)
        v.addWidget(wrap, 1)

        bottom = QFrame(objectName="bottom")
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(18, 12, 18, 12)
        info = QVBoxLayout()
        self.status = QLabel("Загрузка...")
        f = self.status.font()
        f.setBold(True)
        self.status.setFont(f)
        self.detail = muted()
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setFixedHeight(8)
        info.addWidget(self.status)
        info.addWidget(self.bar)
        info.addWidget(self.detail)
        bl.addLayout(info, 1)
        self.more = QToolButton(text="⋯")
        self.more.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(self.more)
        m.addAction("Проверить файлы", lambda: self.start_check(full=True))
        m.addAction("Починить игру...", self.ask_repair)
        m.addSeparator()
        m.addAction("Установить компоненты Wine", self.run_setup)
        m.addAction("Открыть папку игры", lambda: open_path(core.game_dir(self.cfg, self.game)))
        m.addAction("Журнал Wine", lambda: core.LOG_FILE.exists() and open_path(core.LOG_FILE))
        self.more.setMenu(m)
        bl.addWidget(self.more)
        self.play = QPushButton("ИГРАТЬ", objectName="play")
        bl.addWidget(self.play)
        v.addWidget(bottom)

        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        tm = QMenu()
        tm.addAction("Открыть", self._show_window)
        tm.addAction("Выход", QApplication.quit)
        self.tray.setContextMenu(tm)
        self.tray.activated.connect(lambda r: r == QSystemTrayIcon.Trigger and self._show_window())
        self.tray.setToolTip(APP_NAME)

        self.speed_timer = QTimer(self, interval=1000)
        self.speed_timer.timeout.connect(self._tick_speed)

    def _connect(self):
        b = self.bridge
        b.servers.connect(self._on_servers)
        b.projects.connect(self._on_projects)
        b.cdn.connect(lambda idx: setattr(self, "cdn_idx", idx))
        b.progress.connect(self._on_progress)
        b.task_done.connect(self._on_task_done)
        b.mods.connect(self._on_mods)
        b.mod_done.connect(self._on_mod_done)
        b.mod_progress.connect(lambda t: (self.mods_tab.status.setText(t), self.mods_tab.status.show()))
        b.game_exit.connect(self._on_game_exit)
        b.icon_ready.connect(self._apply_icon)
        b.log.connect(lambda s: print(s, file=sys.stderr))
        self.game_box.currentIndexChanged.connect(lambda _: self._game_changed())
        self.nick.editingFinished.connect(self._save_nick)
        self.settings_btn.clicked.connect(self.open_settings)
        self.play.clicked.connect(self.on_play)
        self.servers_tab.play_requested.connect(self.play_on)
        self.servers_tab.refresh_btn.clicked.connect(self._load_servers)
        self.servers_tab.table.selectionModel().currentRowChanged.connect(self._remember_server)
        self.mods_tab.install.connect(self.install_mod)
        self.mods_tab.uninstall.connect(self.uninstall_mod)
        self.mods_tab.reload.connect(self._load_mods)
        self.game_tab.changed.connect(lambda: core.save_config(self.cfg))
        self.game_tab.verify.connect(lambda: self.start_check())
        self.game_tab.repair.connect(self.ask_repair)
        self.game_tab.choose_dir.connect(self.choose_game_dir)
        QTimer(self, interval=60000, timeout=self._load_servers).start()

    @property
    def game(self):
        return self.cfg["game"]

    @property
    def gs(self):
        return core.game_settings(self.cfg, self.game)

    def busy(self):
        return self.state in (State.CHECKING, State.DOWNLOADING, State.SETUP)

    # ---- смена игры
    def _game_changed(self, initial=False):
        gid = self.game_box.currentData()
        if not initial and self.busy():
            self.game_box.blockSignals(True)
            self.game_box.setCurrentIndex(self.game_box.findData(self.game))
            self.game_box.blockSignals(False)
            QMessageBox.information(self, APP_NAME, "Дождитесь окончания текущей операции.")
            return
        self.cfg["game"] = gid
        core.save_config(self.cfg)
        self.nick.setText(self.gs["nick"])
        self.game_tab.build(self.cfg, gid)
        self.news_tab.set_game(gid, self.projects)
        self.mods_tab.set_mods([], [], {})
        self.mods_tab.status.setText("Загрузка списка модов...")
        self.mods_tab.status.show()
        self._load_mods()
        if self.servers_data:
            self._on_servers(self.servers_data, "")
        self.start_check()

    def _save_nick(self):
        self.gs["nick"] = self.nick.text().strip()
        core.save_config(self.cfg)

    def _remember_server(self, *_):
        s = self.servers_tab.current()
        if s:
            self.gs["last_server"] = s.get("number")
            core.save_config(self.cfg)

    # ---- данные из сети
    def _load_servers(self):
        def job():
            try:
                self.bridge.servers.emit(core.fetch_servers(), "")
            except Exception as e:  # noqa: BLE001
                self.bridge.servers.emit(None, str(e))
        POOL.submit(job)

    def _on_servers(self, data, err):
        if data is None:
            if not self.servers_data:
                self.detail.setText(f"Не удалось загрузить список серверов: {err}")
            return
        self.servers_data = data
        cur = self.servers_tab.current()
        num = cur.get("number") if cur else self.gs.get("last_server")
        self.servers_tab.set_servers(data.get(self.game, []), num)

    def _bg_projects(self):
        try:
            self.bridge.projects.emit(core.fetch_projects())
        except Exception:  # noqa: BLE001
            self.bridge.projects.emit([])

    def _on_projects(self, projects):
        self.projects = projects
        self.news_tab.set_game(self.game, projects)

    def _load_mods(self):
        game = self.game

        def job():
            try:
                top, mods = core.fetch_mods(game)
                self.bridge.mods.emit(top, (game, mods), "")
            except Exception as e:  # noqa: BLE001
                self.bridge.mods.emit([], (game, []), str(e))
        POOL.submit(job)

    def _on_mods(self, top, payload, err):
        game, mods = payload
        if game == self.game:
            self.mods_tab.set_mods(top, mods, self.gs["mods"], err)

    # ---- статус и прогресс
    def set_state(self, st, status=None, detail=""):
        self.state = st
        labels = {State.UNKNOWN: "ИГРАТЬ", State.NOT_INSTALLED: "УСТАНОВИТЬ", State.NEED_UPDATE: "ОБНОВИТЬ",
                  State.READY: "ИГРАТЬ", State.RUNNING: "В ИГРЕ", State.CHECKING: "ОТМЕНА",
                  State.DOWNLOADING: "ОТМЕНА", State.SETUP: "ПОДОЖДИТЕ"}
        self.play.setText(labels[st])
        self.play.setProperty("cancel", st in (State.CHECKING, State.DOWNLOADING))
        self.play.style().unpolish(self.play)
        self.play.style().polish(self.play)
        self.play.setEnabled(st not in (State.RUNNING, State.SETUP))
        self.servers_tab.play_here.setEnabled(st not in (State.RUNNING, State.SETUP, State.CHECKING,
                                                         State.DOWNLOADING))
        if status is not None:
            self.status.setText(status)
        self.detail.setText(detail)
        if st == State.READY:
            self.bar.setValue(1000)
        elif st in (State.NOT_INSTALLED, State.NEED_UPDATE, State.UNKNOWN):
            self.bar.setValue(0)
        if st == State.DOWNLOADING:
            self.speed_timer.start()
        else:
            self.speed_timer.stop()

    def _on_progress(self, stage, done, total, text):
        if total > 0:
            self.bar.setValue(int(1000 * done / total))
        if stage == "download":
            self.dl_done = done
            self.status.setText(f"{text} {human_size(done)} из {human_size(total)}")
        elif stage == "verify":
            self.status.setText(f"{text} {int(done)} из {int(total)}")
        else:
            self.status.setText(text)

    def _tick_speed(self):
        t, b = self.speed_mark
        now = time.monotonic()
        speed = (self.dl_done - b) / max(now - t, 0.001)
        self.speed_mark = (now, self.dl_done)
        total = self.updater.total_bytes if self.updater else 0
        left = (total - self.dl_done) / speed if speed > 0 else 0
        eta = time.strftime("%H:%M:%S", time.gmtime(left)) if speed > 0 else "—"
        self.detail.setText(f"Скорость: {human_size(speed)}/с · осталось ≈ {eta}")

    # ---- проверка и загрузка
    def start_check(self, full=False, repair=False, keep_user=True, then=None):
        if self.busy() or self.state == State.RUNNING:
            return
        root = core.game_dir(self.cfg, self.game)
        installed = (root / "gta_sa.exe").exists()
        self.after_task = then
        self.set_state(State.CHECKING, "Проверка файлов...")
        self.bar.setValue(0)
        self.updater = core.Updater(self.cfg, self.game,
                                    progress=lambda *a: self.bridge.progress.emit(*a),
                                    log=lambda s: self.bridge.log.emit(s))
        up = self.updater

        def job():
            try:
                self.bridge.progress.emit("info", 0, 0, "Получение списка файлов...")
                manifest = up.fetch_manifest()
                if not installed and not repair:
                    # новая установка: не тратим время на проверку, просто считаем, что качать
                    self.bridge.progress.emit("info", 0, 0, "Подготовка установки...")
                items = up.plan(manifest, full=full or repair, repair=repair, keep_user=keep_user)
                self.bridge.task_done.emit("check", (items, installed), "")
            except core.Cancelled:
                self.bridge.task_done.emit("check", None, "cancel")
            except Exception as e:  # noqa: BLE001
                self.bridge.task_done.emit("check", None, str(e))
        threading.Thread(target=job, daemon=True).start()

    def start_download(self):
        up = self.updater
        items = self.pending
        self.set_state(State.DOWNLOADING, "Загрузка файлов...")
        self.speed_mark = (time.monotonic(), 0)
        self.dl_done = 0

        def job():
            try:
                up.download(items)
                self.bridge.task_done.emit("download", None, "")
            except core.Cancelled:
                self.bridge.task_done.emit("download", None, "cancel")
            except Exception as e:  # noqa: BLE001
                self.bridge.task_done.emit("download", None, str(e))
        threading.Thread(target=job, daemon=True).start()

    def _on_task_done(self, kind, result, err):
        then, self.after_task = self.after_task, None
        self.bar.setRange(0, 1000)
        if err == "cancel":
            self.set_state(State.NEED_UPDATE, "Отменено", "Нажмите «Обновить», чтобы продолжить.")
            return
        if err:
            if kind == "setup":
                self.set_state(State.UNKNOWN, "Ошибка настройки Wine", err)
            else:
                self.set_state(State.NEED_UPDATE, "Ошибка", err)
            QMessageBox.warning(self, APP_NAME, err)
            return
        if kind == "check":
            items, installed = result
            self.pending = items
            files = [i for i in items if not i.is_dir]
            size = sum(i.size for i in files)
            if not files:
                if items:
                    self.updater.download(items)   # только создать папки
                self.set_state(State.READY, "Готово к игре")
                if then:
                    then()
                return
            if not installed:
                self.set_state(State.NOT_INSTALLED, "Игра не установлена",
                               f"Нужно скачать {human_size(size)} ({len(files)} файлов) в "
                               f"{core.game_dir(self.cfg, self.game)}")
            else:
                self.set_state(State.NEED_UPDATE, "Требуется обновить",
                               f"{len(files)} файлов, {human_size(size)}")
                if then:   # перед запуском — сразу качаем
                    self.after_task = then
                    self.start_download()
        elif kind == "download":
            self.pending = []
            self.set_state(State.READY, "Готово к игре")
            self._notify("Загрузка завершена", "Игра готова к запуску.")
            if then:
                then()
        elif kind == "setup":
            self.set_state(State.UNKNOWN, "Wine настроен")
            self.start_check(then=then)

    # ---- кнопка «Играть»
    def on_play(self):
        if self.state in (State.CHECKING, State.DOWNLOADING):
            if self.updater:
                self.updater.cancel.set()
            return
        if self.state == State.NOT_INSTALLED:
            self.confirm_install()
            return
        if self.state == State.NEED_UPDATE and self.pending:
            self.start_download()
            return
        s = self.servers_tab.current()
        if not s:
            QMessageBox.information(self, APP_NAME, "Выберите сервер в списке.")
            return
        self.play_on(s)

    def confirm_install(self):
        files = [i for i in self.pending if not i.is_dir]
        size = sum(i.size for i in files)
        root = core.game_dir(self.cfg, self.game)
        root.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(root).free
        box = QMessageBox(self)
        box.setWindowTitle("Установка игры")
        box.setText(f"Будет скачано {human_size(size)}.\n\nПапка: {root}\nСвободно на диске: {human_size(free)}")
        box.setInformativeText("Папку можно изменить во вкладке «Настройки игры».")
        box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        box.button(QMessageBox.Ok).setText("Скачать")
        if box.exec() == QMessageBox.Ok:
            self.start_download()

    def play_on(self, server):
        nick = self.nick.text().strip()
        self._save_nick()
        if not QRegularExpression(core.NICK_RE).match(nick).hasMatch():
            QMessageBox.warning(self, APP_NAME, "Введите ник: 3–20 символов, латиница, цифры и «_».\n"
                                               "Например: Ivan_Petrov")
            self.nick.setFocus()
            return
        if self.state == State.RUNNING:
            return
        if self.busy():
            return
        if self.state == State.NOT_INSTALLED:
            self.confirm_install()
            return
        wine = core.Wine(self.cfg)
        if not shutil.which(wine.wine()) and not Path(wine.wine()).exists():
            QMessageBox.warning(self, APP_NAME, "Wine не найден. Установите wine и winetricks.")
            return
        go = lambda: self._launch(server)  # noqa: E731
        if not wine.components_ready():
            r = QMessageBox.question(
                self, APP_NAME, "Перед первым запуском нужно подготовить Wine: DXVK, DirectX 9, "
                                "Visual C++ и шрифты (аналог «Установить драйвера»).\n\n"
                                "Это займёт несколько минут. Начать?")
            if r != QMessageBox.Yes:
                return
            self.run_setup(then=lambda: self._launch(server))
            return
        if self.gs["options"].get("autoClean"):
            self.start_check(repair=True, keep_user=True, then=go)
        else:
            # как в оригинале: быстрая проверка перед каждым запуском
            self.start_check(then=go)

    def _launch(self, server):
        try:
            core.launch(self.cfg, self.game, server, self.cdn_idx)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, APP_NAME, f"Не удалось запустить игру: {e}")
            return
        self.launch_time = time.monotonic()
        self.set_state(State.RUNNING, f"Игра запущена — {server['name']}", "Лаунчер покажется после выхода из игры.")
        if self.cfg.get("minimize_on_play", True):
            self.tray.show()
            QTimer.singleShot(1500, self.hide)

        def wait():
            time.sleep(3)
            core.wait_game_exit(self.cfg)
            self.bridge.game_exit.emit()
        threading.Thread(target=wait, daemon=True).start()

    def _on_game_exit(self):
        self._show_window()
        self.set_state(State.READY, "Готово к игре")
        quick, asi = core.crash_info(self.cfg, self.game)
        if time.monotonic() - getattr(self, "launch_time", 0) < 15 and not quick:
            self.detail.setText(f"Игра закрылась сразу после запуска. Подробности: {core.LOG_FILE}")
        if quick or asi:
            r = QMessageBox.question(self, APP_NAME, "Похоже, игра аварийно завершилась. "
                                                     "Проверить и починить файлы игры?")
            if r == QMessageBox.Yes:
                self.start_check(full=True)

    def _show_window(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def _notify(self, title, text):
        if self.isHidden() and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
            self.tray.showMessage(title, text)

    # ---- Wine
    def run_setup(self, then=None):
        if self.busy():
            return
        self.after_task = then
        self.set_state(State.SETUP, "Настройка Wine...", "Это займёт несколько минут")
        self.bar.setRange(0, 0)

        def job():
            try:
                core.Wine(self.cfg).setup(log=lambda s: self.bridge.progress.emit("info", 0, 0, s[:120]))
                self.bridge.task_done.emit("setup", None, "")
            except Exception as e:  # noqa: BLE001
                self.bridge.task_done.emit("setup", None, str(e))
        threading.Thread(target=job, daemon=True).start()

    # ---- починка
    def ask_repair(self):
        if self.busy() or self.state == State.RUNNING:
            return
        box = QMessageBox(self)
        box.setWindowTitle("Починить игру")
        box.setText("Все файлы игры будут проверены по контрольным суммам, повреждённые — скачаны заново, "
                    "лишние файлы — удалены.")
        keep = QCheckBox("Сохранить настройки, моды, голосовой чат и кэш")
        keep.setChecked(True)
        box.setCheckBox(keep)
        box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        box.button(QMessageBox.Ok).setText("Починить")
        if box.exec() != QMessageBox.Ok:
            return
        if not keep.isChecked():
            self.gs["mods"].clear()
            core.save_config(self.cfg)
            self.mods_tab.set_installed(self.gs["mods"])
            core.clear_cef_cache(self.cfg)
        # then — пустое действие: после проверки повреждённые файлы сразу докачиваются
        self.start_check(repair=True, keep_user=keep.isChecked(), then=lambda: None)

    def choose_game_dir(self):
        if self.busy():
            return
        d = QFileDialog.getExistingDirectory(self, "Папка игры", str(core.game_dir(self.cfg, self.game)))
        if not d:
            return
        self.gs["game_dir"] = d
        core.save_config(self.cfg)
        self.game_tab.build(self.cfg, self.game)
        self.start_check()

    # ---- моды
    def install_mod(self, mod):
        if not (core.game_dir(self.cfg, self.game) / "gta_sa.exe").exists():
            QMessageBox.information(self, APP_NAME, "Сначала установите игру.")
            return
        if self.state == State.RUNNING:
            QMessageBox.information(self, APP_NAME, "Закройте игру перед установкой модов.")
            return
        game = self.game
        all_mods = {m["id"]: m for m in self.mods_tab.mods}
        order, seen = [], set()

        def add(m):   # сначала зависимости
            if m["id"] in seen:
                return
            seen.add(m["id"])
            for d in m.get("dependencyModsIds") or []:
                if d in all_mods and str(d) not in self.gs["mods"]:
                    add(all_mods[d])
            order.append(m)
        add(mod)
        conflicts = [all_mods[c]["title"] for m in order for c in (m.get("conflictModsIds") or [])
                     if str(c) in self.gs["mods"] and c in all_mods]
        if conflicts and QMessageBox.question(
                self, APP_NAME, f"«{mod['title']}» несовместим с установленными модами: "
                                f"{', '.join(conflicts)}.\n\nВсё равно установить?") != QMessageBox.Yes:
            return
        self.mods_tab.set_busy(mod["id"], True)

        def job():
            try:
                for m in order:
                    title = m.get("title", "")
                    core.install_mod(self.cfg, game, m, log=lambda s: self.bridge.log.emit(s),
                                     progress=lambda d, t, title=title: self.bridge.mod_progress.emit(
                                         f"Установка «{title}»: {d} из {t} файлов"))
                self.bridge.mod_done.emit(mod["id"], True, "")
            except Exception as e:  # noqa: BLE001
                self.bridge.mod_done.emit(mod["id"], False, str(e))
        POOL.submit(job)

    def uninstall_mod(self, mod):
        if self.state == State.RUNNING:
            QMessageBox.information(self, APP_NAME, "Закройте игру перед удалением модов.")
            return
        core.uninstall_mod(self.cfg, self.game, mod["id"])
        core.save_config(self.cfg)
        self.mods_tab.set_installed(self.gs["mods"])
        self.mods_tab.set_busy(mod["id"], False)
        self.start_check()   # вернуть оригинальные файлы, если мод их заменял

    def _on_mod_done(self, mod_id, ok, err):
        core.save_config(self.cfg)
        self.mods_tab.set_busy(mod_id, False)
        self.mods_tab.set_installed(self.gs["mods"])
        self.mods_tab.status.hide()
        if err:
            QMessageBox.warning(self, APP_NAME, err)

    def _apply_icon(self):
        icon = app_icon()
        self.setWindowIcon(icon)
        QApplication.setWindowIcon(icon)
        self.tray.setIcon(icon)

    def pick_icon_exe(self):
        f, _ = QFileDialog.getOpenFileName(self, "Официальный лаунчер Arizona", str(Path.home()),
                                           "Программы Windows (*.exe)")
        if not f:
            return
        if core.exe_icon_bytes(f) and install_original_icon(self.cfg, f):
            self.cfg["icon_exe"] = f
            core.save_config(self.cfg)
            self._apply_icon()
            QMessageBox.information(self, APP_NAME, "Иконка установлена. В доке она сменится "
                                                    "после перезапуска лаунчера.")
        else:
            QMessageBox.warning(self, APP_NAME, "В этом файле не нашлось иконки.")

    # ---- настройки
    def open_settings(self):
        dlg = LauncherSettings(self.cfg, self, self.run_setup)
        if dlg.exec() == QDialog.Accepted:
            old_root = self.cfg["games_root"]
            dlg.apply()
            core.save_config(self.cfg)
            if old_root != self.cfg["games_root"]:
                self.game_tab.build(self.cfg, self.game)
                self.start_check()

    def closeEvent(self, e):
        self._save_nick()
        if self.updater:
            self.updater.cancel.set()
        core.save_config(self.cfg)
        super().closeEvent(e)
        QApplication.quit()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("arizona-launcher")
    app.setDesktopFileName("arizona-launcher")
    app.setApplicationDisplayName(APP_NAME)
    app.setStyle("Fusion")
    app.setWindowIcon(app_icon())
    app.setStyleSheet(STYLE)
    app.setQuitOnLastWindowClosed(False)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
