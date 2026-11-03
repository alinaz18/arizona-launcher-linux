#!/usr/bin/env python3
"""Ежедневная проверка, что лаунчер всё ещё совместим с серверами Arizona.

Запускается из .github/workflows/watchdog.yml. Использует remote.json из репозитория
(тот же, что получают лаунчеры пользователей). Печатает отчёт в Markdown и
завершается с кодом 1, если что-то сломалось или вышла новая версия официального лаунчера.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import arizona_core as core  # noqa: E402

OFFICIAL_REPO = "dogoran-el/arizona-launcher"   # откуда официальный лаунчер берёт обновления
problems, ok = [], []


def check(name, fn):
    try:
        msg = fn()
        ok.append(f"{name}: {msg}" if msg else name)
    except Exception as e:  # noqa: BLE001
        problems.append(f"**{name}**: {e}")


def official_version():
    headers = {}
    if os.environ.get("GH_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GH_TOKEN']}"
    import urllib.request
    req = urllib.request.Request(f"https://api.github.com/repos/{OFFICIAL_REPO}/releases/latest",
                                 headers={"User-Agent": "arizona-launcher-watchdog", **headers})
    with urllib.request.urlopen(req, timeout=20) as r:
        tag = json.load(r)["tag_name"].lstrip("v")
    known = core.REMOTE["official_version"]
    if tag != known:
        raise RuntimeError(f"вышла новая версия официального лаунчера {tag} (проверена {known}). "
                           "Нужно сравнить её с нашей реализацией и обновить official_version в remote.json.")
    return tag


def servers():
    data = core.fetch_servers()
    counts = []
    for game in core.GAMES:
        lst = data.get(game)
        if not lst:
            raise RuntimeError(f"в ответе нет серверов для «{game}»")
        for s in lst:
            for k in ("name", "ip", "port", "online", "maxplayers"):
                if k not in s:
                    raise RuntimeError(f"у сервера {s.get('name')} нет поля {k}")
        counts.append(f"{game} {len(lst)}")
    return ", ".join(counts)


def projects():
    data = core.fetch_projects()
    if not isinstance(data, list) or not any(p.get("gameId") == "arizona" for p in data):
        raise RuntimeError("неожиданный формат launcher/projects")
    return f"{len(data)} проектов"


def manifest(game):
    def run():
        up = core.Updater({"games_root": "/nonexistent", "games": {}, "threads": 1}, game)
        m = up.fetch_manifest()
        files = [(rel, n) for rel, n in core.flatten_tree(m) if n.get("type") in ("file", "check", "res")]
        if not files:
            raise RuntimeError("пустой game.json")
        for rel, n in files:
            for k in ("size", "hash", "date_change"):
                if k not in n:
                    raise RuntimeError(f"у файла {rel} нет поля {k}")
        if not any(rel == "gta_sa.exe" for rel, _ in files):
            raise RuntimeError("в game.json нет gta_sa.exe")
        # скачать самый маленький файл и сверить MD5 — проверка пути <CDN>/game/<файл>
        rel, n = min(((r, x) for r, x in files if x.get("size", 0) > 0), key=lambda t: t[1]["size"])
        data = core.Http.get(f"{up.cdn[up.cdn_type]}/game/{core.quote_path(rel)}")
        if hashlib.md5(data).hexdigest() != n["hash"]:
            raise RuntimeError(f"MD5 скачанного файла {rel} не совпал")
        size = sum(x.get("size", 0) for _, x in files) / 2**30
        return f"{len(files)} файлов, {size:.1f} ГБ, CDN {up.cdn_type}"
    return run


def mods(game):
    def run():
        top, lst = core.fetch_mods(game)
        if not lst:
            raise RuntimeError("пустой список модов")
        m = next((x for x in lst if x.get("visible", True) is not False), lst[0])
        tree, _ = core.mods_api_json(f"/{game}/{m['id']}")
        if not core.flatten_tree(tree):
            raise RuntimeError(f"пустой список файлов мода {m['id']}")
        return f"{len(lst)} модов"
    return run


def main():
    core.apply_remote(json.loads((ROOT / "remote.json").read_text(encoding="utf-8")))
    check("Версия официального лаунчера", official_version)
    check("Список серверов", servers)
    check("Новости (projects)", projects)
    for game in core.GAMES:
        check(f"Файлы игры: {game}", manifest(game))
    check("Моды: arizona", mods("arizona"))
    check("Моды: rodina", mods("rodina"))

    lines = ["## Проблемы", *[f"- {p}" for p in problems], ""] if problems else []
    lines += ["## В порядке", *[f"- {o}" for o in ok]]
    report = "\n".join(lines)
    print(report)
    out = os.environ.get("GITHUB_STEP_SUMMARY")
    if out:
        Path(out).write_text(report + "\n", encoding="utf-8")
    Path(ROOT / "watchdog-report.md").write_text(report + "\n", encoding="utf-8")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
