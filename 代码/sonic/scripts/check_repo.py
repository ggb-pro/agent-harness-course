"""检查四文档、链接和不该入库的文件；不访问网络。"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote


REPO_ROOT = Path(__file__).resolve().parents[3]
MARKDOWN_LINK = re.compile(r"!?(?:\[[^\]]+\])\(([^)]+)\)")
URL_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)
MARKDOWN_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
CODE_LINE_FRAGMENT = re.compile(r"^L([1-9]\d*)(?:-L([1-9]\d*))?$", re.IGNORECASE)
EXPECTED_DOCS = {"README.md", "学习文档.md", "设计说明.md", "面经.md"}


def check_four_documents() -> list[str]:
    found = {
        str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        for path in REPO_ROOT.rglob("*.md")
        if ".git" not in path.parts and ".venv" not in path.parts
    }
    if found == EXPECTED_DOCS:
        return []
    extra = sorted(found - EXPECTED_DOCS)
    missing = sorted(EXPECTED_DOCS - found)
    return [f"Markdown 必须恰好四份；多余: {extra}；缺少: {missing}"]


def markdown_anchors(path: Path) -> set[str]:
    """Build the subset of GitHub heading slugs used by this repository."""

    anchors: set[str] = set()
    occurrences: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = MARKDOWN_HEADING.match(line)
        if match is None:
            continue
        heading = re.sub(r"<[^>]+>", "", match.group(1)).lower()
        base = re.sub(r"[^\w\s-]", "", heading, flags=re.UNICODE)
        base = re.sub(r"\s+", "-", base).strip("-")
        occurrence = occurrences.get(base, 0)
        occurrences[base] = occurrence + 1
        anchors.add(base if occurrence == 0 else f"{base}-{occurrence}")
    return anchors


def check_local_links() -> list[str]:
    problems: list[str] = []
    anchor_cache: dict[Path, set[str]] = {}
    line_count_cache: dict[Path, int] = {}
    for source in REPO_ROOT.rglob("*.md"):
        if ".git" in source.parts or ".venv" in source.parts:
            continue
        text = source.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK.finditer(text):
            raw = match.group(1).strip()
            if not raw or URL_SCHEME.match(raw):
                continue
            # 本仓库不用带 title 的链接；尖括号仅表示路径有空格。
            path_and_fragment = raw.strip("<>").split("#", 1)
            path_part = unquote(path_and_fragment[0])
            fragment = unquote(path_and_fragment[1]) if len(path_and_fragment) == 2 else ""
            target = source.resolve() if not path_part else (source.parent / path_part).resolve()
            if not target.is_relative_to(REPO_ROOT):
                problems.append(f"{source.relative_to(REPO_ROOT)}: 链接越出仓库: {raw}")
            elif not target.exists():
                problems.append(f"{source.relative_to(REPO_ROOT)}: 找不到 {raw}")
            elif fragment:
                line_match = CODE_LINE_FRAGMENT.fullmatch(fragment)
                if line_match is not None:
                    line_count = line_count_cache.setdefault(
                        target,
                        len(target.read_text(encoding="utf-8").splitlines()),
                    )
                    start = int(line_match.group(1))
                    end = int(line_match.group(2) or start)
                    if end < start or end > line_count:
                        problems.append(
                            f"{source.relative_to(REPO_ROOT)}: 行号越界 {raw}"
                        )
                elif target.suffix.lower() == ".md":
                    anchors = anchor_cache.setdefault(target, markdown_anchors(target))
                    if fragment.lower() not in anchors:
                        problems.append(
                            f"{source.relative_to(REPO_ROOT)}: 找不到标题锚点 {raw}"
                        )
    return problems


def check_sensitive_files() -> list[str]:
    problems: list[str] = []
    forbidden_names = {".env", ".env.local", "id_rsa", "id_ed25519"}
    forbidden_suffixes = {".pem", ".p12", ".pfx", ".key", ".zip"}
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or ".venv" in path.parts:
            continue
        if path.name.lower() in forbidden_names or path.suffix.lower() in forbidden_suffixes:
            problems.append(f"{path.relative_to(REPO_ROOT)}: 不应提交凭据或重复源码包")
    return problems


if __name__ == "__main__":
    errors = check_four_documents() + check_local_links() + check_sensitive_files()
    if errors:
        print("\n".join(errors), file=sys.stderr)
        raise SystemExit(1)
    print("四文档、本地链接与敏感文件名检查通过")
