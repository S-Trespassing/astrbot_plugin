from __future__ import annotations

import filecmp
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from .storage import JsonStorage


class SelfUpdateError(RuntimeError):
    """插件自更新失败。"""


@dataclass(slots=True)
class UpdateResult:
    changed: bool
    mode: str
    repo_url: str
    branch: str
    commit: str = ""
    copied_files: int = 0
    removed_files: int = 0


class SelfUpdateService:
    SKIP_DIR_NAMES = {
        ".git",
        ".github",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
    }
    SKIP_FILE_SUFFIXES = {
        ".pyc",
        ".pyo",
        ".tmp",
    }

    def __init__(
        self,
        plugin_dir: Path,
        temp_dir: Path,
        storage: JsonStorage,
    ) -> None:
        self.plugin_dir = plugin_dir
        self.temp_dir = temp_dir / "self_update"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.storage = storage

    @staticmethod
    def normalize_repo_url(repo_url: str) -> str:
        value = (repo_url or "").strip()
        if not value:
            return ""
        if value.startswith("git@github.com:"):
            value = "https://github.com/" + value.split(":", 1)[1]
        value = value.replace("http://github.com/", "https://github.com/")
        if value.endswith(".git"):
            value = value[:-4]
        value = value.rstrip("/")
        prefix = "https://github.com/"
        if not value.startswith(prefix):
            return ""
        parts = [part for part in value[len(prefix) :].split("/") if part]
        if len(parts) < 2:
            return ""
        owner, repo_name = parts[0], parts[1]
        return f"{prefix}{owner}/{repo_name}"

    @classmethod
    def locate_plugin_root(cls, search_root: Path) -> Path:
        candidates: list[Path] = []
        for metadata_path in search_root.rglob("metadata.yaml"):
            candidate = metadata_path.parent
            if (candidate / "main.py").exists():
                candidates.append(candidate)
        if not candidates:
            raise SelfUpdateError("仓库内容中没有找到有效的 AstrBot 插件根目录。")
        return sorted(
            candidates,
            key=lambda item: (len(item.relative_to(search_root).parts), str(item)),
        )[0]

    def is_git_repo(self) -> bool:
        return (self.plugin_dir / ".git").exists()

    def detect_origin_repo(self) -> str:
        if not self.is_git_repo():
            return ""
        try:
            remote = self._run_git(["remote", "get-url", "origin"])
        except SelfUpdateError:
            return ""
        return self.normalize_repo_url(remote)

    def detect_current_branch(self) -> str:
        if not self.is_git_repo():
            return ""
        try:
            branch = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"])
        except SelfUpdateError:
            return ""
        branch = branch.strip()
        return "" if branch == "HEAD" else branch

    def cleanup_stale_files(self, max_age_seconds: int = 86400) -> None:
        now = time.time()
        for item in self.temp_dir.iterdir():
            try:
                if now - item.stat().st_mtime <= max_age_seconds:
                    continue
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    item.unlink(missing_ok=True)
            except OSError:
                continue

    async def update_from_github(
        self,
        repo_url: str,
        branch: str,
        github_token: str = "",
    ) -> UpdateResult:
        normalized_repo = self.normalize_repo_url(repo_url)
        if not normalized_repo:
            raise SelfUpdateError("请先配置有效的 GitHub 仓库地址。")

        normalized_branch = (branch or "main").strip() or "main"
        if self.is_git_repo():
            return self._update_from_git(normalized_repo, normalized_branch)
        return await self._update_from_archive(
            normalized_repo,
            normalized_branch,
            github_token=github_token,
        )

    def apply_directory_snapshot(
        self,
        source_root: Path,
        repo_url: str,
        branch: str,
        commit: str = "",
    ) -> UpdateResult:
        files = self._collect_source_files(source_root)
        previous_state = self.storage.load()
        previous_files = {
            str(item)
            for item in previous_state.get("managed_files", [])
            if isinstance(item, str)
        }
        copied = 0
        removed = 0
        changed = False

        for relative_path in files:
            source_path = source_root / relative_path
            target_path = self.plugin_dir / relative_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if not target_path.exists() or not filecmp.cmp(
                source_path,
                target_path,
                shallow=False,
            ):
                shutil.copy2(source_path, target_path)
                copied += 1
                changed = True

        next_files = {relative_path.as_posix() for relative_path in files}
        for relative_file in sorted(previous_files - next_files):
            target_path = self.plugin_dir / relative_file
            if target_path.exists() and target_path.is_file() and self._is_safe_target(target_path):
                target_path.unlink(missing_ok=True)
                removed += 1
                changed = True

        self.storage.save(
            {
                "mode": "archive",
                "repo_url": repo_url,
                "branch": branch,
                "commit": commit,
                "managed_files": sorted(next_files),
            }
        )
        return UpdateResult(
            changed=changed,
            mode="archive",
            repo_url=repo_url,
            branch=branch,
            commit=commit,
            copied_files=copied,
            removed_files=removed,
        )

    def _update_from_git(self, repo_url: str, branch: str) -> UpdateResult:
        if shutil.which("git") is None:
            raise SelfUpdateError("当前插件目录是 Git 仓库，但服务器没有安装 git。")

        pending = self._run_git(["status", "--porcelain"])
        if pending.strip():
            raise SelfUpdateError("当前插件目录存在未提交改动，已停止自动更新以避免覆盖本地修改。")

        remote_url = ""
        try:
            remote_url = self._run_git(["remote", "get-url", "origin"])
        except SelfUpdateError:
            remote_url = ""

        if remote_url:
            if self.normalize_repo_url(remote_url) != repo_url:
                self._run_git(["remote", "set-url", "origin", repo_url])
        else:
            self._run_git(["remote", "add", "origin", repo_url])

        self._run_git(["fetch", "origin", branch, "--depth", "1"])

        current_branch = self.detect_current_branch()
        if current_branch != branch:
            branch_exists = self._run_git(["branch", "--list", branch]).strip()
            if branch_exists:
                self._run_git(["switch", branch])
            else:
                self._run_git(["switch", "-c", branch, "--track", f"origin/{branch}"])

        before_commit = self._run_git(["rev-parse", "HEAD"]).strip()
        self._run_git(["pull", "--ff-only", "origin", branch])
        after_commit = self._run_git(["rev-parse", "HEAD"]).strip()
        self._install_requirements()
        self.storage.save(
            {
                "mode": "git",
                "repo_url": repo_url,
                "branch": branch,
                "commit": after_commit,
                "managed_files": [],
            }
        )
        return UpdateResult(
            changed=before_commit != after_commit,
            mode="git",
            repo_url=repo_url,
            branch=branch,
            commit=after_commit,
        )

    async def _update_from_archive(
        self,
        repo_url: str,
        branch: str,
        github_token: str = "",
    ) -> UpdateResult:
        previous_state = self.storage.load()
        latest_commit = await self._fetch_latest_commit(
            repo_url,
            branch,
            github_token=github_token,
        )
        if (
            latest_commit
            and previous_state.get("repo_url") == repo_url
            and previous_state.get("branch") == branch
            and previous_state.get("commit") == latest_commit
        ):
            return UpdateResult(
                changed=False,
                mode="archive",
                repo_url=repo_url,
                branch=branch,
                commit=latest_commit,
            )

        with tempfile.TemporaryDirectory(
            dir=self.temp_dir,
            prefix="self_update_",
        ) as work_dir_str:
            work_dir = Path(work_dir_str)
            zip_path = work_dir / "repo.zip"
            await self._download_archive(
                repo_url,
                branch,
                zip_path,
                github_token=github_token,
            )
            with zipfile.ZipFile(zip_path) as archive:
                archive.extractall(work_dir)
            source_root = self.locate_plugin_root(work_dir)
            result = self.apply_directory_snapshot(
                source_root,
                repo_url=repo_url,
                branch=branch,
                commit=latest_commit,
            )

        self._install_requirements()
        return result

    async def _fetch_latest_commit(
        self,
        repo_url: str,
        branch: str,
        github_token: str = "",
    ) -> str:
        api_url = self._build_commit_api_url(repo_url, branch)
        if not api_url:
            return ""
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "astrbot-plugin-group-manage",
        }
        if github_token:
            headers["Authorization"] = f"Bearer {github_token}"
        try:
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                response = await client.get(api_url, headers=headers)
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return ""
        sha = payload.get("sha", "")
        return str(sha).strip()

    async def _download_archive(
        self,
        repo_url: str,
        branch: str,
        target_path: Path,
        github_token: str = "",
    ) -> None:
        archive_url = f"{repo_url}/archive/refs/heads/{quote(branch, safe='')}.zip"
        headers = {"User-Agent": "astrbot-plugin-group-manage"}
        if github_token:
            headers["Authorization"] = f"Bearer {github_token}"
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.get(archive_url, headers=headers)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise SelfUpdateError(f"下载 GitHub 仓库压缩包失败：{exc.response.status_code}") from exc
        target_path.write_bytes(response.content)

    def _collect_source_files(self, source_root: Path) -> list[Path]:
        files: list[Path] = []
        for path in sorted(source_root.rglob("*")):
            if not path.is_file():
                continue
            relative_path = path.relative_to(source_root)
            if any(part in self.SKIP_DIR_NAMES for part in relative_path.parts[:-1]):
                continue
            if path.suffix.lower() in self.SKIP_FILE_SUFFIXES:
                continue
            files.append(relative_path)
        return files

    def _install_requirements(self) -> None:
        requirements_path = self.plugin_dir / "requirements.txt"
        if not requirements_path.exists():
            return
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-r",
                str(requirements_path),
                "--disable-pip-version-check",
            ],
            cwd=self.plugin_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            check=False,
        )
        if completed.returncode == 0:
            return
        tail_output = "\n".join(
            line
            for line in (
                (completed.stdout or "").strip().splitlines()
                + (completed.stderr or "").strip().splitlines()
            )[-8:]
        ).strip()
        detail = f"\n{tail_output}" if tail_output else ""
        raise SelfUpdateError(f"安装插件依赖失败。{detail}")

    def _run_git(self, args: list[str]) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=self.plugin_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
        if completed.returncode == 0:
            return (completed.stdout or "").strip()
        detail = (completed.stderr or completed.stdout or "").strip()
        raise SelfUpdateError(detail or f"git {' '.join(args)} 执行失败。")

    def _build_commit_api_url(self, repo_url: str, branch: str) -> str:
        prefix = "https://github.com/"
        if not repo_url.startswith(prefix):
            return ""
        owner_repo = repo_url[len(prefix) :].split("/")
        if len(owner_repo) < 2:
            return ""
        owner, repo_name = owner_repo[0], owner_repo[1]
        return (
            f"https://api.github.com/repos/{owner}/{repo_name}/commits/"
            f"{quote(branch, safe='')}"
        )

    def _is_safe_target(self, target_path: Path) -> bool:
        try:
            target_path.resolve().relative_to(self.plugin_dir.resolve())
        except ValueError:
            return False
        return True
