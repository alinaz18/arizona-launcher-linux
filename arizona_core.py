"""Движок лаунчера Arizona для Linux (без интерфейса).

Повторяет работу официального лаунчера:
  * список серверов, новости и моды — с api.arizona-five.com / api-samp.arizona-five.com;
  * файлы игры — по манифесту <CDN>/game.json (дерево папок, у файлов size/hash(MD5)/date_change),
    сами файлы лежат в <CDN>/game/<путь>;
  * быстрая проверка: размер + дата изменения, MD5 считается только когда дата не совпала;
  * запуск: gta_sa.exe -c -h IP -p PORT -n Ник -mem ... через Wine.
"""

import hashlib
import json
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

APP_VERSION = "1.1"
REPO = "alinaz18/arizona-launcher-linux"
# официальный лаунчер представляется так; CDN отдаёт файлы и без этого, но так надёжнее
USER_AGENT = "Arizona PC/0.0.144"

XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
XDG_DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
XDG_CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
CONFIG_DIR = XDG_CONFIG / "arizona-launcher"
DATA_DIR = XDG_DATA / "arizona-launcher"
CACHE_DIR = XDG_CACHE / "arizona-launcher"
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_FILE = DATA_DIR / "wine.log"

API = ["https://api.arizona-five.com/", "https://arz-api-reserve.s-amp.com/"]
MODS_API = ["https://api-samp.arizona-five.com/launcher/mods",
            "https://arz-api-samp-reserve.s-amp.com/launcher/mods"]
# для аргумента -cdn: индекс первого рабочего зеркала в каждой группе
PING_GROUPS = [
    ["https://cdn.azresources.cloud", "https://resources.azgames-cdn.ru"],
    ["https://cdn.azsounds.net", "https://azgamesound-cdn.ru"],
    ["https://server-api.arizona.games", "https://server-api.azgames-cdn.ru"],
]
PING_HASH = "5aa4731d5d84e09e2f7e7141e560104f"

# Опции запуска: id -> (подпись, описание)
OPTION_INFO = {
    "wideScreen": ("Широкий экран", "Расширяет угол обзора и адаптирует интерфейс под современные мониторы."),
    "autoLogin": ("Автологин", "Сохраняет пароль и выполняет автоматический вход в аккаунт."),
    "shitPc": ("Слабый ПК", "Отключает эффекты и снижает качество текстур."),
    "oldResolution": ("Устаревшие разрешения", "Отключает 32-bit режим экрана. Включайте, только если без него не работает."),
    "hdrResolution": ("Поддержка HDR", "[BETA] Вывод изображения в HDR. Возможны искажения цветов."),
    "grass": ("Дополнительная растительность", "Повышает детализацию травы и листвы. Может снизить FPS."),
    "newGraphics": ("Новые текстуры", "Современные текстуры растительности, новые модели оружия и другое. "
                    "Меняет набор скачиваемых файлов."),
    "graphics": ("Улучшенная графика", "Улучшенное освещение и небо. Снижает производительность."),
    "autoClean": ("Автоочистка", "Удаляет лишние файлы и модификации из папки игры перед запуском."),
    "preload": ("Предзагрузка", "Загружает модели заранее, снижая нагрузку на диск. Возможны подлагивания."),
    "windowed": ("Запуск в окне", "Игра запускается в окне (размер — из настроек игры)."),
    "authCef": ("Новая авторизация", "Обновлённый вид входа в игру."),
    "testBranch": ("Тестовая ветка", "Подключение к тестовой версии (нужен пароль тестов)."),
}

GAMES = {
    "arizona": {
        "title": "Arizona RP",
        "flag": "-arizona",
        "cdn": {"main": "https://pc.az-ins.com/release", "reserve": "https://arz-pc.react-group.tech/release",
                "mods": "https://pc.az-ins.com/resource/mods",
                "modsReserve": "https://arz-pc.react-group.tech/resource/mods"},
        "options": {"wideScreen": True, "autoLogin": True, "shitPc": False, "oldResolution": False,
                    "hdrResolution": False, "grass": True, "newGraphics": True, "autoClean": False,
                    "preload": False, "windowed": False, "authCef": True, "testBranch": False},
        "links": {"Сайт": "https://arizona-rp.com", "Форум": "https://forum.arizona-rp.com",
                  "Помощь": "https://help.arizona-rp.com", "Магазин": "https://arizona-rp.com/shop",
                  "Telegram": "https://t.me/arizona_rpcom", "VK": "https://vk.com/arizonastaterp",
                  "Discord": "https://discord.gg/arizona-games"},
    },
    "rodina": {
        "title": "Rodina RP",
        "flag": "-rodina",
        "cdn": {"main": "https://pc.rod-ins.com/release", "reserve": "https://rod-pc.react-group.tech/release",
                "mods": "https://pc.rod-ins.com/resource/mods",
                "modsReserve": "https://rod-pc.react-group.tech/resource/mods"},
        "options": {"wideScreen": True, "autoLogin": True, "shitPc": False, "autoClean": False,
                    "preload": False, "windowed": False, "graphics": False},
        "links": {"Сайт": "https://rodina-rp.com", "Форум": "https://forum.rodina-rp.com",
                  "Помощь": "https://help.rodina-rp.com", "Telegram": "https://t.me/rodina_com",
                  "VK": "https://vk.com/rodina_rp", "Discord": "https://discord.gg/rodinagames"},
    },
    "village": {
        "title": "Жизнь в деревне",
        "flag": "-village",
        "cdn": {"main": "https://pc.az-ins.com/village", "reserve": "https://arz-pc.react-group.tech/village",
                "mods": "https://pc.az-ins.com/village/mods",
                "modsReserve": "https://arz-pc.react-group.tech/village/mods"},
        "options": {"wideScreen": True, "autoLogin": True, "shitPc": False, "autoClean": False,
                    "preload": False, "windowed": False, "graphics": False},
        "links": {"Сайт": "https://bone-country.ru", "Форум": "https://forum.bone-country.ru",
                  "Telegram": "https://t.me/arizona_rpcom", "VK": "https://vk.com/bone_country"},
    },
}

