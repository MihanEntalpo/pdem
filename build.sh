#!/usr/bin/env bash
set -euo pipefail

usage() { echo "Usage: $(basename "$0") {prod|test}"; exit 2; }

[[ $# -eq 1 ]] || usage
case "$1" in
  prod) REPO="pypi" ;;
  test) REPO="testpypi" ;;
  *) usage ;;
esac

VENV="./venv"
[[ -d "$VENV" ]] || python -m venv "$VENV"
# shellcheck source=/dev/null
source "$VENV/bin/activate"

python -m pip install --upgrade pip
python -m pip install --upgrade build twine

rm -rf dist/ build/ *.egg-info
python -m build
python -m twine check dist/*

echo "Uploading to repository: $REPO"
python -m twine upload --repository "$REPO" dist/*
