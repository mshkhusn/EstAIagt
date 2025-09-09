# app.py（最小再現：Gemini 2.5 Flash 単体テスト）
# 依存: streamlit, google-generativeai
# Secrets: GEMINI_API_KEY（必須）, APP_PASSWORD（任意）

import json
import streamlit as st
import google.generativeai as genai

st.set_page_config(page_title="Gemini 2.5 Flash 最小テスト", layout="centered")

# ---- Secrets ----
API_KEY = st.secrets.get("GEMINI_API_KEY", "")
APP_PASSWORD = st.secrets.get("APP_PASSWORD", "")

if not API_KEY:
    st.error("GEMINI_API_KEY が設定されていません。Streamlit の Secrets を確認してください。")
    st.stop()

# 任意の簡易パスワード（空ならスキップ）
if APP_PASSWORD:
    pw = st.text_input("パスワード", type="password")
    if pw != APP_PASSWORD:
        st.warning("🔒 認証が必要です")
        st.stop()

# ---- Gemini 初期化 & モデル ----
genai.configure(api_key=API_KEY)
MODEL_ID = "gemini-2.5-flash"

def _mk_model_simple():
    # 最小構成（MIME/Schema 指定なし。まずはこれが通るか確認）
    return genai.GenerativeModel(
        MODEL_ID,
        generation_config={
            "candidate_count": 1,
            "temperature": 0.2,
            "top_p": 0.9,
            "max_output_tokens": 1024,
        },
    )

st.title("Gemini 2.5 Flash 最小テスト")
prompt = st.text_area("プロンプト", "必ず JSON だけ返してください: {\"ok\": true}")
col1, col2, col3 = st.columns(3)

if col1.button("① generate_content(文字列)"):
    try:
        m = _mk_model_simple()
        r = m.generate_content(prompt)
        st.success("OK: generate_content(str)")
        st.subheader("text")
        st.code((r.text or "").strip() or "(空)")
        st.subheader("to_dict()")
        st.code(json.dumps(r.to_dict(), ensure_ascii=False, indent=2), language="json")
    except Exception as e:
        st.error(f"{type(e).__name__}: {e}")

if col2.button("② generate_content(role/parts)"):
    try:
        m = _mk_model_simple()
        req = [{"role": "user", "parts": [prompt]}]  # SDKの推奨形式
        r = m.generate_content(req)
        st.success("OK: generate_content(role/parts)")
        st.subheader("text")
        st.code((r.text or "").strip() or "(空)")
        st.subheader("to_dict()")
        st.code(json.dumps(r.to_dict(), ensure_ascii=False, indent=2), language="json")
    except Exception as e:
        st.error(f"{type(e).__name__}: {e}")

if col3.button("③ chat.send_message"):
    try:
        m = _mk_model_simple()
        chat = m.start_chat(history=[])
        r = chat.send_message(prompt)
        st.success("OK: chat.send_message")
        st.subheader("text")
        st.code((r.text or "").strip() or "(空)")
        st.subheader("to_dict()")
        st.code(json.dumps(r.to_dict(), ensure_ascii=False, indent=2), language="json")
    except Exception as e:
        st.error(f"{type(e).__name__}: {e}")
