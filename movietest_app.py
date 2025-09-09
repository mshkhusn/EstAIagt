# app_gemini25_test.py
# =============================================
# Gemini 2.5 疎通テスター（2.0へ自動フォールバック）
# - まずはテキストのみで 2.5 が通るか確認する最小実装
# - 既存 requirements.txt は「いまのまま」でOK（まずは試す）
# - 環境変数 GEMINI_API_KEY を設定してデプロイしてください
# =============================================

import os
import time
import json
from typing import Optional, Dict, Any

import streamlit as st
import google.generativeai as genai


# ============ 初期設定 ============
API_KEY = os.getenv("GEMINI_API_KEY", "")
st.set_page_config(page_title="Gemini 2.5 テスト", page_icon="🧪", layout="wide")

if not API_KEY:
    st.error("環境変数 GEMINI_API_KEY が未設定です。Streamlit Cloud の Secrets 等で設定してください。")
    st.stop()

genai.configure(api_key=API_KEY)

MODEL_CHOICES = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
]
DEFAULT_MODEL = "gemini-2.5-flash"
FALLBACK_MODEL = "gemini-2.0-flash"  # 2.5 が落ちたらここへ


# ============ ページ/サイドバー UI ============
st.title("🧪 Gemini 2.5 テスター（自動フォールバック付き）")

with st.sidebar:
    st.subheader("モデル選択")
    model_name = st.selectbox("モデル", MODEL_CHOICES, index=MODEL_CHOICES.index(DEFAULT_MODEL))
    st.caption("2.5 が不安定な場合は 2.0 Flash を選択してください。")

    st.subheader("応答設定（任意）")
    max_output_tokens = st.number_input("max_output_tokens", min_value=64, max_value=8192, value=1024, step=64)
    temperature = st.slider("temperature", min_value=0.0, max_value=2.0, value=0.6, step=0.1)

    force_json = st.toggle("JSON 形式での出力を促す（system相当のヒントを前置）", value=False)

st.write(
    "1) テキストのみで 2.5 を実行 → 成功するか確認\n"
    "2) 失敗時は 2.0 に自動フォールバック（結果エリアに表示）\n"
    "3) 安定を確認後、既存アプリへ段階的に統合（Excel 出力は別関数化がおすすめ）"
)

prompt = st.text_area(
    "プロンプト",
    "2.5 が正常応答するかの動作確認用テキスト。必要なら具体例を書いてください。",
    height=180,
)

col_run, col_clear = st.columns([1, 1])
