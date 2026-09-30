"""把当前 Desk OS 打成 Windows 安装包。

源码更新后，再运行本文件（或双击 pack.bat）即可。
PyInstaller 会收进 backend 下的全部模块和整个 frontend 目录，
所以新加的接口、页面和依赖（写进 requirements.txt 并被代码 import）会一起打进去。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
APP_DIR = ROOT / "release" / "app" / "DeskOS"
SETUP_EXE = ROOT / "release" / "DeskOS-Setup.exe"
BUILD_DIR = ROOT / "build"
NSIS_DIR = ROOT / ".tools" / "nsis"
NSIS_ZIP = ROOT / ".tools" / "nsis-3.10.zip"
NSIS_URLS = (
    "https://downloads.sourceforge.net/project/nsis/NSIS%203/3.10/nsis-3.10.zip",
    "https://sourceforge.net/projects/nsis/files/NSIS%203/3.10/nsis-3.10.zip/download",
)
NSIS_SHA256 = "fcdce3229717a2a148e7cda0ab5bdb667f39d8fb33ede1da8dabc336bd5ad110"


def _step(text: str) -> None:
    print(f"\n== {text}", flush=True)


def _python_version(exe: Path) -> tuple[int, int] | None:
    try:
        out = subprocess.check_output(
            [str(exe), "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=30,
        ).split()
        return int(out[0]), int(out[1])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def _candidate_pythons() -> list[Path]:
    found: list[Path] = []
    for name in ("python3.13", "python3.12", "python3.11", "python"):
        located = shutil.which(name)
        if located:
            found.append(Path(located))
    home = Path.home()
    roots = (
        home / ".local" / "bin",
        home / "AppData" / "Roaming" / "uv" / "python",
        home / "AppData" / "Local" / "Programs" / "Python",
    )
    for root in roots:
        if not root.is_dir():
            continue
        found.extend(root.glob("python3.*.exe"))
        found.extend(root.glob("*/python.exe"))
        found.extend(root.glob("*/*/python.exe"))
    unique: list[Path] = []
    seen: set[str] = set()
    for path in found:
        if not path.is_file():
            continue
        key = str(path.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _use_project_python() -> None:
    """用独立的 Python 3.11+ 环境打包，避免碰到系统里过旧的 python。"""
    venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
    current = _python_version(Path(sys.executable))
    if venv_python.is_file() and Path(sys.executable).resolve() == venv_python.resolve():
        if current and current >= (3, 11):
            return
        raise SystemExit(f"打包环境 Python 版本过低: {sys.version}")

    if not venv_python.is_file() or (_python_version(venv_python) or (0, 0)) < (3, 11):
        ranked: list[tuple[tuple[int, int, int], Path]] = []
        for path in _candidate_pythons():
            version = _python_version(path)
            if not version or version < (3, 11):
                continue
            text = str(path).lower()
            standalone = 1 if ("\\uv\\" in text or "\\.local\\" in text) else 0
            ranked.append(((version[0], version[1], standalone), path))
        if not ranked:
            raise SystemExit("没有找到 Python 3.11 或更新版本，无法打包。")
        base = max(ranked)[1]
        if venv_python.parent.parent.exists():
            shutil.rmtree(venv_python.parent.parent)
        _step(f"创建打包环境（基于 {base}）")
        subprocess.check_call([str(base), "-m", "venv", str(ROOT / ".venv")], cwd=ROOT)
    print(f"改用打包环境: {venv_python}", flush=True)
    raise SystemExit(subprocess.call([str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]]))


def _run(args: list[str]) -> None:
    print(" ".join(args), flush=True)
    subprocess.check_call(args, cwd=ROOT)


def _install_deps() -> None:
    _step("安装依赖和 PyInstaller")
    _run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "pyinstaller"])


def _build_app() -> None:
    _step("按当前源码打包程序")
    if APP_DIR.exists():
        shutil.rmtree(APP_DIR)
    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onedir",
        "--noupx",
        "--name",
        "DeskOS",
        "--distpath",
        str(ROOT / "release" / "app"),
        "--workpath",
        str(BUILD_DIR / "pyinstaller"),
        "--specpath",
        str(BUILD_DIR),
        "--paths",
        str(ROOT),
        "--add-data",
        f"{ROOT / 'frontend'}{os.pathsep}frontend",
        "--exclude-module",
        "webview.platforms.android",
        "--exclude-module",
        "webview.platforms.cocoa",
        "--exclude-module",
        "webview.platforms.gtk",
        "--exclude-module",
        "webview.platforms.qt",
        "--collect-submodules",
        "backend",
        "--collect-submodules",
        "uvicorn",
        "--collect-submodules",
        "fastapi",
        "--collect-submodules",
        "starlette",
        "--collect-all",
        "webview",
        "--collect-all",
        "pythonnet",
        "--collect-all",
        "certifi",
        "--hidden-import",
        "clr",
        "--hidden-import",
        "clr_loader",
        "main.py",
    ]
    _run(args)
    exe = APP_DIR / "DeskOS.exe"
    if not exe.is_file():
        raise SystemExit(f"没有生成 {exe}")


def _pack_check() -> None:
    _step("检查打包结果（不打开窗口）")
    exe = APP_DIR / "DeskOS.exe"
    completed = subprocess.run([str(exe), "--pack-check"], cwd=APP_DIR, timeout=120)
    if completed.returncode != 0:
        log = Path(os.environ.get("LOCALAPPDATA", "")) / "DeskOS" / "desk_os.log"
        detail = ""
        if log.is_file():
            detail = "\n" + "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-40:])
        raise SystemExit(f"打包自检失败，退出码 {completed.returncode}。{detail}")
    print("自检通过", flush=True)


def _copy_sqlite(src: Path, dst: Path) -> None:
    """用 SQLite 备份复制数据库，避免程序开着时拷到一半。"""
    import sqlite3

    tmp = dst.with_name(dst.name + ".partial")
    if tmp.exists():
        tmp.unlink()
    source = sqlite3.connect(f"file:{src.resolve().as_posix()}?mode=ro", uri=True)
    try:
        target = sqlite3.connect(tmp)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    os.replace(tmp, dst)


def _seed_user_data() -> None:
    """把仓库 data 里还没有的文件补到安装后的数据目录。已有文件不覆盖。"""
    src = ROOT / "data"
    local = os.environ.get("LOCALAPPDATA", "")
    if not local or not src.is_dir():
        return
    dst = Path(local) / "DeskOS" / "data"
    dst.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for path in sorted(src.iterdir()):
        if not path.is_file():
            continue
        if path.name.endswith((".db-shm", ".db-wal", ".pyc", ".partial")):
            continue
        target = dst / path.name
        if target.exists():
            continue
        try:
            if path.suffix == ".db":
                print(f"正在复制 {path.name}（{path.stat().st_size / (1024 * 1024):.0f} MB）", flush=True)
                _copy_sqlite(path, target)
            else:
                partial = target.with_suffix(target.suffix + ".partial")
                shutil.copy2(path, partial)
                os.replace(partial, target)
        except OSError as exc:
            print(f"复制 {path.name} 没有成功，安装包仍会继续生成：{exc}", flush=True)
            continue
        copied.append(path.name)
    if copied:
        print(f"已补到 {dst}: {', '.join(copied)}", flush=True)
        print("之后重新打包不会覆盖这里已有的文件。", flush=True)
        return
    print(f"本机数据已在 {dst}，本次不覆盖。", flush=True)


def _find_makensis() -> Path | None:
    found = shutil.which("makensis")
    if found:
        return Path(found)
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "NSIS" / "makensis.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "NSIS" / "makensis.exe",
    ]
    candidates.extend(NSIS_DIR.rglob("makensis.exe"))
    for path in candidates:
        if path.is_file():
            return path
    return None


def _download_nsis() -> None:
    NSIS_ZIP.parent.mkdir(parents=True, exist_ok=True)
    if NSIS_ZIP.is_file() and hashlib.sha256(NSIS_ZIP.read_bytes()).hexdigest() == NSIS_SHA256:
        return
    last_error = "未知错误"
    for url in NSIS_URLS:
        try:
            print(f"下载 NSIS: {url}", flush=True)
            request = Request(url, headers={"User-Agent": "DeskOS-pack/1.0"})
            with urlopen(request, timeout=120) as response:
                NSIS_ZIP.write_bytes(response.read())
            digest = hashlib.sha256(NSIS_ZIP.read_bytes()).hexdigest()
            if digest != NSIS_SHA256:
                last_error = f"校验和不匹配: {digest}"
                NSIS_ZIP.unlink(missing_ok=True)
                continue
            return
        except Exception as exc:
            last_error = str(exc)
    raise SystemExit(f"下载 NSIS 失败: {last_error}")


def _ensure_makensis() -> Path:
    found = _find_makensis()
    if found:
        return found
    _step("准备安装包工具 NSIS")
    _download_nsis()
    NSIS_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(NSIS_ZIP) as archive:
        archive.extractall(NSIS_DIR)
    found = _find_makensis()
    if not found:
        raise SystemExit("解压后没有找到 makensis.exe")
    return found


def _write_nsi(version: str) -> Path:
    payload = APP_DIR
    script = f"""Unicode True