MEMORY_VALUES = [1024, 2048, 3072, 4096]
NICK_RE = r"^[A-Za-z0-9_]{3,20}$"
GTA_EXES = ["enb.exe", "gta-sa.exe", "gtasa.exe", "gta_sa.exe"]  # приоритет как в оригинале

# что не трогать при «починке с сохранением настроек» (пути относительно папки игры)
KEEP_ON_REPAIR = ("cef/Cache", "AZVoice/sound_storage", "AZVoice/config.json", "moonloader/config",
                  "moonloader/resources", "mods/mods.img")
KEEP_EXACT = ("AZVoice",)


# ---------------------------------------------------------------- удалённые настройки

# Если Arizona сменит домены, API или потребует новые флаги запуска, это правится в
# remote.json в репозитории — лаунчеры у всех подхватят изменения без переустановки.
REMOTE_URL = f"https://raw.githubusercontent.com/{REPO}/main/remote.json"
REMOTE_CACHE = DATA_DIR / "remote.json"
REMOTE = {"notice": "", "official_version": "", "extra_args": {}}


def _https_list(v):
    return isinstance(v, list) and v and all(isinstance(x, str) and x.startswith("https://") for x in v)


def apply_remote(data):
    """Применить удалённые настройки. Всё непонятное молча пропускается."""
    global USER_AGENT, API, MODS_API, PING_GROUPS
    if not isinstance(data, dict) or data.get("schema") != 1:
        return False
    ua = data.get("user_agent")
    if isinstance(ua, str) and 0 < len(ua) < 100:
        USER_AGENT = ua
    if _https_list(data.get("api")):
        API = data["api"]
    if _https_list(data.get("mods_api")):
        MODS_API = data["mods_api"]
    ping = data.get("ping_groups")
    if isinstance(ping, list) and len(ping) == 3 and all(_https_list(g) for g in ping):
        PING_GROUPS = ping
    for gid, g in (data.get("games") or {}).items():
        if gid not in GAMES or not isinstance(g, dict):
            continue
        cdn = g.get("cdn") or {}
        for k in ("main", "reserve", "mods", "modsReserve"):
            if isinstance(cdn.get(k), str) and cdn[k].startswith("https://"):
                GAMES[gid]["cdn"][k] = cdn[k].rstrip("/")
        extra = g.get("extra_args")
        if isinstance(extra, list) and all(isinstance(a, str) and a.startswith("-") and " " not in a
                                           for a in extra):
            REMOTE["extra_args"][gid] = extra
    REMOTE["notice"] = data.get("notice") if isinstance(data.get("notice"), str) else ""
    REMOTE["official_version"] = str(data.get("official_version") or "")
    REMOTE["min_version"] = str(data.get("min_launcher_version") or "")
    return True


