"""
VeloxVPN — публикация исходников на GitHub через официальный REST API.

Зачем так, а не через git:
  * git не требуется устанавливать — работаем по HTTPS через API GitHub;
  * не нужен интерактивный вход: авторизация идёт токеном;
  * скрипт можно запускать из любого места и из агента.

Как пользоваться
----------------
1. Создать Personal Access Token (classic) на GitHub:
   Settings -> Developer settings -> Personal access tokens -> Generate new token.
   Достаточно галочки ``public_repo`` (для приватного репозитория — ``repo``).
2. Положить токен в файл ``%USERPROFILE%\\.velox_github_token`` (одна строка)
   или задать переменную окружения ``GITHUB_TOKEN``.
   В репозиторий токен никогда не попадает.
3. Запустить:

       python publish_github.py --repo VeloxVPN --visibility private
       python publish_github.py --repo VeloxVPN --visibility public --release

Токен читается из переменных окружения (GITHUB_TOKEN / GH_TOKEN) или из файла
``%USERPROFILE%\\.velox_github_token``. В репозиторий он не копируется и в логи
не попадает.
"""

import argparse
import base64
import fnmatch
import json
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

API = "https://api.github.com"
API_VERSION = "2022-11-28"
USER_AGENT = "VeloxVPN-Publisher"

# Каталоги, которые не публикуются никогда (кроме случая, когда они перечислены
# в .gitignore и совпадают с правилами исключений).
DEFAULT_EXCLUDE_DIRS = {
    ".git", ".idea", ".vscode", "__pycache__", ".pytest_cache", ".mypy_cache",
    "node_modules", ".venv", "venv", "env", "build", "dist", "data",
    "VeloxVPN", "VeloxVPN-Gothic", "VeloxVPN-Gothic-2", "VeloxVPN-Gothic-3",
    "VeloxVPN-1.0.0", "build_guard", "dist_new", ".github_cache",
}

# Файлы, которые не публикуются никогда.
DEFAULT_EXCLUDE_FILES = {
    ".DS_Store", "Thumbs.db", "desktop.ini",
    "velox_app.log", "singbox_active.json", "singbox_debug.json",
    "test_check.json", "test_run.log",
}


# --------------------------------------------------------------------------
# Авторизация
# --------------------------------------------------------------------------

def read_token() -> str:
    """Достаёт токен из окружения или из файла в профиле пользователя."""
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()

    token_file = Path(os.path.expanduser("~")) / ".velox_github_token"
    if token_file.exists():
        value = token_file.read_text(encoding="utf-8").strip()
        if value:
            return value
    return ""


