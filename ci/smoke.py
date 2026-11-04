"""Offline contract for the static nginx application and its build context."""
import argparse
import re
import tarfile
from html.parser import HTMLParser
from pathlib import Path


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.text = {}
        self.lang = None

    def handle_starttag(self, tag, attrs):
        if tag == "html":
            self.lang = dict(attrs).get("lang")
        if tag not in {"meta", "link", "br", "hr", "img", "input"}:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag:
            raise ValueError("Unbalanced HTML")
        self.stack.pop()

    def handle_data(self, data):
        if self.stack:
            self.text.setdefault(self.stack[-1], []).append(data.strip())


def check_html(html, version):
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("Invalid version")
    page = Page()
    page.feed(html)
    page.close()
    if page.stack or page.lang != "ru":
        raise ValueError("Incomplete HTML or incorrect language")
    for tag in ("title", "h1"):
        if page.text.get(tag) != ["Netology DevOps Diploma"]:
            raise ValueError("Application heading contract failed")
    paragraphs = page.text.get("p", [])
    if "Application is running successfully!" not in paragraphs:
        raise ValueError("Application readiness text missing")
    if [p for p in paragraphs if p.startswith("Version:")] != [f"Version: {version}"]:
        raise ValueError("Application version mismatch")


def check_context(root):
    for name in ("Dockerfile", "index.html", "ci/VERSION", ".dockerignore"):
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("Missing or symlinked application input")
    version = (root / "ci/VERSION").read_text().strip()
    check_html((root / "index.html").read_text(encoding="utf-8"), version)
    instructions = [s.strip() for s in (root / "Dockerfile").read_text().splitlines()
                    if s.strip() and not s.lstrip().startswith("#")]
    if instructions != ["FROM nginx:stable-alpine", "COPY index.html /usr/share/nginx/html/index.html", "EXPOSE 80"]:
        raise ValueError("Unexpected nginx image, copy source/destination or build instruction")
    ignores = (root / ".dockerignore").read_text().splitlines()
    if ignores != ["**", "!Dockerfile", "!index.html"]:
        raise ValueError("Build context must allow only Dockerfile and index.html")
    return version


def write_context_archive(root, destination):
    """Offline allowlist archive; validates inputs, does not emulate a Docker build."""
    check_context(root)
    with tarfile.open(destination, 'x') as archive:
        for name in ('Dockerfile', 'index.html', '.dockerignore'):
            archive.add(root / name, arcname=name, recursive=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        print("Static application smoke PASS, version=" + check_context(args.root))
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Static application smoke FAIL: {exc}\n")
