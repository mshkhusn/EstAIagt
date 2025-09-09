# movie_app.py (Gemini 2.5 Flash 専用テスト版)
import os
import re
import json
from io import BytesIO
from datetime import date
import ast
from typing import Optional

import streamlit as st
import pandas as pd
import google.generativeai as genai

# =========================
# ページ設定
# =========================
st.set_page_config(page_title="映像制作概算見積エージェント（Gemini 2.5 Flash 専用）", layout="centered")

# =========================
# Secrets
# =========================
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
APP_PASSWORD   = st.secrets["APP_PASSWORD"]

if not GEMINI_API_KEY:
    st.error("GEMINI_API_KEY が設定されていません。st.secrets を確認してください。")
    st.stop()

genai.configure(api_key=GEMINI_API_KEY)

# =========================
# 定数
# =========================
TAX_RATE = 0.10
MGMT_FEE_CAP_RATE = 0.15
RUSH_K = 0.75
GEMINI_MODEL_ID = "gemini-2.5-flash"

# =========================
# セッション
# =========================
for k in ["items_json_raw", "items_json", "df", "meta", "final_html", "model_used"]:
    if k not in st.session_state:
        st.session_state[k] = None

# =========================
# 認証
# =========================
st.title("映像制作概算見積エージェント（Gemini 2.5 Flash 専用）")
password = st.text_input("パスワードを入力してください", type="password")
if password != APP_PASSWORD:
    st.warning("🔒 認証が必要です")
    st.stop()

# =========================
# 入力
# =========================
st.header("制作条件の入力")
video_duration = st.selectbox("尺の長さ", ["15秒", "30秒", "60秒"])
num_versions = st.number_input("納品本数", min_value=1, max_value=10, value=1)
shoot_days = st.number_input("撮影日数", min_value=1, max_value=10, value=2)
edit_days = st.number_input("編集日数", min_value=1, max_value=10, value=3)
delivery_date = st.date_input("納品希望日", value=date.today())

extra_notes = st.text_area("備考（案件概要など自由記入）")

# =========================
# ユーティリティ
# =========================
def robust_parse_items_json(raw: str) -> str:
    """コードフェンス除去＋JSON復元"""
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(json)?", "", s, flags=re.IGNORECASE).strip("`\n ")
    try:
        return json.dumps(json.loads(s), ensure_ascii=False)
    except Exception:
        return json.dumps({"items": []}, ensure_ascii=False)

def _robust_extract_gemini_text(resp) -> str:
    try:
        if getattr(resp, "text", None):
            return resp.text
    except Exception:
        pass
    try:
        cands = getattr(resp, "candidates", None) or []
        buf = []
        for c in cands:
            content = getattr(c, "content", None)
            if not content:
                continue
            parts = getattr(content, "parts", None) or []
            for p in parts:
                t = getattr(p, "text", None)
                if t:
                    buf.append(t)
        if buf:
            return "".join(buf)
    except Exception:
        pass
    try:
        return json.dumps(resp.to_dict(), ensure_ascii=False)
    except Exception:
        return ""

def _gemini25_model():
    return genai.GenerativeModel(
        GEMINI_MODEL_ID,
        generation_config={
            "candidate_count": 1,
            "temperature": 0.3,
            "top_p": 0.9,
            "max_output_tokens": 2500,
        },
    )

def llm_generate_items_json(prompt: str) -> str:
    try:
        model = _gemini25_model()
        resp = model.generate_content(prompt)
        raw = _robust_extract_gemini_text(resp)

        if not raw.strip():
            chat = model.start_chat(history=[])
            resp2 = chat.send_message(prompt)
            raw = _robust_extract_gemini_text(resp2)

        if not raw.strip():
            raw = '{"items":[{"category":"管理費","task":"管理費（固定）","qty":1,"unit":"式","unit_price":0,"note":""}]}'

        st.session_state["items_json_raw"] = raw
        st.session_state["model_used"] = GEMINI_MODEL_ID
        return robust_parse_items_json(raw)
    except Exception as e:
        st.warning(f"⚠️ Gemini呼び出し失敗: {e}")
        return json.dumps({"items": []}, ensure_ascii=False)

# =========================
# プロンプト
# =========================
def build_prompt_json() -> str:
    return f"""
必ず JSON のみを返してください。

案件条件:
- 尺: {video_duration}
- 本数: {num_versions}
- 撮影日数: {shoot_days}
- 編集日数: {edit_days}
- 納品希望日: {delivery_date.isoformat()}
- 備考: {extra_notes}

出力仕様:
- ルートは items 配列。
- 各要素キー: category, task, qty, unit, unit_price, note
- 管理費は固定1行 (task=管理費（固定）, qty=1, unit=式)。
"""

# =========================
# 実行
# =========================
if st.button("💡 見積もりを作成"):
    with st.spinner("Gemini 2.5 Flash が見積もりを生成中…"):
        prompt = build_prompt_json()
        items_json_str = llm_generate_items_json(prompt)

        try:
            data = json.loads(items_json_str)
            df = pd.DataFrame(data.get("items", []))
        except Exception:
            st.error("JSON解析に失敗しました。")
            st.stop()

        st.session_state["items_json"] = items_json_str
        st.session_state["df"] = df

# =========================
# 表示
# =========================
if st.session_state["df"] is not None:
    st.write("✅ 生成結果 (Gemini 2.5 Flash)")
    st.dataframe(st.session_state["df"])
    with st.expander("RAW出力", expanded=False):
        st.code(st.session_state["items_json_raw"])
