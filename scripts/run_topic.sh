#!/usr/bin/env bash
# Run one topic from eval/data/Digital_Life_Science_Technology with both
# the proposed schema-based method and the no-schema baseline.
#
# Usage:
#   bash scripts/run_topic.sh [topic]
#     topic ... file stem under eval/data/Digital_Life_Science_Technology/
#              (default: artificial_intelligence)
#
# Output:
#   logs/Digital_Life_Science_Technology/<topic>.json
#   logs/Digital_Life_Science_Technology/no_schema/<topic>.json
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CATEGORY="Digital_Life_Science_Technology"
DATA_DIR="$ROOT/eval/data/$CATEGORY"
LOGS_DIR="$ROOT/logs/$CATEGORY"
NO_SCHEMA_LOGS_DIR="$LOGS_DIR/no_schema"
PYTHON="$ROOT/.venv/bin/python"

TOPIC="${1:-artificial_intelligence}"
TOPIC_FILE="$DATA_DIR/$TOPIC.json"

if [[ ! -x "$PYTHON" ]]; then
    echo "Python virtual environment not found: $PYTHON" >&2
    exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
    echo "jq is required but was not found in PATH." >&2
    exit 1
fi

if [[ ! -f "$TOPIC_FILE" ]]; then
    echo "Topic not found: $TOPIC_FILE" >&2
    echo "" >&2
    echo "Available topics:" >&2
    find "$DATA_DIR" -maxdepth 1 -name '*.json' -exec basename {} .json \; | sort >&2
    exit 1
fi

mkdir -p "$LOGS_DIR" "$NO_SCHEMA_LOGS_DIR"

question="$(jq -r '.question' "$TOPIC_FILE")"
agent1_stance="$(jq -r '.agent1_stance' "$TOPIC_FILE")"
agent2_stance="$(jq -r '.agent2_stance' "$TOPIC_FILE")"

run_and_move_log() {
    local mode="$1"
    local cli_path="$2"
    local destination="$3"
    local output_file
    local generated_log

    output_file="$(mktemp)"

    echo "=== [$mode][$CATEGORY] $TOPIC ==="
    if ! "$PYTHON" "$cli_path" \
        --question "$question" \
        --agent1-stance "$agent1_stance" \
        --agent2-stance "$agent2_stance" \
        2>&1 | tee "$output_file"; then
        echo "[error] $mode run failed. Console output was captured at $output_file" >&2
        exit 1
    fi

    generated_log="$(awk '/^\[system\] log saved/ { path=$NF } END { print path }' "$output_file")"
    if [[ -z "$generated_log" || ! -f "$generated_log" ]]; then
        echo "[error] could not locate generated JSON log for $mode run." >&2
        echo "Console output was captured at $output_file" >&2
        exit 1
    fi

    mv -f "$generated_log" "$destination"
    rm -f "$output_file"
    echo "Saved JSON log -> $destination"
    echo ""
}

run_and_move_log "schema" "$ROOT/src/cli.py" "$LOGS_DIR/$TOPIC.json"
run_and_move_log "no-schema" "$ROOT/src/cli_no_schema.py" "$NO_SCHEMA_LOGS_DIR/$TOPIC.json"

echo "=== Complete: $TOPIC ==="