class GitHub:
    """Минимальный клиент GitHub REST API (без внешних зависимостей)."""

    def __init__(self, token: str):
        self.token = token
        self._blobs: Dict[str, str] = {}  # sha -> sha (кэш, чтобы не грузить дважды)

    def _request(self, method: str, path: str, payload=None, raw: bool = False,
                 accept: str = "application/vnd.github+json"):
        url = path if path.startswith("http") else API + path
        data = None
        headers = {
            "Accept": accept,
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": USER_AGENT,
        }
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            if exc.code == 401:
                raise RuntimeError(
                    "GitHub отклонил токен (401). Проверь, что Personal Access Token "
                    "действителен и в нём есть галочка public_repo (или repo)."
                ) from exc
            if exc.code == 403:
                if "Resource not accessible by personal access token" in detail:
                    raise RuntimeError(
                        "Fine-grained токен не умеет создавать репозитории. Нужен "
                        "Personal Access Token (classic) с галочкой public_repo: "
                        "GitHub -> Settings -> Developer settings -> Personal access "
                        "tokens -> Generate new token (classic)."
                    ) from exc
                raise RuntimeError(
                    "Нет прав на это действие (403). Для публичного репозитория "
                    "токену нужна галочка public_repo, для приватного — repo."
                ) from exc
            raise RuntimeError(f"GitHub API {method} {path} -> HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Не удалось связаться с GitHub: {exc.reason}") from exc

        if raw:
            return body
        if not body:
            return {}
        return json.loads(body.decode("utf-8"))

    # --- Пользователь и репозитории ---

    def whoami(self) -> Dict:
        return self._request("GET", "/user")

    def get_repo(self, owner: str, name: str) -> Optional[Dict]:
        try:
            return self._request("GET", f"/repos/{owner}/{name}")
        except RuntimeError as exc:
            if "HTTP 404" in str(exc):
                return None
            raise

    def create_repo(self, name: str, description: str, visibility: str,
                    owner: Optional[str] = None) -> Dict:
        payload = {
            "name": name,
            "description": description,
            "private": visibility != "public",
            "has_issues": True,
            "has_wiki": False,
            "auto_init": False,
        }
        path = "/user/repos" if owner is None else f"/orgs/{owner}/repos"
        if owner is not None:
            payload["visibility"] = visibility
        return self._request("POST", path, payload)

    # --- Git Data API ---

    def get_ref(self, owner: str, name: str, ref: str = "heads/main") -> Optional[Dict]:
        try:
            return self._request("GET", f"/repos/{owner}/{name}/git/ref/{ref}")
        except RuntimeError as exc:
            if "HTTP 404" in str(exc):
                return None
            raise

    def create_blob(self, owner: str, name: str, content: bytes) -> str:
        payload = {
            "content": base64.b64encode(content).decode("ascii"),
            "encoding": "base64",
        }
        result = self._request("POST", f"/repos/{owner}/{name}/git/blobs", payload)
        return result["sha"]

    def get_commit(self, owner: str, name: str, sha: str) -> Dict:
        return self._request("GET", f"/repos/{owner}/{name}/git/commits/{sha}")

    def create_tree(self, owner: str, name: str, entries: List[Dict],
                    base_tree: Optional[str] = None) -> str:
        payload = {"tree": entries}
        if base_tree:
            payload["base_tree"] = base_tree
        result = self._request("POST", f"/repos/{owner}/{name}/git/trees", payload)
        return result["sha"]

    def create_commit(self, owner: str, name: str, message: str, tree_sha: str,
                      parents: List[str]) -> str:
        payload = {"message": message, "tree": tree_sha}
        if parents:
            payload["parents"] = parents
        result = self._request("POST", f"/repos/{owner}/{name}/git/commits", payload)
        return result["sha"]

    def update_ref(self, owner: str, name: str, sha: str, ref: str = "heads/main") -> Dict:
        payload = {"sha": sha, "force": False}
        return self._request("PATCH", f"/repos/{owner}/{name}/git/refs/{ref}", payload)

    def create_ref(self, owner: str, name: str, sha: str, ref: str = "heads/main") -> Dict:
        payload = {"ref": ref, "sha": sha}
        return self._request("POST", f"/repos/{owner}/{name}/git/refs", payload)

    # --- Releases ---

    def create_release(self, owner: str, name: str, tag: str, name_title: str,
                       body: str, prerelease: bool = False) -> Dict:
        payload = {
            "tag_name": tag,
            "name": name_title,
            "body": body,
            "prerelease": prerelease,
        }
        return self._request("POST", f"/repos/{owner}/{name}/releases", payload)

    def upload_asset(self, owner: str, name: str, upload_url: str, path: Path) -> None:
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        upload_url = upload_url.split("{")[0]
        req = urllib.request.Request(
            upload_url,
            data=path.read_bytes(),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": content_type,
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            raise RuntimeError(f"Загрузка ассета {path.name} -> HTTP {exc.code}: {detail}") from exc


# --------------------------------------------------------------------------
# Отбор файлов (.gitignore)
# --------------------------------------------------------------------------

class IgnoreRules:
    """Минимальный разбор .gitignore: каталоги, glob, negations, root-anchored."""

    def __init__(self, lines: Iterable[str]):
        self.rules: List[Tuple[str, bool, bool]] = []  # (pattern, negated, dir_only)
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            negated = False
            if line.startswith("!"):
                negated = True
                line = line[1:].strip()
            dir_only = line.endswith("/")
            line = line.rstrip("/")
            if not line:
                continue
            root_anchored = "/" in line
            line = line.lstrip("/")
            self.rules.append((line, negated, dir_only or root_anchored))

    def is_ignored(self, rel_path: str, is_dir: bool) -> bool:
        """Проверяет путь относительно корня репозитория."""
        ignored = False
        for pattern, negated, dir_only in self.rules:
            if dir_only and not is_dir:
                # каталог-правило может исключать вложенные файлы
                if not any(self._match_one(part, pattern) for part in rel_path.split("/")[:-1]):
                    continue
            if self._match(rel_path, pattern):
                ignored = not negated
        return ignored

    @staticmethod
    def _match(rel_path: str, pattern: str) -> bool:
        parts = rel_path.split("/")
        for idx in range(len(parts)):
            if fnmatch.fnmatch(parts[idx], pattern):
                # правило без слэша совпадает с любым элементом пути
                if "/" not in pattern:
                    return True
                if idx == len(parts) - 1:
                    return True
        return False

    @staticmethod
    def _match_one(part: str, pattern: str) -> bool:
        return fnmatch.fnmatch(part, pattern)


def collect_files(root: Path, ignore: IgnoreRules) -> List[Path]:
    """Собирает список файлов для публикации, уважая .gitignore."""
    result: List[Path] = []

    def walk(directory: Path, rel: str):
        try:
            entries = sorted(directory.iterdir(), key=lambda p: p.name.lower())
        except (PermissionError, OSError):
            return
        for entry in entries:
            name = entry.name
            rel_path = f"{rel}/{name}" if rel else name
            is_dir = entry.is_dir()

            if is_dir and name in DEFAULT_EXCLUDE_DIRS:
                continue
            if not is_dir and name in DEFAULT_EXCLUDE_FILES:
                continue
            if ignore.is_ignored(rel_path, is_dir):
                continue
            if is_dir:
                walk(entry, rel_path)
            elif entry.is_file():
                result.append(entry)

    walk(root, "")
    return result


# --------------------------------------------------------------------------
# Основной сценарий
# --------------------------------------------------------------------------

def build_commit_message() -> str:
    """Формирует текст коммита из последнего изменения в репозитории."""
    return "VeloxVPN: автоматическая публикация исходников"


def zip_build(build_dir: Path, out_file: Path) -> Path:
    """Упаковывает собранное приложение в zip для Release."""
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_file, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in build_dir.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(build_dir))
    return out_file


