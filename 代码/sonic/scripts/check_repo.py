"""检查四文档、链接和不该入库的文件；不访问网络。"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote


REPO_ROOT = Path(__file__).resolve().parents[3]
MARKDOWN_LINK = re.compile(r"!?(?:\[[^\]]+\])\(([^)]+)\)")
URL_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)
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


def check_local_links() -> list[str]:
    problems: list[str] = []
    for source in REPO_ROOT.rglob("*.md"):
        if ".git" in source.parts or ".venv" in source.parts:
            continue
        text = source.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK.finditer(text):
            raw = match.group(1).strip()
            if not raw or raw.startswith("#") or URL_SCHEME.match(raw):
                continue
            # 本仓库不用带 title 的链接；尖括号仅表示路径有空格。
            path_part = unquote(raw.split("#", 1)[0].strip("<>"))
            target = (source.parent / path_part).resolve()
            if not target.is_relative_to(REPO_ROOT):
                problems.append(f"{source.relative_to(REPO_ROOT)}: 链接越出仓库: {raw}")
            elif not target.exists():
                problems.append(f"{source.relative_to(REPO_ROOT)}: 找不到 {raw}")
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
