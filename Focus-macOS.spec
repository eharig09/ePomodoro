import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata


project_root = Path(SPECPATH)
target_arch = os.getenv("FOCUS_MAC_ARCH", "").strip() or None
codesign_identity = os.getenv("FOCUS_CODESIGN_IDENTITY", "").strip() or None

streamlit_data, streamlit_binaries, streamlit_hidden = collect_all("streamlit")
keyring_data, keyring_binaries, keyring_hidden = collect_all("keyring")

datas = [
    (str(project_root / "app.py"), "."),
    (str(project_root / ".streamlit" / "config.toml"), ".streamlit"),
]
for folder in ("app_pages", "components", "database", "services"):
    for source in (project_root / folder).glob("*.py"):
        datas.append((str(source), folder))

datas += streamlit_data + keyring_data
datas += copy_metadata("streamlit")
datas += copy_metadata("todoist-api-python")
datas += copy_metadata("keyring")

hiddenimports = streamlit_hidden + keyring_hidden
for package in (
    "app_pages",
    "components",
    "database",
    "services",
    "todoist_api_python",
    "keyring.backends",
):
    hiddenimports += collect_submodules(package)

a = Analysis(
    [str(project_root / "macos_launcher.py")],
    pathex=[str(project_root)],
    binaries=streamlit_binaries + keyring_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Focus",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=target_arch,
    codesign_identity=codesign_identity,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Focus",
)

app = BUNDLE(
    coll,
    name="Focus.app",
    icon=None,
    bundle_identifier="com.focusproductivity.desktop",
    version="1.0.0",
    info_plist={
        "CFBundleDisplayName": "Focus",
        "CFBundleName": "Focus",
        "NSHighResolutionCapable": True,
        "NSPrincipalClass": "NSApplication",
    },
)
