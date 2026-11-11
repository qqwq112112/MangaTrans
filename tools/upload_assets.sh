#!/usr/bin/env bash
# Upload release assets one by one with retries.
# gh aborts the whole `release create` when a single asset times out, so each
# file is pushed separately: a stall only costs one retry, not the release.
set -uo pipefail

export GH_TOKEN=$(powershell -NoProfile -Command \
  "[Environment]::GetEnvironmentVariable('GH_TOKEN','Machine')" | tr -d '\r\n')

GH=/d/GitHubCLI/gh.exe
REPO=qqwq112112/MangaTrans
TAG=v1.0.0
DIR=/d/MangaTrans/release-assets
MAX_TRY=3

cd "$DIR" || exit 1

# Already-uploaded names, so a re-run skips them.
mapfile -t HAVE < <("$GH" api "repos/$REPO/releases/tags/$TAG/assets?per_page=100" \
  --jq '.[] | select(.state=="uploaded") | .name' 2>/dev/null)

uploaded=0
skipped=0
failed=()

for f in *.part*.txt; do
    if printf '%s\n' "${HAVE[@]}" | grep -qxF "$f"; then
        echo "  [skip] $f"
        skipped=$((skipped + 1))
        continue
    fi

    ok=0
    for try in $(seq 1 $MAX_TRY); do
        printf "  [%d/%d] %-52s " "$try" "$MAX_TRY" "$f"
        if "$GH" release upload "$TAG" --repo "$REPO" --clobber "$f" >/dev/null 2>&1; then
            echo "OK"
            ok=1
            uploaded=$((uploaded + 1))
            break
        fi
        echo "retry"
        sleep 3
    done

    if [ "$ok" -eq 0 ]; then
        echo "  [FAIL] $f"
        failed+=("$f")
    fi
done

echo
echo "上传 $uploaded 个，跳过 $skipped 个，失败 ${#failed[@]} 个"
if [ ${#failed[@]} -gt 0 ]; then
    printf '  失败: %s\n' "${failed[@]}"
    exit 1
fi
