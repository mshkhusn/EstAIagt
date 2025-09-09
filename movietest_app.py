# movietest_app.py
# Gemini 2.5 flash シンプル動作確認用（fallback なし）

import json
import base64
import streamlit as st
import google.generativeai as genai

st.set_page_config(page_title="Gemini 2.5 Flash 簡易テスト", layout="centered")

# --- Secrets / 初期化 ---
API_KEY = st.secrets.get("GEMINI_API_KEY", "")
if not API_KEY:
    st.error("GEMINI_API_KEY が未設定です。Streamlit Secrets に追加してください。")
    st.stop()
genai.configure(api_key=API_KEY)

# --- 安全側: 応答テキスト抽出関数（textが空でもpartsやinline_dataから拾う） ---
def extract_text(resp) -> str:
    # 1) 普通に text があればそれを使う
    try:
        if getattr(resp, "text", None):
            return resp.text
    except Exception:
        pass

    # 2) candidates -> content.parts を調べて text / inline_data(json) を拾う
    try:
        cands = getattr(resp, "candidates", None) or []
        if not cands:
            return ""
        parts = getattr(cands[0].content, "parts", None) or []
        buf = []
        for p in parts:
            # a) plain text
            t = getattr(p, "text", None)
            if t:
                buf.append(t)
                continue
            # b) inline_data（application/jsonなど）
            inline = getattr(p, "inline_data", None)
            if inline and "json" in (getattr(inline, "mime_type", "") or getattr(inline, "mimeType", "")):
                data_b64 = getattr(inline, "data", None)
                if data_b64:
                    try:
                        buf.append(base64.b64decode(data_b64).decode("utf-8", errors="ignore"))
                    except Exception:
                        pass
        return "".join(buf)
    except Exception:
        return ""

# --- 画面 ---
st.title("Gemini 2.5 Flash 簡易テスト（fallback無し）")

st.sidebar.markdown("### 実行設定")
model_id = st.sidebar.selectbox("モデル", ["gemini-2.5-flash", "gemini-2.5-pro"], index=0)
max_tokens = st.sidebar.number_input("max_output_tokens", 16, 8192, 1024, step=16)
temperature = st.sidebar.slider("temperature", 0.0, 1.0, 0.6, 0.05)
top_p = st.sidebar.slider("top_p", 0.0, 1.0, 0.9, 0.05)
st.sidebar.caption("※ ここでは自動フォールバックはしません。")

st.markdown("#### プロンプト")
prompt = st.text_area(
    "自由に入力して「実行」を押してください。",
    value="こんにちは！何かお手伝いできることはありますか？",
    height=160,
)

col1, col2 = st.columns(2)
run = col1.button("▶︎ 実行", use_container_width=True, type="primary")
clear = col2.button("クリア", use_container_width=True)

if clear:
    st.experimental_rerun()

if run:
    # safety設定はデフォルトのまま（BLOCK_NONEは付けない）
    model = genai.GenerativeModel(
        model_id,
        generation_config={
            "candidate_count": 1,
            "max_output_tokens": int(max_tokens),
            "temperature": float(temperature),
            "top_p": float(top_p),
        },
    )
    try:
        resp = model.generate_content(prompt)
        raw = resp.to_dict()
        text = extract_text(resp)
        # finish_reason を表示（2 = SAFETY）
        try:
            finish_reason = (raw.get("candidates") or [{}])[0].get("finish_reason", None)
        except Exception:
            finish_reason = None

        st.success(f"実行モデル: {model_id} / finish_reason: {finish_reason}")
        st.write(text if text else "（空文字）")

        with st.expander("デバッグ：to_dict()（RAW）", expanded=False):
            st.code(json.dumps(raw, ensure_ascii=False, indent=2), language="json")

    except Exception as e:
        st.error(f"例外発生: {type(e).__name__}: {str(e)[:300]}")
