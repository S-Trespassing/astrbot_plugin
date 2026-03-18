from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate AstrBot custom plugin source JSON from metadata.yaml.",
    )
    parser.add_argument(
        "--workspace",
        default=".",
        help="Plugin repository root. Default: current directory",
    )
    parser.add_argument(
        "--output",
        default="plugin_cache.json",
        help="Output JSON path relative to workspace. Default: plugin_cache.json",
    )
    parser.add_argument(
        "--branch",
        default="main",
        help="GitHub branch used to build raw asset URLs. Default: main",
    )
    parser.add_argument(
        "--updated-at",
        default="",
        help="Optional ISO8601 timestamp override.",
    )
    return parser.parse_args()


def read_metadata(metadata_path: Path) -> dict:
    data: dict[str, object] = {}
    current_list_key = ""
    for raw_line in metadata_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line:
            current_list_key = ""
            continue

        stripped = line.strip()
        if current_list_key and stripped.startswith("- "):
            items = data.setdefault(current_list_key, [])
            if isinstance(items, list):
                items.append(stripped[2:].strip().strip("'\""))
            continue

        if ":" not in stripped:
            current_list_key = ""
            continue

        key, value = stripped.split(":", 1)
        normalized_key = key.strip()
        normalized_value = value.strip().strip("'\"")
        if normalized_value:
            data[normalized_key] = normalized_value
            current_list_key = ""
            continue

        data[normalized_key] = []
        current_list_key = normalized_key
    return data


def detect_updated_at(workspace: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%cI"],
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
        )
        timestamp = result.stdout.strip()
        if timestamp:
            return timestamp
    except Exception:
        pass
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_repo_path(repo_url: str) -> str:
    parsed = urlparse(repo_url)
    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    return path


def build_logo_url(workspace: Path, repo_url: str, branch: str) -> str | None:
    logo_path = workspace / "logo.png"
    if not logo_path.exists():
        return None
    repo_path = normalize_repo_path(repo_url)
    if not repo_path:
        return None
    return f"https://raw.githubusercontent.com/{repo_path}/{branch}/logo.png"


def build_source_entry(
    workspace: Path,
    metadata: dict,
    branch: str,
    updated_at: str,
) -> dict[str, dict[str, object]]:
    plugin_name = str(metadata.get("name", "")).strip()
    if not plugin_name:
        raise RuntimeError("metadata.yaml missing name")

    repo_url = str(metadata.get("repo", "")).strip()
    if not repo_url:
        raise RuntimeError("metadata.yaml missing repo")

    support_platforms_raw = metadata.get("support_platforms", "")
    support_platforms: list[str] = []
    if isinstance(support_platforms_raw, list):
        support_platforms = [str(item).strip() for item in support_platforms_raw if str(item).strip()]
    elif isinstance(support_platforms_raw, str) and support_platforms_raw:
        support_platforms = [item.strip() for item in support_platforms_raw.split(",") if item.strip()]

    entry: dict[str, object] = {
        "display_name": str(metadata.get("display_name", plugin_name)).strip() or plugin_name,
        "desc": str(metadata.get("desc", "")).strip(),
        "author": str(metadata.get("author", "")).strip(),
        "repo": repo_url,
        "tags": [],
        "stars": 0,
        "version": str(metadata.get("version", "")).strip(),
        "updated_at": updated_at,
    }

    astrbot_version = str(metadata.get("astrbot_version", "")).strip()
    if astrbot_version:
        entry["astrbot_version"] = astrbot_version

    if support_platforms:
        entry["support_platforms"] = support_platforms

    logo_url = build_logo_url(workspace, repo_url, branch)
    if logo_url:
        entry["logo"] = logo_url

    return {plugin_name: entry}


def main() -> int:
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    metadata_path = workspace / "metadata.yaml"
    output_path = (workspace / args.output).resolve()

    if not metadata_path.exists():
        raise SystemExit("metadata.yaml not found")

    metadata = read_metadata(metadata_path)
    updated_at = args.updated_at.strip() or detect_updated_at(workspace)
    payload = build_source_entry(
        workspace=workspace,
        metadata=metadata,
        branch=args.branch.strip() or "main",
        updated_at=updated_at,
    )

    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Created: {output_path}")
    print(f"Plugin: {next(iter(payload))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