SetCompressor /SOLID lzma
!include "MUI2.nsh"

!define APP_NAME "Desk OS"
!define APP_EXE "DeskOS.exe"
!define APP_VERSION "{version}"

Name "${{APP_NAME}}"
OutFile "{_nsis_path(SETUP_EXE)}"
InstallDir "$LOCALAPPDATA\\Programs\\DeskOS"
InstallDirRegKey HKCU "Software\\DeskOS" "InstallDir"
RequestExecutionLevel user
ShowInstDetails show
BrandingText "Desk OS"

!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "安装 Desk OS"
!define MUI_WELCOMEPAGE_TEXT "将安装当前这一版 Desk OS。$\\r$\\n$\\r$\\n以后程序更新了，重新运行 pack.bat 生成新的安装包，再安装一次即可。原来的记录会保留。"
!define MUI_FINISHPAGE_TITLE "安装完成"
!define MUI_FINISHPAGE_TEXT "Desk OS 已安装。$\\r$\\n$\\r$\\n个人数据单独保存在本机，之后重新安装不会清掉。"
!define MUI_FINISHPAGE_RUN "$INSTDIR\\${{APP_EXE}}"
!define MUI_FINISHPAGE_RUN_TEXT "立即启动 Desk OS"
!define MUI_UNCONFIRMPAGE_TEXT_TOP "将移除 Desk OS 程序。本机保存的记录会留下来。"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "SimpChinese"