def load_remote_cached():
    try:
        return apply_remote(json.loads(REMOTE_CACHE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return False


def refresh_remote():
    """Скачать свежий remote.json из репозитория и применить (в фоне при старте)."""
    try:
        data = json.loads(http_get(REMOTE_URL, timeout=8))
    except Exception:  # noqa: BLE001
        return False
    if not apply_remote(data):
        return False
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REMOTE_CACHE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return True


def version_tuple(v):
    return tuple(int(x) for x in "".join(c for c in v if c.isdigit() or c == ".").split(".") if x)


def latest_release():
    """(версия, ссылка) последнего релиза лаунчера на GitHub или None."""
    try:
        d = json.loads(http_get(f"https://api.github.com/repos/{REPO}/releases/latest", timeout=8))
        return d["tag_name"].lstrip("v"), d["html_url"]
    except Exception:  # noqa: BLE001
        return None


def default_config():
    return {
        "game": "arizona",
        "games_root": str(Path.home() / "Games" / "arizona-launcher"),
        "wine": "wine",
        "prefix": str(DATA_DIR / "prefix"),
        "vsync": False,
        "esync": True,
        "threads": 4,
        "minimize_on_play": True,
        "opacity": 100,          # непрозрачность фона окна, %
        "blur": 0,               # размытие фона в KDE (0 — выкл., 1–15 — сила)
        "fingerprint": "",
        "games": {},   # gameId -> {nick, memory, password, options, last_server, game_dir, mods}
    }


def load_config():
    cfg = default_config()
    try:
        cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    if not cfg.get("fingerprint"):
        cfg["fingerprint"] = machine_fingerprint()
    return cfg


def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_FILE)


def game_settings(cfg, game):
    """Настройки конкретной игры с подставленными значениями по умолчанию."""
    g = cfg["games"].setdefault(game, {})
    g.setdefault("nick", "")
    g.setdefault("memory", 2048)
    g.setdefault("password", "")
    g.setdefault("last_server", None)
    g.setdefault("mods", {})
    opts = g.setdefault("options", {})
    for k, v in GAMES[game]["options"].items():
        opts.setdefault(k, v)
    return g


def game_dir(cfg, game):
    custom = cfg["games"].get(game, {}).get("game_dir")
    return Path(custom) if custom else Path(cfg["games_root"]) / game


def machine_fingerprint():
    # как node-machine-id: sha256 от идентификатора машины
    for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            mid = Path(p).read_text().strip()
            if mid:
                return hashlib.sha256(mid.encode()).hexdigest()
        except OSError:
            pass
    return hashlib.sha256(os.urandom(32)).hexdigest()


# ---------------------------------------------------------------- HTTP

def http_get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


class Http:
    """HTTP с повторным использованием соединений (keep-alive) — по одному на поток и хост.

    CDN отвечает 302 на зеркало (pc.az-ins.com → pc2.az-ins.com); перенаправление хоста
    запоминается, чтобы не платить за лишний запрос и TLS-рукопожатие на каждый файл.
    """
    _local = threading.local()
    _redirects = {}

    @classmethod
    def _conn(cls, scheme, host):
        conns = cls._local.__dict__.setdefault("conns", {})
        key = (scheme, host)
        if key not in conns:
            import http.client
            klass = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
            conns[key] = klass(host, timeout=30)
        return conns[key]

    @classmethod
    def _drop(cls, scheme, host):
        c = cls._local.__dict__.get("conns", {}).pop((scheme, host), None)
        if c:
            c.close()

    @classmethod
    def open(cls, url):
        """Вернуть объект ответа (с .read()) для GET url. Ответ нужно дочитать до конца."""
        for _ in range(5):
            u = urllib.parse.urlsplit(url)
            host = cls._redirects.get((u.scheme, u.netloc), (u.scheme, u.netloc))
            scheme, netloc = host
            path = u.path + (f"?{u.query}" if u.query else "")
            for retry in (0, 1):
                conn = cls._conn(scheme, netloc)
                try:
                    conn.request("GET", path, headers={"User-Agent": USER_AGENT})
                    r = conn.getresponse()
                    break
                except (OSError, Exception) as e:  # noqa: BLE001 — разорванное keep-alive соединение
                    cls._drop(scheme, netloc)
                    if retry:
                        raise IOError(str(e)) from e
            if r.status in (301, 302, 303, 307, 308):
                r.read()
                loc = urllib.parse.urlsplit(urllib.parse.urljoin(f"{scheme}://{netloc}{path}",
                                                                 r.getheader("Location", "")))
                if loc.path == u.path:
                    cls._redirects[(u.scheme, u.netloc)] = (loc.scheme, loc.netloc)
                url = urllib.parse.urlunsplit(loc)
                continue
            if r.status != 200:
                r.read()
                raise IOError(f"HTTP {r.status} для {url}")
            return r
        raise IOError(f"слишком много перенаправлений: {url}")

    @classmethod
    def get(cls, url):
        return cls.open(url).read()


def http_json(url, timeout=15):
    return json.loads(http_get(url, timeout))


def api_json(path):
    """Основной API, при ошибке — резервный."""
    err = None
    for base in API:
        try:
            return http_json(base + path)
        except Exception as e:  # noqa: BLE001
            err = e
    raise err


def mods_api_json(path):
    err = None
    for base in MODS_API:
        try:
            return http_json(base + path), base
        except Exception as e:  # noqa: BLE001
            err = e
    raise err


def fetch_servers():
    return api_json("launcher/servers")


def fetch_projects():
    return api_json("launcher/projects")


def cdn_indexes():
    """Аргумент -cdn: для каждой группы зеркал — номер первого отвечающего правильно."""
    def check(urls):
        for i, u in enumerate(urls):
            try:
                if json.loads(http_get(u + "/ping.json", timeout=5)).get("hash") == PING_HASH:
                    return i
            except urllib.error.HTTPError as e:
                if e.code == 403 and len(urls) > 1:
                    return 1
            except Exception:  # noqa: BLE001
                pass
        return 0
    with ThreadPoolExecutor(3) as ex:
        return list(ex.map(check, PING_GROUPS))


def quote_path(p):
    return "/".join(urllib.parse.quote(part) for part in p.split("/"))


def md5_file(path, cancel=None):
    h = hashlib.md5()
    with open(path, "rb") as f:
        while chunk := f.read(4 << 20):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            h.update(chunk)
    return h.hexdigest()


class Cancelled(Exception):
    pass


# ---------------------------------------------------------------- manifest / проверка файлов

class Item:
    """Файл (или папка), который нужно скачать."""
    __slots__ = ("rel", "remote", "size", "hash", "date", "is_dir")

    def __init__(self, rel, remote, size=0, hash_="", date=0, is_dir=False):
        self.rel, self.remote, self.size, self.hash, self.date, self.is_dir = rel, remote, size, hash_, date, is_dir


class HashCache:
    """Кэш MD5 уже проверенных файлов (как «hashmap» в оригинале), чтобы не считать заново."""

    def __init__(self, game):
        self.path = DATA_DIR / f"hashmap-{game}.json"
        self.lock = threading.Lock()
        try:
            self.data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.data = {}

    def get(self, rel):
        return self.data.get(rel)

    def set(self, rel, h):
        with self.lock:
            self.data[rel] = h

    def save(self):
        with self.lock:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data))


def set_mtime(path, ts):
    try:
        os.utime(path, (ts, ts))
    except OSError:
        pass


class Updater:
    """Проверка, скачивание и починка файлов игры. Работает в фоновом потоке.

    progress(stage, done, total, text) вызывается из рабочих потоков.
    """

    def __init__(self, cfg, game, progress=lambda *a: None, log=lambda s: None):
        self.cfg, self.game = cfg, game
        self.root = game_dir(cfg, game)
        self.cdn = GAMES[game]["cdn"]
        self.cdn_type = "main"
        self.cancel = threading.Event()
        self.progress, self.log = progress, log
        self.hashes = HashCache(game)

    # ---- манифест
    def fetch_manifest(self):
        last = None
        for t in ("main", "reserve"):
            try:
                data = http_json(f"{self.cdn[t]}/game.json", timeout=30)
                self.cdn_type = t
                return data
            except Exception as e:  # noqa: BLE001
                self.log(f"game.json с {self.cdn[t]}: {e}")
                last = e
        raise RuntimeError(f"Не удалось получить список файлов игры: {last}")

    def mod_paths(self):
        mods = self.cfg["games"].get(self.game, {}).get("mods", {})
        return {p for m in mods.values() for p in m.get("files", [])}

    # ---- проверка (порт getFilesToUpdate из оригинала)
    def plan(self, manifest, full=False, repair=False, keep_user=True):
        """Вернуть список Item для скачивания.

        full — считать MD5 всех файлов; repair — дополнительно удалить лишнее.
        """
        gs = game_settings(self.cfg, self.game)
        variant = "future" if gs["options"].get("newGraphics") else "default"
        mod_paths = self.mod_paths()
        root = self.root
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".write_test"
        try:
            probe.write_text("ok")
            probe.unlink()
        except OSError as e:
            raise RuntimeError(f"Нет прав на запись в папку игры {root}: {e}") from e

        files = []          # (node, rel, remote) — только файлы, для подсчёта прогресса
        dirs = []           # (rel, exists)
        expected = set()    # все пути из манифеста (для починки)
        pure_dirs = []

        def walk(node, parent=""):
            for ch in node.get("data") or []:
                t = ch.get("type")
                if not t:
                    walk(ch, parent)
                    continue
                if ch.get("variant_tag") and self.game == "arizona" and ch["variant_tag"] != variant:
                    continue
                local = ch.get("install_as") or ch["name"]
                rel = f"{parent}/{local}" if parent else local
                remote = f"{parent}/{ch['name']}" if parent else ch["name"]
                if t == "delete":
                    p = root / rel
                    if p.is_file() and p.stat().st_mtime < ch.get("date_change", 0):
                        try:
                            p.unlink()
                            self.log(f"удалён устаревший файл {rel}")
                        except OSError:
                            pass
                    continue
                expected.add(rel)
                if t == "dir" or ch.get("data") is not None:
                    dirs.append(rel)
                    if ch.get("pure"):
                        pure_dirs.append((rel, ch))
                    walk(ch, rel)
                else:
                    files.append((ch, rel, remote))

        walk(manifest)

        # «чистые» папки: всё, чего нет в манифесте, удаляется (кроме файлов модов)
        for rel, _node in pure_dirs:
            base = root / rel
            if not base.is_dir():
                continue
            for p in sorted(base.rglob("*"), reverse=True):
                r = p.relative_to(root).as_posix()
                if r in expected or r in mod_paths:
                    continue
                try:
                    shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()
                except OSError:
                    pass

        todo = [Item(d, d, is_dir=True) for d in dirs if not (root / d).is_dir()]
        total = len(files)
        done = 0
        lock = threading.Lock()
        need = []

        def check(entry):
            nonlocal done
            node, rel, remote = entry
            if self.cancel.is_set():
                raise Cancelled()
            try:
                return self._check_file(node, rel, remote, full, mod_paths, repair, keep_user)
            finally:
                with lock:
                    done += 1
                    if done % 20 == 0 or done == total:
                        self.progress("verify", done, total, "Проверка файлов...")

        with ThreadPoolExecutor(4) as ex:
            for r in ex.map(check, files):
                if r:
                    need.append(r)
        self.hashes.save()

        if repair:
            self._remove_extra(expected, mod_paths, keep_user)
        return todo + need

    def _check_file(self, node, rel, remote, full, mod_paths, repair, keep_user):
        p = self.root / rel
        item = Item(rel, remote, node.get("size", 0), node.get("hash", ""), node.get("date_change", 0))
        if not p.exists():
            return item
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
            return item
        if rel in mod_paths and (not repair or keep_user):
            return None   # файл заменён модом — не трогаем
        t = node.get("type")
        if t == "res" and not full:
            return None   # ресурс, который игра меняет сама: важно только наличие
        st = p.stat()
        if st.st_size != item.size:
            return item
        mtime = int(st.st_mtime)
        date = int(item.date)
        if mtime != date and t != "check":
            if date > mtime:
                cached = self.hashes.get(rel)
                if cached and cached != item.hash:
                    return item
                h = md5_file(p, self.cancel)
                self.hashes.set(rel, h)
                if h != item.hash:
                    return item
            set_mtime(p, date)
        if full or (t == "check" and mtime != date):
            h = md5_file(p, self.cancel)
            self.hashes.set(rel, h)
            if h != item.hash:
                return item
            set_mtime(p, date)
        return None

    def _remove_extra(self, expected, mod_paths, keep_user):
        root = self.root
        for p in sorted(root.rglob("*"), key=lambda x: len(x.parts), reverse=True):
            rel = p.relative_to(root).as_posix()
            if rel in expected:
                continue
            if keep_user:
                if rel in mod_paths or rel in KEEP_EXACT or any(
                        rel == k or rel.startswith(k + "/") for k in KEEP_ON_REPAIR):
                    continue
                if any(e.startswith(rel + "/") for e in KEEP_ON_REPAIR):
                    continue   # родительская папка сохраняемых файлов
            if any(e.startswith(rel + "/") for e in expected):
                continue
            try:
                shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()
                self.log(f"удалён лишний файл {rel}")
            except OSError:
                pass

    # ---- скачивание
    def download(self, items):
        files = [i for i in items if not i.is_dir]
        for i in items:
            if i.is_dir:
                (self.root / i.rel).mkdir(parents=True, exist_ok=True)
        total = sum(i.size for i in files)
        if not files:
            return
        free = shutil.disk_usage(self.root).free
        if free < total:
            raise RuntimeError(f"Недостаточно места на диске: нужно {total / 2**30:.1f} ГБ, "
                               f"свободно {free / 2**30:.1f} ГБ")
        if any(i.rel.startswith("frontend") or i.rel.endswith("frontend.zip") for i in files):
            clear_cef_cache(self.cfg)   # обновился интерфейс — старый кэш CEF мешает
        self.done_bytes = 0
        self.total_bytes = total
        lock = threading.Lock()

        def on_bytes(n):
            with lock:
                self.done_bytes += n
                done = self.done_bytes
            self.progress("download", done, total, "Загрузка файлов...")

        threads = max(1, min(int(self.cfg.get("threads", 4)), 16))
        # крупные файлы первыми — равномернее загрузка потоков
        files.sort(key=lambda i: -i.size)
        with ThreadPoolExecutor(threads) as ex:
            futs = [ex.submit(self._download_one, i, on_bytes) for i in files]
            try:
                for f in as_completed(futs):
                    f.result()
            except BaseException:
                self.cancel.set()
                raise
        self.hashes.save()

    def _download_one(self, item, on_bytes, attempt=0):
        if self.cancel.is_set():
            raise Cancelled()
        dst = self.root / item.rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        part = dst.with_name(dst.name + ".part")
        base = self.cdn[self.cdn_type]
        url = f"{base}/game/{quote_path(item.remote)}"
        got = 0
        try:
            h = hashlib.md5()
            r = Http.open(url)
            with open(part, "wb") as f:
                while chunk := r.read(1 << 18):
                    if self.cancel.is_set():
                        r.close()
                        raise Cancelled()
                    f.write(chunk)
                    h.update(chunk)
                    got += len(chunk)
                    on_bytes(len(chunk))
            digest = h.hexdigest()
            if item.hash and digest != item.hash:
                raise IOError(f"контрольная сумма не совпала ({item.rel})")
            if dst.is_dir():
                shutil.rmtree(dst)
            part.replace(dst)
            set_mtime(dst, item.date)
            self.hashes.set(item.rel, digest)
        except Cancelled:
            part.unlink(missing_ok=True)
            raise
        except Exception as e:  # noqa: BLE001
            part.unlink(missing_ok=True)
            on_bytes(-got)
            if attempt >= 3:
                raise RuntimeError(f"Ошибка при скачивании {item.rel}: {e}") from e
            self.log(f"повтор {item.rel}: {e}")
            if attempt == 1:
                self.cdn_type = "reserve" if self.cdn_type == "main" else "main"
            time.sleep(1 + attempt)
            self._download_one(item, on_bytes, attempt + 1)


