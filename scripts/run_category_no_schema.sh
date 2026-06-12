#!/usr/bin/env bash
# eval/data の指定カテゴリの全トピックについて、スキーマなし版 (cli_no_schema.py) を実行し、
# 結果ログを eval/logs-v1-no-schema/<category>/<topic>/ に保存する。
#
# 使い方:
#   bash scripts/run_category_no_schema.sh <category> [n_runs]
#     <category> … eval/data 配下のカテゴリ名（省略時は一覧表示）
#     n_runs     … 各トピックの実行回数（既定 1）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOGS_DIR="$ROOT/eval/logs-v1-no-schema"
DATA_DIR="$ROOT/eval/data"
PYTHON="$ROOT/.venv/bin/python"

CATEGORY="${1:-}"
N="${2:-1}"

if [[ -z "$CATEGORY" ]]; then
    echo "Usage: $0 <category> [n_runs]" >&2
    echo "" >&2
    echo "Available categories:" >&2
    ls "$DATA_DIR" | grep -vE 'scenarios|config.json' >&2
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
    [[ -e "$topic_file" ]] || continue
    topic="$(basename "$topic_file" .json)"
    LOG_GROUP_DIR="$LOGS_DIR/$CATEGORY/$topic"
    mkdir -p "$LOG_GROUP_DIR"

    question="$(jq -r '.question' "$topic_file")"
    agent1_stance="$(jq -r '.agent1_stance' "$topic_file")"
    agent2_stance="$(jq -r '.agent2_stance' "$topic_file")"

    echo "=== [no-schema][$CATEGORY] $topic (${N} run(s)) ==="

    for i in $(seq 1 "$N"); do
        echo "--- run $i / $N ---"
        timestamp="$(date +%Y%m%d_%H%M%S)"
        output_file="$LOG_GROUP_DIR/$(printf '%02d' "$i")_${timestamp}.log"

        # 1トピックの失敗で全体を止めない。
        "$PYTHON" "$ROOT/src/cli_no_schema.py" \
            --question "$question" \
            --agent1-stance "$agent1_stance" \
            --agent2-stance "$agent2_stance" \
            2>&1 | tee "$output_file" || true

        # cli_no_schema が出力する「[system] log saved → <path>」から生成 JSON を特定して移動。
        generated_log="$(awk '/^\[system\] log saved/ { path=$NF } END { print path }' "$output_file")"
        if [[ -n "$generated_log" && -f "$generated_log" ]]; then
            destination="$LOG_GROUP_DIR/$(printf '%02d' "$i")_$(basename "$generated_log")"
            mv "$generated_log" "$destination"
            echo "Moved JSON log → $destination"
        else
            echo "[warn] could not locate generated JSON log for $CATEGORY/$topic run $i" >&2
        fi
    done
    echo ""
done

echo "=== All runs for [no-schema][$CATEGORY] complete ==="
