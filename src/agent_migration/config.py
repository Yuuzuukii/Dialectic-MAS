import os

from pydantic import SecretStr

OPENAI_API_KEY = SecretStr(os.environ["OPENAI_API_KEY"])
DIALOGUE_AGENT_MODEL = "gpt-5.4-nano"
# 攻撃の成立判定・統合・最終回答を担当する、議論に参加しないエージェントのモデル。
JUDGE_MODEL = "gpt-5.4-mini"
