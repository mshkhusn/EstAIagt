# gemini25_probe_app.py
import json
import streamlit as st
import google.generativeai as genai

st.set_page_config(page_title="Gemini 2.5 Probe (SAFETY切り分け)", layout="centered")

# --- Secrets ---
API_KEY = st.secrets.get("GEMINI_API_KEY", "")
if not API_KEY:
    st.error("GEMINI_API_KEY が未設定です。Streamlit Secrets に追加してください。")
    st.stop()

genai.configure(api_key=API_KEY)

# --- Safety settings helper (BLOCK_NONE を付与してみる) ---
def permissive_safety():
    try:
        from google.generativeai.types import HarmCategory, HarmBlockThreshold
        return {
            HarmCategory.HARM_CATEGORY_SEXUAL: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }
    except Exception:
        # SDK が古い等で import できない場合は None を返す
        return None

# --- 3つの最小テストパターン ----------------------------------------------
TESTS = {
    "A) 最小JSON（テキスト指定）": {
        "prompt": '必ず {"ok": true} だけを、コードフェンス無しで返してください。説明は禁止。',
        "gen_cfg": {"max_output_tokens": 32},  # テキスト返答
        "schema": None,
    },
    "B) 最小JSON（構造化出力）": {
        "prompt": "次のスキーマに従って JSON を1個だけ返してください。",
        "gen_cfg": {
            "max_output_tokens": 32,
            "response_mime_type": "application/json",
            "response_schema": {
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
            },
        },
        "schema": {"ok": True},
    },
    "C) 最小テキスト（echo）": {
        "prompt": "次の文字列をそのまま返してください: hello",
        "gen_cfg": {"max_output_tokens": 16},
        "schema": None,
    },
}

# --- UI -----------------------------------------------------------------------
st.title("Gemini 2.5 Probe（SAFETY 無音切り分け）")

model = st.selectbox("モデル", ["gemini-2.5-flash", "gemini-2.5-pro"], index=0)
test_name = st.radio("テスト内容", list(TESTS.keys()), index=0)
permissive = st.checkbox("Permissive Safety（BLOCK_NONE を付与して試す）", value=True)
repeat = st.number_input("繰り返し回数（統計/ブレ確認）", min_value=1, max_value=10, value=1, step=1)

colA, colB = st.columns(2)
with colA:
    temp = st.number_input("temperature", 0.0, 1.0, 0.0, 0.05)
with colB:
    top_p = st.number_input("top_p", 0.0, 1.0, 0.9, 0.05)

run = st.button("▶︎ 実行")

# --- 実行ロジック -------------------------------------------------------------
def finish_reason_name(d: dict) -> str:
    try:
        cand = (d.get("candidates") or [{}])[0]
        fr = cand.get("finish_reason", 0)
        return {0: "UNSPEC", 1: "STOP", 2: "SAFETY", 3: "RECIT", 4: "OTHER"}.get(fr, str(fr))
    except Exception:
        return "UNKNOWN"

def extract_text(resp) -> str:
    # resp.text が空でも parts 経由で拾う
    try:
        if getattr(resp, "text", None):
            return resp.text
    except Exception:
        pass
    try:
        cands = getattr(resp, "candidates", []) or []
        parts = getattr(getattr(cands[0], "content", None), "parts", []) if cands else []
        buf = []
        for p in parts:
            t = getattr(p, "text", None)
            if t:
                buf.append(t)
        return "".join(buf)
    except Exception:
        return ""

if run:
    spec = TESTS[test_name]
    safety_settings = permissive_safety() if permissive else None

    st.subheader("実行パラメータ")
    st.write({
        "model": model,
        "test": test_name,
        "permissive_safety": bool(safety_settings),
        "repeat": int(repeat),
    })

    results = []
    for i in range(int(repeat)):
        model_obj = genai.GenerativeModel(
            model,
            generation_config={
                "candidate_count": 1,
                "temperature": temp,
                "top_p": top_p,
                **spec["gen_cfg"],
            },
            safety_settings=safety_settings,
        )
        prompt = spec["prompt"]
        if spec["schema"] is not None:
            prompt += f"\nサンプル: {json.dumps(spec['schema'], ensure_ascii=False)}"

        try:
            resp = model_obj.generate_content(prompt)
            d = resp.to_dict()
            txt = extract_text(resp)
            fin = finish_reason_name(d)

            # 表示
            st.markdown(f"### Run {i+1}")
            st.code(txt or "(空文字)", language="json" if "{" in (txt or "") else None)
            with st.expander("to_dict()（RAW）", expanded=False):
                st.code(json.dumps(d, ensure_ascii=False, indent=2), language="json")

            results.append({"run": i + 1, "finish": fin, "text_len": len(txt or "")})

        except Exception as e:
            results.append({"run": i + 1, "finish": f"EXC:{type(e).__name__}", "text_len": 0})
            st.error(f"例外: {type(e).__name__}: {str(e)[:200]}")

    st.subheader("サマリ")
    st.table(results)

st.markdown("---")
st.caption("※ ここで A/B/C すべてが SAFETY になる場合、モデル/アカウント/リージョン側の Safety レイヤーでブロックされている可能性が高いです。")