# ---------------------------------------------------------------- моды

def fetch_mods(game):
    data, _ = mods_api_json(f"/{game}")
    return data.get("topOfMonth", []), data.get("mods", [])


def flatten_tree(tree):
    """Дерево вида game.json -> список (rel, node) для файлов и папок."""
    out = []

    def walk(node, parent=""):
        for ch in node.get("data") or []:
            if not ch.get("type"):
                walk(ch, parent)
                continue
            rel = f"{parent}/{ch['name']}" if parent else ch["name"]
            out.append((rel, ch))
            if ch.get("data") is not None:
                walk(ch, rel)
    walk(tree)
    return out


def install_mod(cfg, game, mod, cancel=None, log=lambda s: None, progress=lambda done, total: None):
    """Скачать мод в папку игры (параллельно). Возвращает список установленных файлов."""
    tree, _ = mods_api_json(f"/{game}/{mod['id']}")
    root = game_dir(cfg, game)
    entries = flatten_tree(tree)
    for rel, node in entries:
        if node.get("type") == "dir":
            (root / rel).mkdir(parents=True, exist_ok=True)
    todo = [(rel, node) for rel, node in entries if node.get("type") != "dir"]
    bases = (GAMES[game]["cdn"]["mods"], GAMES[game]["cdn"]["modsReserve"])
    done = 0
    lock = threading.Lock()

    def fetch(entry):
        nonlocal done
        rel, node = entry
        last = None
        for attempt in range(4):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            base = bases[0] if attempt < 2 else bases[1]
            try:
                data = Http.get(f"{base}/{mod['id']}/{quote_path(rel)}")
                if node.get("hash") and hashlib.md5(data).hexdigest() != node["hash"]:
                    raise IOError("контрольная сумма не совпала")
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                if p.is_dir():
                    shutil.rmtree(p)
                p.write_bytes(data)
                break
            except Cancelled:
                raise
            except Exception as e:  # noqa: BLE001
                last = e
                log(f"мод {mod['id']}: {rel}: {e}")
                time.sleep(0.5 * (attempt + 1))
        else:
            raise RuntimeError(f"Не удалось установить мод «{mod.get('title')}» ({rel}): {last}")
        with lock:
            done += 1
            progress(done, len(todo))
        return rel

    with ThreadPoolExecutor(12) as ex:
        files = list(ex.map(fetch, todo))
    gs = game_settings(cfg, game)
    gs["mods"][str(mod["id"])] = {"version": mod.get("version"), "title": mod.get("title"),
                                  "flag": mod.get("flag"), "files": files}
    return files