def list_remote_files(gh: "GitHub", owner: str, name: str, tree_sha: str) -> List[str]:
    """Возвращает список путей файлов в удалённом дереве (рекурсивно)."""
    result: List[str] = []

    def walk(sha: str, prefix: str):
        try:
            data = gh._request("GET", f"/repos/{owner}/{name}/git/trees/{sha}?recursive=1")
        except RuntimeError:
            return
        for item in data.get("tree", []):
            if item.get("type") == "blob":
                result.append(f"{prefix}{item['path']}")

    walk(tree_sha, "")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Публикация VeloxVPN на GitHub")
    parser.add_argument("--repo", default="VeloxVPN", help="Имя репозитория")
    parser.add_argument("--owner", default=None,
                        help="Владелец (по умолчанию — аккаунт токена)")
    parser.add_argument("--org", default=None, help="Организация (если репозиторий в org)")
    parser.add_argument("--visibility", choices=["public", "private"], default="private",
                        help="Видимость нового репозитория")
    parser.add_argument("--description", default="FastVPN Configurator — настольный VPN-клиент для Windows")
    parser.add_argument("--branch", default="main", help="Ветка (по умолчанию main)")
    parser.add_argument("--message", default=None, help="Текст коммита")
    parser.add_argument("--release", action="store_true",
                        help="Собрать релиз и приложить zip со сборкой")
    parser.add_argument("--release-tag", default=None, help="Тег релиза (по умолчанию v<дата>)")
    parser.add_argument("--build-dir", default=None,
                        help="Папка собранного приложения для релиза")
    parser.add_argument("--dry-run", action="store_true",
                        help="Только показать, что будет отправлено")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    token = read_token()
    if not token and not args.dry_run:
        print("ОШИБКА: не найден токен GitHub.")
        print(f"Создайте файл {Path(os.path.expanduser('~')) / '.velox_github_token'} "
              "с Personal Access Token или задайте GITHUB_TOKEN.")
        return 1

    ignore_file = root / ".gitignore"
    ignore = IgnoreRules(ignore_file.read_text(encoding="utf-8").splitlines()) \
        if ignore_file.exists() else IgnoreRules([])

    files = collect_files(root, ignore)
    total_size = sum(f.stat().st_size for f in files)
    print(f"Файлов к публикации: {len(files)} ({total_size / 1024:.1f} КБ)")
    for path in files:
        rel = path.relative_to(root).as_posix()
        print(f"  {rel}")

    if args.dry_run:
        return 0

    gh = GitHub(token)
    user = gh.whoami()
    login = user.get("login", "?")
    owner = args.owner or args.org or login
    print(f"\nАвторизация: {login} ({user.get('name') or 'без имени'})")

    # Fine-grained токены не умеют создавать репозитории — предупреждаем заранее,
    # чтобы не падать на середине публикации.
    if token.startswith("github_pat_"):
        repo_exists = gh.get_repo(owner, args.repo) is not None
        if not repo_exists:
            print(f"\nОШИБКА: токен fine-grained (github_pat_...), а репозиторий "
                  f"{owner}/{args.repo} ещё не создан.\n"
                  "Fine-grained токены не могут создавать репозитории. Нужен "
                  "Personal Access Token (classic) с галочкой public_repo:\n"
                  "  GitHub -> Settings -> Developer settings -> Personal access tokens\n"
                  "  -> Generate new token (classic) -> отметить public_repo")
            return 1
        print("Токен fine-grained — репозиторий уже существует, публикуем в него.")

    print(f"Репозиторий: {owner}/{args.repo} ({args.visibility})")

    repo = gh.get_repo(owner, args.repo)
    if repo is None:
        if args.org:
            repo = gh.create_repo(args.repo, args.description, args.visibility, owner=args.org)
        else:
            repo = gh.create_repo(args.repo, args.description, args.visibility)
        print(f"Создан репозиторий: {repo.get('html_url')}")
    else:
        print(f"Репозиторий уже существует: {repo.get('html_url')}")
        if args.visibility == "public" and repo.get("private"):
            print("  Репозиторий приватный — делаем публичным...")
            gh._request("PATCH", f"/repos/{owner}/{args.repo}", {"private": False})
            print("  Готово: репозиторий теперь публичный.")

    # 1. Блобы
    entries: List[Dict] = []
    published_paths = set()
    for path in files:
        rel = path.relative_to(root).as_posix()
        content = path.read_bytes()
        sha = gh.create_blob(owner, args.repo, content)
        entries.append({
            "path": rel,
            "mode": "100644",
            "type": "blob",
            "sha": sha,
        })
        published_paths.add(rel)
        print(f"  blob {rel}")

    # 2. Дерево
    ref = gh.get_ref(owner, args.repo, f"heads/{args.branch}")
    base_tree = None
    if ref:
        # GitHub в качестве base_tree ждёт sha дерева, а не коммита,
        # поэтому берём дерево родительского коммита.
        try:
            parent = gh.get_commit(owner, args.repo, ref["object"]["sha"])
            base_tree = parent.get("tree", {}).get("sha")
        except RuntimeError:
            base_tree = None

    # Файлы, которые были в репозитории, но исчезли локально, — удаляем.
    if ref and base_tree:
        for stale in list_remote_files(gh, owner, args.repo, base_tree):
            if stale not in published_paths:
                entries.append({"path": stale, "mode": "100644", "type": "blob", "sha": None})
                print(f"  удалить {stale}")

    tree_sha = gh.create_tree(owner, args.repo, entries, base_tree=base_tree)

    # 3. Коммит
    parents = [ref["object"]["sha"]] if ref else []
    message = args.message or build_commit_message()
    commit_sha = gh.create_commit(owner, args.repo, message, tree_sha, parents)

    # 4. Обновление ветки
    if ref:
        gh.update_ref(owner, args.repo, commit_sha, f"heads/{args.branch}")
    else:
        gh.create_ref(owner, args.repo, commit_sha, f"heads/{args.branch}")
    print(f"\nКоммит: {commit_sha}")
    print(f"Ветка {args.branch} обновлена.")

    # 5. Релиз со сборкой
    if args.release:
        build_dir = Path(args.build_dir) if args.build_dir else root / "VeloxVPN"
        if not build_dir.exists():
            print("ПАПКА СБОРКИ НЕ НАЙДЕНА — релиз пропущен.")
        else:
            tag = args.release_tag or f"v{time.strftime('%Y.%m.%d')}"
            out_zip = root / f"VeloxVPN-{tag}.zip"
            zip_build(build_dir, out_zip)
            release = gh.create_release(
                owner, args.repo, tag,
                f"VeloxVPN {tag}",
                "Автоматическая сборка VeloxVPN для Windows.",
            )
            gh.upload_asset(owner, args.repo, release["upload_url"], out_zip)
            print(f"Релиз {tag}: {release.get('html_url')}")

    print(f"\nГотово: https://github.com/{owner}/{args.repo}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        print(f"\nОШИБКА: {exc}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nПрервано пользователем.")
        sys.exit(130)
