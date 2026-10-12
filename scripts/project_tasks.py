from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from pic_timeline.public_package import pack_public_data


STUDIO_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ROOT = STUDIO_ROOT / "apps" / "public-ui"

if os.name == "nt":
    ctypes.windll.kernel32.SetConsoleOutputCP(65001)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def _run(command: list[str], *, cwd: Path) -> None:
    print(f"\n[{cwd.name}] {' '.join(command)}", flush=True)
    environment = os.environ.copy()
    environment.update(
        {
            "FORCE_COLOR": "0",
            "NO_COLOR": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }
    )
    environment["PYTHON"] = sys.executable
    subprocess.run(command, cwd=cwd, check=True, env=environment)


def _npm() -> str:
    executable = shutil.which("npm")
    if executable is None:
        raise FileNotFoundError("找不到 npm，请先运行 pixi install")
    return executable


def _require_public_repo() -> None:
    if not (PUBLIC_ROOT / "package.json").is_file():
        raise FileNotFoundError(f"静态前端源码不存在：{PUBLIC_ROOT}")


def _run_public(*command: str) -> None:
    _require_public_repo()
    executable = _npm() if command[0] == "npm" else command[0]
    _run([executable, *command[1:]], cwd=PUBLIC_ROOT)


def _ensure_node_modules(root: Path, *, public: bool = False) -> None:
    lockfile = root / "package-lock.json"
    install_marker = root / "node_modules" / ".package-lock.json"
    if install_marker.is_file() and install_marker.stat().st_mtime >= lockfile.stat().st_mtime:
        return
    if public:
        _run_public("npm", "install")
    else:
        _run([_npm(), "install"], cwd=root)


def _studio_frontend_is_stale() -> bool:
    output = STUDIO_ROOT / "apps" / "local-ui" / "dist" / "index.html"
    if not output.is_file():
        return True
    inputs = [
        STUDIO_ROOT / "package-lock.json",
        STUDIO_ROOT / "package.json",
        STUDIO_ROOT / "apps" / "local-ui" / "package.json",
        STUDIO_ROOT / "apps" / "local-ui" / "vite.config.ts",
    ]
    inputs.extend((STUDIO_ROOT / "apps" / "local-ui" / "src").rglob("*"))
    latest_input = max(path.stat().st_mtime for path in inputs if path.is_file())
    return latest_input > output.stat().st_mtime


def run_app(arguments: list[str]) -> None:
    _ensure_node_modules(STUDIO_ROOT)
    if _studio_frontend_is_stale():
        _run([_npm(), "run", "build"], cwd=STUDIO_ROOT)
    _run([sys.executable, "-m", "pic_timeline.web", *arguments], cwd=STUDIO_ROOT)


def test_all() -> None:
    _ensure_node_modules(STUDIO_ROOT)
    _require_public_repo()
    _ensure_node_modules(PUBLIC_ROOT, public=True)
    (STUDIO_ROOT / ".pytest_tmp").mkdir(parents=True, exist_ok=True)
    _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests",
            f"--basetemp=.pytest_tmp/run-{os.getpid()}-{time.time_ns()}",
            "--ignore=tests/_tmp",
            "--ignore=tests/.runtime_tmp",
            "--ignore=exports",
        ],
        cwd=STUDIO_ROOT,
    )
    _run([_npm(), "run", "test:web"], cwd=STUDIO_ROOT)
    _run([_npm(), "run", "build"], cwd=STUDIO_ROOT)
    _run_public(sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py")
    _run_public("npm", "test")
    _prepare_demo()
    _run_public("npm", "run", "build")
    _run_public("npm", "run", "audit")
    print("\n全部测试、构建和公开产物审计均已通过。", flush=True)


def _prepare_demo() -> None:
    public_data = PUBLIC_ROOT / "public" / "data"
    public_data.mkdir(parents=True, exist_ok=True)
    for source in (PUBLIC_ROOT / "demo" / "data").glob("*.json"):
        target = public_data / source.name
        if not target.exists():
            shutil.copy2(source, target)


def release_local(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(description="生成本地公开数据包与静态网站，不上传")
    parser.add_argument("--base", default="/Moments/", help="静态网站路径，默认 /Moments/；自定义域名可用 /")
    parser.add_argument("--index", type=Path, default=Path("data/photo_index.sqlite3"))
    parser.add_argument("--annotations", type=Path, default=Path("data/annotations.sqlite3"))
    args = parser.parse_args(arguments)
    total_steps = 5

    def step(number: int, label: str) -> None:
        print(f"\n[release {number}/{total_steps}] {label}", flush=True)

    step(1, "检查内置公开前端和依赖")
    _require_public_repo()
    _ensure_node_modules(PUBLIC_ROOT, public=True)
    step(2, "生成脱敏 JSON 与 WebP")
    _run(
        [sys.executable, "-m", "pic_timeline.export_public",
         "--index", str(args.index.resolve()),
         "--annotations", str(args.annotations.resolve())],
        cwd=STUDIO_ROOT,
    )
    step(3, "导入公开数据包并定位城市")
    _run_public("npm", "run", "import-data")
    step(4, "构建静态网站")
    _run_public("npm", "run", "build", "--", "--base", args.base)
    step(5, "审计并打包本地公开产物")
    _run_public("npm", "run", "audit")
    exports = STUDIO_ROOT / "exports"
    site = exports / "site"
    if site.exists():
        shutil.rmtree(site)
    shutil.copytree(PUBLIC_ROOT / "dist", site)
    shutil.make_archive(str(exports / "site"), "zip", site)
    checksum = pack_public_data(exports / "public-data", exports / "public-data.zip")
    print(
        f"\n本地 release 完成：exports/site/、site.zip、public-data.zip 和 {checksum.name}。"
        "未执行 Git 提交、推送、Release 上传或 GitHub Pages 发布。",
        flush=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Moments 统一任务入口")
    parser.add_argument("command", choices=("app", "test", "release"))
    args, remaining = parser.parse_known_args()
    if remaining[:1] == ["--"]:
        remaining = remaining[1:]
    if args.command == "app":
        run_app(remaining)
    elif args.command == "test":
        test_all()
    else:
        release_local(remaining)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