Section "主程序"
  ExecWait '"$SYSDIR\\taskkill.exe" /F /IM "${{APP_EXE}}"' $0
  ClearErrors
  RMDir /r "$INSTDIR\\_internal"
  Delete "$INSTDIR\\${{APP_EXE}}"
  ClearErrors
  SetOutPath "$INSTDIR"
  File /r "{_nsis_path(payload)}\\*.*"
  WriteUninstaller "$INSTDIR\\Uninstall.exe"
  WriteRegStr HKCU "Software\\DeskOS" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\DeskOS" "DisplayName" "${{APP_NAME}}"
  WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\DeskOS" "DisplayVersion" "${{APP_VERSION}}"
  WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\DeskOS" "Publisher" "Desk OS"
  WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\DeskOS" "UninstallString" '"$INSTDIR\\Uninstall.exe"'
  WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\DeskOS" "InstallLocation" "$INSTDIR"
  WriteRegDWORD HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\DeskOS" "NoModify" 1
  WriteRegDWORD HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\DeskOS" "NoRepair" 1
  CreateDirectory "$SMPROGRAMS\\Desk OS"
  CreateShortcut "$SMPROGRAMS\\Desk OS\\Desk OS.lnk" "$INSTDIR\\${{APP_EXE}}"
  CreateShortcut "$SMPROGRAMS\\Desk OS\\卸载 Desk OS.lnk" "$INSTDIR\\Uninstall.exe"
  CreateShortcut "$DESKTOP\\Desk OS.lnk" "$INSTDIR\\${{APP_EXE}}"
SectionEnd

Section "Uninstall"
  ExecWait '"$SYSDIR\\taskkill.exe" /F /IM "${{APP_EXE}}"' $0
  ClearErrors
  RMDir /r "$INSTDIR\\_internal"
  Delete "$INSTDIR\\${{APP_EXE}}"
  Delete "$INSTDIR\\Uninstall.exe"
  RMDir "$INSTDIR"
  Delete "$DESKTOP\\Desk OS.lnk"
  Delete "$SMPROGRAMS\\Desk OS\\Desk OS.lnk"
  Delete "$SMPROGRAMS\\Desk OS\\卸载 Desk OS.lnk"
  RMDir "$SMPROGRAMS\\Desk OS"
  DeleteRegKey HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\DeskOS"
  DeleteRegKey HKCU "Software\\DeskOS"
SectionEnd
"""
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    path = BUILD_DIR / "desk_os.nsi"
    path.write_text(script, encoding="utf-8-sig")
    return path


def _nsis_path(path: Path) -> str:
    return str(path.resolve()).replace("$", "$$")


def _build_installer(version: str) -> None:
    _step("生成安装程序")
    SETUP_EXE.parent.mkdir(parents=True, exist_ok=True)
    makensis = _ensure_makensis()
    nsi = _write_nsi(version)
    _run([str(makensis), "/INPUTCHARSET", "UTF8", str(nsi)])
    if not SETUP_EXE.is_file() or SETUP_EXE.stat().st_size < 1024 * 1024:
        raise SystemExit(f"安装包没有生成: {SETUP_EXE}")
    if SETUP_EXE.read_bytes()[:2] != b"MZ":
        raise SystemExit("安装包不是有效的 Windows 程序")


def main() -> None:
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.chdir(ROOT)
    _use_project_python()
    version = datetime.now().strftime("%Y.%m.%d.%H%M")
    print(f"Desk OS 打包 {version}", flush=True)
    _install_deps()
    _build_app()
    _seed_user_data()
    _pack_check()
    _build_installer(version)
    size_mb = SETUP_EXE.stat().st_size / (1024 * 1024)
    print(
        f"\n安装包已生成: {SETUP_EXE} ({size_mb:.0f} MB)\n"
        "双击它即可安装。以后改了程序，再双击 pack.bat 就会按最新代码重新打包。",
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc
