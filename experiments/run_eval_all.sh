#!/usr/bin/env bash
# 実験フォルダ（logs/experiment_<日時>）の全ターン数について、LLM を使う評価を順に実行する.
#   1. atomic coverage（最終回答）
#   2. SVI（--trials 3: トピック x 手法の組ごとに 3 回分）
#   3. 議論全体のカバレッジ（負けた主張を含む）
# 結果は <実験フォルダ>/turns<N>/eval_result/ に保存される。
# グラフ（日本語フォント Hiragino が要る）と dialogue tree は、手元の Mac で
#   plot_summary / plot_atomic_coverage / plot_svi_consensus_score / plot_argument_network
# を実行する（費用はかからない）。
#
# SKIP_DIALOGUE_COVERAGE=1 を付けると、3 の議論全体のカバレッジを省く（coverage と SVI だけ）。
#
# Usage: bash experiments/run_eval_all.sh logs/experiment_<日時> [trials]
set -euo pipefail

EXP="${1:?usage: bash experiments/run_eval_all.sh logs/experiment_<日時> [trials]}"
TRIALS="${2:-3}"
cd "$(dirname "$0")/.."
PY="${PYTHON:-python}"

[ -d "$EXP" ] || { echo "実験フォルダが見つかりません: $EXP" >&2; exit 1; }

# coverage の項目分割は spaCy の英語モデルを使う。pyproject には含まれないので、無ければ入れる。
if ! "$PY" -c "import spacy; spacy.load('en_core_web_sm')" 2>/dev/null; then
  echo "[setup] spaCy の en_core_web_sm を導入します"
  uv pip install --python "$PY" \
    "https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"
fi

n_logs=$(find "$EXP" -path '*raw_dialogue*' -name '*.json' | wc -l | tr -d ' ')
echo "[info] $EXP: ${n_logs} logs"

for dir in "$EXP"/turns*/; do
  t="$(basename "$dir")"
  t="${t#turns}"
  base="$EXP/turns$t"
  [ -d "$base/raw_dialogue" ] || continue
  echo "===== turns$t: atomic coverage ====="
  "$PY" -m experiments.eval.runners.eval_atomic_coverage_final \
    --base-dir "$base/raw_dialogue" \
    --out "$base/eval_result/atomic_coverage/atomic_coverage_comparison.json"
  echo "===== turns$t: SVI ====="
  "$PY" -m experiments.eval.runners.eval_svi_final --trials "$TRIALS" \
    --base-dir "$base/raw_dialogue" \
    --out "$base/eval_result/svi/questionnaire_result/svi_comparison.json"
  if [ -z "${SKIP_DIALOGUE_COVERAGE:-}" ]; then
    echo "===== turns$t: dialogue coverage ====="
    "$PY" -m experiments.eval.runners.eval_dialogue_coverage \
      --base-dir "$base/raw_dialogue" \
      --out "$base/eval_result/dialogue_coverage/dialogue_coverage_comparison.json"
  fi
done
echo "[done] 評価が終わりました: $EXP"
