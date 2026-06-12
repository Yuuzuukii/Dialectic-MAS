#!/usr/bin/env bash
# eval/data 配下の全カテゴリ・全トピックについて cli を実行し、
# 結果ログを eval/logs-v2/<category>/<topic>/ に保存する全カテゴリ一括ドライバ。
#
# 使い方:
#   bash scripts/run_batch.sh [n_runs]
#     n_runs … 各トピックの実行回数（既定 1）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DATA_DIR="$ROOT/eval/data"
LOGS_DIR="$ROOT/eval/logs-v2"
PYTHON="$ROOT/.venv/bin/python"

N="${1:-1}"

if [[ ! -x "$PYTHON" ]]; then
    echo "Python virtual environment not found: $PYTHON" >&2
    exit 1
fi

if [[ ! -d "$DATA_DIR" ]]; then
    echo "Data directory not found: $DATA_DIR" >&2
    exit 1
fi

for category_dir in "$DATA_DIR"/*/; do
    category="$(basename "$category_dir")"
    # scenarios/ はカテゴリではないのでスキップ。
    [[ "$category" == "scenarios" ]] && continue

    echo "=== Category: $category ==="
    for topic_file in "$category_dir"*.json; do
        [[ -e "$topic_file" ]] || continue
        topic="$(basename "$topic_file" .json)"
        LOG_GROUP_DIR="$LOGS_DIR/$category/$topic"
        mkdir -p "$LOG_GROUP_DIR"

        question="$(jq -r '.question' "$topic_file")"
        agent1_stance="$(jq -r '.agent1_stance' "$topic_file")"
        agent2_stance="$(jq -r '.agent2_stance' "$topic_file")"

        echo "--- [$category] $topic (${N} run(s)) ---"
        for i in $(seq 1 "$N"); do
            echo "  run $i / $N"
            timestamp="$(date +%Y%m%d_%H%M%S)"
            output_file="$LOG_GROUP_DIR/$(printf '%02d' "$i")_${timestamp}.log"

            # 1トピックの失敗で全体を止めない（pipefail/set -e を局所的に無効化）。
            "$PYTHON" "$ROOT/src/cli.py" \
                --question "$question" \
                --agent1-stance "$agent1_stance" \
                --agent2-stance "$agent2_stance" \
                2>&1 | tee "$output_file" || true

            # cli が出力する「[system] log saved → <path>」から生成 JSON を特定して移動。
            generated_log="$(awk '/^\[system\] log saved/ { path=$NF } END { print path }' "$output_file")"
            if [[ -n "$generated_log" && -f "$generated_log" ]]; then
                destination="$LOG_GROUP_DIR/$(printf '%02d' "$i")_$(basename "$generated_log")"
                mv "$generated_log" "$destination"
                echo "  Moved JSON log → $destination"
            else
                echo "  [warn] could not locate generated JSON log for $category/$topic run $i" >&2
            fi
        done
    done
    echo ""
done

echo "=== All categories complete ==="
