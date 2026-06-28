#!/bin/bash
# UserPromptSubmit フック: メッセージに「カメラチェック」が含まれていたら
# curry_logic/camera_logic の正当性回帰テストを実行し、結果をrewakeで通知する。
prompt=$(jq -r '.prompt // empty')
if ! echo "$prompt" | grep -q 'カメラチェック'; then
  exit 0
fi

cd /Users/yuzuki/Desktop/Dialect-MAS || exit 0
output=$(.venv/bin/python src/dialogue/test_protocol_regression.py --runs 10 --quiet 2>&1)
echo "$output" > /tmp/protocol_regression_last.log
echo "$output" | tail -2
exit 2
