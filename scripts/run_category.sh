#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOGS_DIR="$ROOT/eval/logs-v1"
DATA_DIR="$ROOT/eval/data"
PYTHON="$ROOT/.venv/bin/python"

CATEGORY="${1:-}"
N="${2:-1}"

if [[ -z "$CATEGORY" ]]; then
    echo "Usage: $0 <category> [n_runs]" >&2
    echo "" >&2
    echo "Available categories:" >&2
    ls "$DATA_DIR" | grep -v scenarios >&2
    exit 1
fi

CATEGORY_DIR="$DATA_DIR/$CATEGORY"
if [[ ! -d "$CATEGORY_DIR" ]]; then
    echo "Category not found: $CATEGORY_DIR" >&2
    exit 1
fi

if [[ ! -x "$PYTHON" ]]; then
    echo "Python virtual environment not found: $PYTHON" >&2
    exit 1
fi

for topic_file in "$CATEGORY_DIR"/*.json; do
    topic="$(basename "$topic_file" .json)"
    LOG_GROUP_DIR="$LOGS_DIR/$CATEGORY/$topic"
    mkdir -p "$LOG_GROUP_DIR"

    question="$(jq -r '.question' "$topic_file")"
    agent1_stance="$(jq -r '.agent1_stance' "$topic_file")"
    agent2_stance="$(jq -r '.agent2_stance' "$topic_file")"

    echo "=== [$CATEGORY] $topic (${N} run(s)) ==="

    for i in $(seq 1 "$N"); do
        echo "--- run $i / $N ---"
        timestamp="$(date +%Y%m%d_%H%M%S)"
        output_file="$LOG_GROUP_DIR/$(printf '%02d' "$i")_${timestamp}.log"

        pipe_dir="$(mktemp -d)"
        output_pipe="$pipe_dir/cli-output"
        mkfifo "$output_pipe"

        "$PYTHON" "$ROOT/src/cli.py" \
            --question "$question" \
            --agent1-stance "$agent1_stance" \
            --agent2-stance "$agent2_stance" \
            >"$output_pipe" 2>&1 &
        cli_pid="$!"

        while IFS= read -r line; do
            printf '%s\n' "$line" | tee -a "$output_file"
        done <"$output_pipe"

        wait "$cli_pid" 2>/dev/null || true
        rm "$output_pipe"
        rmdir "$pipe_dir"

        generated_log="$(awk '/^\[system\] log saved/ { path=$NF } END { print path }' "$output_file")"
        if [[ -n "$generated_log" && -f "$generated_log" ]]; then
            destination="$LOG_GROUP_DIR/$(printf '%02d' "$i")_$(basename "$generated_log")"
            mv "$generated_log" "$destination"
            echo "Moved JSON log → $destination"
        fi

        echo "Saved output log → $output_file"
    done
    echo ""
done

echo "=== All runs for [$CATEGORY] complete ==="
