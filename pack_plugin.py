from __future__ import annotations

import argparse
import fnmatch
import shutil
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


EXCLUDE_NAMES = {
    ".git",
    ".gitignore",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
    ".venv",
    "venv",
    "tests",
    "dist",
    "captcha_preview.png",
    "pack_plugin.py",
    "借鉴",
}

EXCLUDE_GLOBS = {
    "*.pyc",
    "*.pyo",
    "*.zip",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Package the current AstrBot plugin into an uploadable zip."
    )
    parser.add_argument(
        "--output-dir",
        default="dist",
        help="Directory used to store the generated zip. Default: dist",
    )
    parser.add_argument(
        "--name",
        default="",
        help="Override the package root folder and zip file name.",
    )
    return parser.parse_args()


def read_plugin_name(workspace: Path) -> str:
    metadata_path = workspace / "metadata.yaml"
    if metadata_path.exists():
        for raw_line in metadata_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            if key.strip() == "name":
                plugin_name = value.strip().strip("'\"")
                if plugin_name:
                    return plugin_name
    return workspace.name


def should_exclude(path: Path, workspace: Path) -> bool:
    relative = path.relative_to(workspace)
    parts = relative.parts
    if any(part in EXCLUDE_NAMES for part in parts):
        return True
    if any(fnmatch.fnmatch(path.name, pattern) for pattern in EXCLUDE_GLOBS):
        return True
    return False


def collect_items(workspace: Path) -> list[Path]:
    items: list[Path] = []
    for path in workspace.rglob("*"):
        if path.is_dir():
            continue
        if should_exclude(path, workspace):
            continue
        items.append(path)
    return sorted(items)


def validate_required_files(items: list[Path], workspace: Path) -> None:
    relative_paths = {str(path.relative_to(workspace)).replace("\\", "/") for path in items}
    required = {"main.py", "metadata.yaml"}
    missing = sorted(required - relative_paths)
    if missing:
        missing_text = ", ".join(missing)
        raise RuntimeError(f"Missing required plugin files: {missing_text}")


def build_zip(workspace: Path, output_dir: Path, package_name: str) -> Path:
    items = collect_items(workspace)
    validate_required_files(items, workspace)

    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f"{package_name}.zip"
    if zip_path.exists():
        zip_path.unlink()

    with tempfile.TemporaryDirectory(prefix="astrbot_pack_") as temp_dir:
        staging_root = Path(temp_dir) / package_name
        staging_root.mkdir(parents=True, exist_ok=True)

        for source_path in items:
            relative = source_path.relative_to(workspace)
            target_path = staging_root / relative
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)

        with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as zf:
            # AstrBot 4.19.x 的安装器会把 zip 的第一项当作目录名处理。
            # 这里必须显式写入顶层目录项，避免第一项变成某个文件。
            zf.writestr(f"{package_name}/", "")
            for staged_file in sorted(staging_root.rglob("*")):
                if staged_file.is_dir():
                    continue
                arcname = staged_file.relative_to(Path(temp_dir)).as_posix()
                zf.write(staged_file, arcname)

    return zip_path


def preview_zip(zip_path: Path) -> list[str]:
    with ZipFile(zip_path, "r") as zf:
        return zf.namelist()


def main() -> int:
    args = parse_args()
    workspace = Path(__file__).resolve().parent
    package_name = args.name.strip() or read_plugin_name(workspace)
    output_dir = (workspace / args.output_dir).resolve()

    zip_path = build_zip(workspace, output_dir, package_name)
    entries = preview_zip(zip_path)

    print(f"Created: {zip_path}")
    print(f"Package root: {package_name}/")
    print("Top entries:")
    for entry in entries[:20]:
        print(f"  - {entry}")
    if len(entries) > 20:
        print(f"  ... and {len(entries) - 20} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
