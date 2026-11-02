#!/usr/bin/env bash
set -euo pipefail
OUT="${1:-build}"
mkdir -p "$OUT/wheels"
limescape-plugin requirements > "$OUT/requirements.in"
uv pip compile "$OUT/requirements.in" --generate-hashes --python-version 3.12 --python-platform x86_64-manylinux_2_28 --only-binary :all: --no-header --output-file "$OUT/bundle.lock"
python -m pip download --require-hashes --no-deps --only-binary=:all: --implementation cp --python-version 3.12 --platform manylinux_2_28_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux2014_x86_64 --platform any --abi cp312 --abi abi3 --abi none --requirement "$OUT/bundle.lock" --dest "$OUT/wheels"
echo "locked dependencies into $OUT"