def uninstall_mod(cfg, game, mod_id):
    gs = game_settings(cfg, game)
    info = gs["mods"].pop(str(mod_id), None)
    if not info:
        return
    root = game_dir(cfg, game)
    for rel in info.get("files", []):
        p = root / rel
        if p.is_file():
            try:
                p.unlink()
            except OSError:
                pass
    # заменённые модом файлы игры вернутся при следующей проверке


# ---------------------------------------------------------------- Wine

def prefix_user_dir(cfg):
    users = Path(cfg["prefix"]) / "drive_c" / "users"
    me = users / os.environ.get("USER", "user")
    return me if me.exists() else users / "steamuser"


def clear_cef_cache(cfg):
    for sub in ("AppData/Local/Arizona Games/NG/cef", "Local Settings/Application Data/Arizona Games/NG/cef"):
        p = prefix_user_dir(cfg) / sub
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)


class Wine:
    def __init__(self, cfg):
        self.cfg = cfg

    def env(self):
        e = dict(os.environ)
        e["WINEPREFIX"] = self.cfg["prefix"]
        e["WINEARCH"] = "win64"
        e.setdefault("WINEDEBUG", "-all,err+module")
        e["DXVK_LOG_LEVEL"] = "none"
        e["DXVK_CONFIG_FILE"] = str(DATA_DIR / "dxvk.conf")
        if self.cfg.get("esync", True):
            e["WINEESYNC"] = "1"
            e["WINEFSYNC"] = "1"
        if not self.cfg.get("vsync", False):
            e["MESA_VK_WSI_PRESENT_MODE"] = "immediate"
            e["vblank_mode"] = "0"
            e["__GL_SYNC_TO_VBLANK"] = "0"
        e.setdefault("WINEDLLOVERRIDES", "mscoree,mshtml=")
        return e

    def wine(self):
        return shutil.which(self.cfg["wine"]) or self.cfg["wine"]

    def wineserver(self):
        w = Path(self.wine())
        cand = w.with_name("wineserver")
        return str(cand) if cand.exists() else (shutil.which("wineserver") or "wineserver")

    def prefix_ready(self):
        return (Path(self.cfg["prefix"]) / "system.reg").exists()

    def components_ready(self):
        return (Path(self.cfg["prefix"]) / ".arizona-components").exists()

    def _run(self, args, log=None):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n=== {time.strftime('%F %T')} {' '.join(map(str, args))}\n")
            f.flush()
            p = subprocess.Popen(args, env=self.env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, errors="replace")
            for line in p.stdout:
                f.write(line)
                if log and line.strip():
                    log(line.rstrip())
            if p.wait() != 0:
                raise RuntimeError(f"Команда завершилась с ошибкой: {' '.join(map(str, args[:3]))} "
                                   f"(подробности в {LOG_FILE})")

    def setup(self, log=lambda s: None):
        """Создать префикс и поставить то, что ставит «Установить драйвера» в оригинале:
        DirectX 9 (через DXVK), VC++ 2010/2013/2015-2022, шрифты."""
        if not shutil.which("winetricks"):
            raise RuntimeError("Не найден winetricks — установите его (sudo pacman -S winetricks)")
        Path(self.cfg["prefix"]).mkdir(parents=True, exist_ok=True)
        log("Создание окружения Wine...")
        self._run([self.wine(), "wineboot", "-i"], log)
        self._run([self.wineserver(), "-w"])
        for verbs in (["win10"], ["corefonts"], ["vcrun2010"], ["vcrun2013"], ["vcrun2022"],
                      ["d3dx9", "d3dcompiler_47"], ["dxvk"]):
            log(f"winetricks {' '.join(verbs)}...")
            self._run(["winetricks", "-q", "--unattended", *verbs], log)
        (Path(self.cfg["prefix"]) / ".arizona-components").write_text(time.strftime("%F %T"))

    @staticmethod
    def win_path(p):
        return "Z:" + str(Path(p).resolve()).replace("/", "\\")

    def disable_crash_dialog(self):
        reg = ("Windows Registry Editor Version 5.00\r\n\r\n"
               "[HKEY_CURRENT_USER\\Software\\Wine\\WineDbg]\r\n"
               '"ShowCrashDialog"=dword:00000000\r\n\r\n')
        f = DATA_DIR / "launcher.reg"
        f.write_bytes(b"\xff\xfe" + reg.encode("utf-16-le"))
        subprocess.run([self.wine(), "regedit", "/S", self.win_path(f)], env=self.env(),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def kill(self):
        subprocess.run([self.wineserver(), "-k"], env=self.env(),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def winecfg(self):
        subprocess.Popen([self.wine(), "winecfg"], env=self.env(), start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------- иконка из официального лаунчера

def exe_icon_bytes(exe):
    """Самая крупная иконка из ресурсов Windows-программы: байты PNG или .ico, либо None.

    Логотип не хранится в репозитории: он берётся из официального лаунчера,
    который пользователь уже скачал.
    """
    import struct
    try:
        d = Path(exe).read_bytes()
        u16 = lambda o: struct.unpack_from("<H", d, o)[0]   # noqa: E731
        u32 = lambda o: struct.unpack_from("<I", d, o)[0]   # noqa: E731
        pe = u32(0x3C)
        if d[pe:pe + 4] != b"PE\0\0":
            return None
        nsec, opt_size = u16(pe + 6), u16(pe + 20)
        opt = pe + 24
        ddir = opt + (96 if u16(opt) == 0x10B else 112)          # PE32 / PE32+
        rsrc_rva = u32(ddir + 2 * 8)
        secs = [(u32(o + 12), max(u32(o + 8), u32(o + 16)), u32(o + 20))
                for o in (opt + opt_size + i * 40 for i in range(nsec))]

        def off(rva):
            for va, size, raw in secs:
                if va <= rva < va + size:
                    return rva - va + raw
            raise ValueError("rva")
        base = off(rsrc_rva)

        def entries(o):
            n = u16(o + 12) + u16(o + 14)
            return [(u32(o + 16 + i * 8), u32(o + 20 + i * 8)) for i in range(n)]

        def find(o, key):
            for name, target in entries(o):
                if not name & 0x80000000 and name == key:
                    return target
            return None

        def leaf(target):
            while target & 0x80000000:
                target = entries(base + (target & 0x7FFFFFFF))[0][1]
            e = base + target
            return d[off(u32(e)):off(u32(e)) + u32(e + 4)]

        groups, icons = find(base, 14), find(base, 3)     # RT_GROUP_ICON, RT_ICON
        if groups is None or icons is None:
            return None
        grp = leaf(entries(base + (groups & 0x7FFFFFFF))[0][1])
        best = None
        for i in range(struct.unpack_from("<H", grp, 4)[0]):
            w, h, colors, _, planes, bits, _size, iid = struct.unpack_from("<BBBBHHIH", grp, 6 + i * 14)
            score = ((w or 256) * (h or 256), bits)
            if best is None or score > best[0]:
                best = (score, (w, h, colors, planes, bits, iid))
        w, h, colors, planes, bits, iid = best[1]
        sub = find(base + (icons & 0x7FFFFFFF), iid)
        if sub is None:
            return None
        img = leaf(sub)
        if not img.startswith(b"\x89PNG"):     # BMP-иконка: обернуть в формат .ico
            img = (struct.pack("<HHH", 0, 1, 1)
                   + struct.pack("<BBBBHHII", w, h, colors, 0, planes, bits, len(img), 22) + img)
        return img
    except (OSError, ValueError, struct.error, IndexError, TypeError):
        return None


def download_dirs():
    dirs = []
    try:
        out = subprocess.run(["xdg-user-dir", "DOWNLOAD"], capture_output=True, text=True, timeout=3)
        if out.stdout.strip():
            dirs.append(Path(out.stdout.strip()))
    except (OSError, subprocess.SubprocessError):
        pass
    dirs += [Path.home() / "Downloads", Path.home() / "Загрузки"]
    seen, res = set(), []
    for d in dirs:
        if d.is_dir() and d.resolve() not in seen:
            seen.add(d.resolve())
            res.append(d)
    return res


def find_official_launcher(cfg):
    """Найти официальный лаунчер (установщик или сам .exe), чтобы взять из него иконку."""
    custom = cfg.get("icon_exe")
    if custom and Path(custom).is_file():
        return Path(custom)
    places = [(d, 1) for d in download_dirs()]
    places += [(Path(cfg["games_root"]), 2), (Path(cfg["prefix"]) / "drive_c", 5)]
    for top, depth in places:
        if not top.is_dir():
            continue
        for cur, dirs, names in os.walk(top):
            level = len(Path(cur).relative_to(top).parts)
            if level >= depth:
                dirs[:] = []
            for n in names:
                low = n.lower()
                if low.endswith(".exe") and "arizona" in low and "launcher" in low and "uninstall" not in low:
                    return Path(cur) / n
    return None


def resolve_host(server):
    """Как в оригинале: если основной адрес не резолвится — берём дополнительный IP."""
    host = server["ip"]
    try:
        addr = socket.getaddrinfo(host, None, socket.AF_INET)[0][4][0]
        if addr != "127.0.0.1":
            return host
    except OSError:
        pass
    for alt in server.get("additionalIps") or []:
        if alt != host:
            return alt
    return host


def build_args(cfg, game, server, cdn_idx):
    gs = game_settings(cfg, game)
    o = gs["options"]
    nick = gs["nick"]
    args = ["-c", "-h", resolve_host(server), "-p", str(server["port"]),
            "-n", nick, "-mem", str(gs["memory"]), "-window"]
    if not o.get("windowed"):
        args.append("-modern_scale")
    flags = [
        ("-x", o.get("autoLogin")),
        ("-widescreen", o.get("wideScreen")),
        ("-ldo", o.get("preload")),
        ("-trees_new", o.get("newGraphics") or (o.get("graphics") and game == "rodina")),
        ("-t", o.get("shitPc")),
        ("-auth_cef_enable", o.get("authCef")),
        ("-enable_grass", o.get("grass")),
        ("-16bpp", o.get("oldResolution")),
        ("-allow_hdr", o.get("hdrResolution")),
    ]
    args += [f for f, on in flags if on]
    if o.get("testBranch") and gs.get("password"):
        args += ["-z", gs["password"]]
    args.append(GAMES[game]["flag"])
    args += REMOTE["extra_args"].get(game, [])
    args += ["-userId", cfg["fingerprint"]]
    for m in gs["mods"].values():
        if m.get("flag"):
            args.append(m["flag"])
    args += ["-cdn", ",".join(map(str, cdn_idx or [0, 0, 0]))]
    return args


def find_exe(root):
    for name in GTA_EXES:
        if (root / name).exists():
            return root / name
    return root / "gta_sa.exe"


def launch(cfg, game, server, cdn_idx):
    """Запустить игру. Возвращает Popen процесса wine."""
    wine = Wine(cfg)
    root = game_dir(cfg, game)
    exe = find_exe(root)
    args = build_args(cfg, game, server, cdn_idx)
    vs = -1 if cfg.get("vsync") else 0
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "dxvk.conf").write_text(
        "# создаётся лаунчером при каждом запуске\n"
        f"d3d9.presentInterval = {vs}\ndxgi.syncInterval = {vs}\n", encoding="utf-8")
    wine.disable_crash_dialog()
    log = open(LOG_FILE, "a", encoding="utf-8")
    shown = [a if a != cfg["fingerprint"] else "<id>" for a in args]
    log.write(f"\n=== {time.strftime('%F %T')} launch {exe.name} {' '.join(shown)}\n")
    log.flush()
    p = subprocess.Popen([wine.wine(), str(exe), *args], cwd=root, env=wine.env(),
                         stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    log.close()
    return p


def wait_game_exit(cfg):
    """Дождаться, пока в префиксе не останется процессов (игра закрыта)."""
    w = Wine(cfg)
    subprocess.run([w.wineserver(), "-w"], env=w.env())


def crash_info(cfg, game):
    """Разбор crashlog/last_crash.json: (упала_быстро, виноват_arizona.asi)."""
    p = game_dir(cfg, game) / "crashlog" / "last_crash.json"
    try:
        if time.time() - p.stat().st_mtime > 3600:
            return False, False
        d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return False, False
    quick = False
    try:
        h, m, s = (int(x) for x in str(d.get("playtime", "")).split(":"))
        quick = h * 3600 + m * 60 + s < 300
    except ValueError:
        pass
    return quick, d.get("module_name") == "arizona.asi"
