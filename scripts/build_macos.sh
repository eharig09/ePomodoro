#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
venv_path="$project_root/.venv-macos"
skip_install=0
clean=0

for argument in "$@"; do
    case "$argument" in
        --skip-install) skip_install=1 ;;
        --clean) clean=1 ;;
        *) echo "Unknown option: $argument" >&2; exit 2 ;;
    esac
done

cd "$project_root"

cloud_config="$project_root/cloud_config.json"
generated_cloud_config=0
cleanup_cloud_config() {
    if [[ "$generated_cloud_config" -eq 1 ]]; then
        rm -f "$cloud_config"
    fi
}
trap cleanup_cloud_config EXIT

if [[ ! -x "$venv_path/bin/python" ]]; then
    python3 -m venv "$venv_path"
fi

if [[ ! -f "$cloud_config" ]] &&
   [[ -n "${SUPABASE_URL:-}" || -n "${SUPABASE_PUBLISHABLE_KEY:-}" ]]; then
    if [[ -z "${SUPABASE_URL:-}" || -z "${SUPABASE_PUBLISHABLE_KEY:-}" ]]; then
        echo "Cloud builds require both SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY." >&2
        exit 1
    fi
    SUPABASE_URL="$SUPABASE_URL" SUPABASE_PUBLISHABLE_KEY="$SUPABASE_PUBLISHABLE_KEY" \
        "$venv_path/bin/python" -c 'import json, os, pathlib; pathlib.Path("cloud_config.json").write_text(json.dumps({"supabase_url": os.environ["SUPABASE_URL"], "supabase_publishable_key": os.environ["SUPABASE_PUBLISHABLE_KEY"]}), encoding="utf-8")'
    generated_cloud_config=1
fi

if [[ "$skip_install" -eq 0 ]]; then
    "$venv_path/bin/python" -m pip install --upgrade pip
    "$venv_path/bin/python" -m pip install -r requirements-build.txt
fi

pyinstaller_args=("--noconfirm")
if [[ "$clean" -eq 1 ]]; then
    pyinstaller_args+=("--clean")
fi
pyinstaller_args+=("Focus-macOS.spec")
"$venv_path/bin/python" -m PyInstaller "${pyinstaller_args[@]}"

app_path="$project_root/dist/Focus.app"
if [[ ! -d "$app_path" ]]; then
    echo "The build completed without producing dist/Focus.app" >&2
    exit 1
fi

/usr/bin/codesign --verify --deep --strict --verbose=2 "$app_path"

architecture="$(uname -m)"
dmg_path="$project_root/dist/Focus-macOS-${architecture}.dmg"
/usr/bin/hdiutil create \
    -volname "Focus" \
    -srcfolder "$app_path" \
    -ov \
    -format UDZO \
    "$dmg_path"

if [[ -n "${FOCUS_NOTARY_PROFILE:-}" ]]; then
    if [[ -z "${FOCUS_CODESIGN_IDENTITY:-}" ]]; then
        echo "FOCUS_NOTARY_PROFILE requires a Developer ID in FOCUS_CODESIGN_IDENTITY." >&2
        exit 1
    fi
    /usr/bin/xcrun notarytool submit "$dmg_path" \
        --keychain-profile "$FOCUS_NOTARY_PROFILE" \
        --wait
    /usr/bin/xcrun stapler staple "$dmg_path"
    /usr/sbin/spctl --assess --type open --context context:primary-signature --verbose=2 "$dmg_path"
else
    echo "Built with ad-hoc signing. Set FOCUS_CODESIGN_IDENTITY and FOCUS_NOTARY_PROFILE for public distribution."
fi

echo "Built $app_path"
echo "Disk image $dmg_path"
/usr/bin/shasum -a 256 "$dmg_path"
