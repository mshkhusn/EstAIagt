# movietest_app.py
# =============================================
# Gemini 2.5 疎通テスター（2.0へ自動フォールバック）
# - まずはテキストのみで 2.5 が通るか確認する最小実装
# - requirements.txt は現状のままでOK
# - 環境変数 GEMINI_API_KEY を設定してください
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


# ============ ボタン UI ============
col_run, col_clear = st.columns(2)
with col_run:
    run_clicked = st.button("実行", type="primary", use_container_width=True)
with col_clear:
    clear_clicked = st.button("クリア", use_container_width=True)


# ============ 推論ラッパ関数群 ============
def _generate(model_id: str, contents: str, *, max_tokens: int, temp: float):
    m = genai.GenerativeModel(model_id)
    return m.generate_content(
        contents,
        generation_config={
            "max_output_tokens": int(max_tokens),
            "temperature": float(temp),
        },
    )


def run_with_fallback(
    primary_model: str,
    contents: str,
    *,
    max_tokens: int,
    temp: float,
    fallback_model: str = FALLBACK_MODEL,
) -> Dict[str, Any]:
    out = {"ok": False, "model": primary_model, "fallback_used": False, "text": "", "raw": None}
    try:
        r = _generate(primary_model, contents, max_tokens=max_tokens, temp=temp)
        out.update({"ok": True, "text": getattr(r, "text", ""), "raw": r})
        return out
    except Exception as e:
        out["error_primary"] = repr(e)
        time.sleep(0.6)
        try:
            r2 = _generate(fallback_model, contents, max_tokens=max_tokens, temp=temp)
            out.update(
                {
                    "ok": True,
                    "model": fallback_model,
                    "fallback_used": True,
                    "text": getattr(r2, "text", ""),
                    "raw": r2,
                }
            )
            return out
        except Exception as e2:
            out["error_fallback"] = repr(e2)
            return out


# ============ 実行/クリア ロジック ============
if run_clicked:
    if not prompt.strip():
        st.warning("プロンプトを入力してください。")
    else:
        final_prompt = (
            "あなたは厳密なJSON出力のアシスタントです。必ず JSON のみを返してください。\n"
            "日本語の説明文は JSON の値の中だけに含めてください。トップレベルは {\"result\": ...} 構造にしてください。\n\n"
        ) + prompt if force_json else prompt

        with st.spinner(f"{model_name} で実行中…"):
            out = run_with_fallback(model_name, final_prompt, max_tokens=max_output_tokens, temp=temperature)

        status = ("成功" if out.get("ok") else "失敗") + ("（フォールバックあり）" if out.get("fallback_used") else "")
        if out.get("ok"):
            st.success(f"{status} / 実行モデル: {out.get('model')}")
            st.write(out.get("text", ""))
        else:
            st.error(f"失敗 / 実行モデル: {out.get('model')}")
            st.write("Primary error:", out.get("error_primary"))
            st.write("Fallback error:", out.get("error_fallback"))

if clear_clicked:
    st.session_state.clear()
    st.rerun()
