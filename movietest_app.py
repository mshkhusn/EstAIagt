# movietest_json_app.py
# Gemini 2.5 flash で「見積アイテム JSON」だけを生成・表示する最小アプリ
# - フォールバックなし
# - JSONはコードフェンス有無どちらも許容
# - 多少壊れたJSONも頑張って整形してパース

import re
import ast
import json
import base64
import streamlit as st
import pandas as pd
import google.generativeai as genai

st.set_page_config(page_title="Gemini 2.5 Flash｜JSON最小テスト", layout="centered")

# ========== Secrets / 初期化 ==========
API_KEY = st.secrets.get("GEMINI_API_KEY", "")
if not API_KEY:
    st.error("GEMINI_API_KEY が未設定です。Streamlit Secrets に追加してください。")
    st.stop()

genai.configure(api_key=API_KEY)

# ========== ユーティリティ ==========
def extract_text(resp) -> str:
    """
    Gemini 応答からテキストを抽出（text → parts.text → inline_data(json) の順に探す）
    """
    try:
        if getattr(resp, "text", None):
            return resp.text
    except Exception:
        pass

    try:
        cands = getattr(resp, "candidates", None) or []
        if not cands:
            return ""
        parts = getattr(cands[0].content, "parts", None) or []
        buf = []
        for p in parts:
            t = getattr(p, "text", None)
            if t:
                buf.append(t)
                continue
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

def strip_code_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()

def remove_trailing_commas(s: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", s)

def coerce_json_like(s: str):
    """
    壊れ気味 JSON も可能な限り dict/ list として返す
    """
    if not s:
        return None
    # 1) まずは正攻法
    try:
        return json.loads(s)
    except Exception:
        pass

    # 2) 先頭末尾の {...} / [...] を抽出して整形
    try:
        first = min([x for x in [s.find("{"), s.find("[")] if x != -1], default=-1)
        last_brace = s.rfind("}")
        last_bracket = s.rfind("]")
        last = max(last_brace, last_bracket)
        if first != -1 and last > first:
            frag = s[first:last+1]
            frag = frag.replace("\r", "")
            frag = remove_trailing_commas(frag)
            frag = re.sub(r"\bTrue\b", "true", frag)
            frag = re.sub(r"\bFalse\b", "false", frag)
            frag = re.sub(r"\bNone\b", "null", frag)
            # ' を " に変える簡易策（" が全然無い時だけ）
            if "'" in frag and '"' not in frag:
                frag = frag.replace("'", '"')
            try:
                return json.loads(frag)
            except Exception:
                pass
    except Exception:
        pass

    # 3) 最後に ast.literal_eval で辞書/配列なら拾う
    try:
        return ast.literal_eval(s)
    except Exception:
        return None

def robust_parse_items_json(raw_text: str):
    """
    モデル生テキストを items JSON(dict) に整形して返す
    - 期待形: {"items": [ {category, task, qty, unit, unit_price, note}, ... ]}
    """
    s = strip_code_fences(raw_text or "")
    obj = coerce_json_like(s)
    if not isinstance(obj, dict):
        # list で返るなどのケースに合わせる
        if isinstance(obj, list):
            obj = {"items": obj}
        else:
            obj = {"items": []}

    items = obj.get("items")
    if not isinstance(items, list):
        # よくある代替キーにも対応
        if isinstance(obj.get("data"), list):
            items = obj["data"]
        elif isinstance(obj.get("result"), dict) and isinstance(obj["result"].get("items"), list):
            items = obj["result"]["items"]
        else:
            items = []
    obj["items"] = items
    return obj

# ========== プロンプト ==========
SYSTEM_HINT = """以下のスキーマで JSON オブジェクトを1つ返してください。
- ルートキー: items（配列）
- 各要素: category, task, qty, unit, unit_price, note
- 説明文や前置きは不要。**可能ならコードフェンスなし**で返す。（付いていても可）
"""

DEFAULT_CASE = """案件:
- 30秒、納品1本
- 撮影2日 / 編集3日
- 構成: 通常的な広告映像（インタビュー無し）
- 参考：撮影は都内スタジオ、キャスト1名、MAあり"""

# ========== 画面 ==========
st.title("Gemini 2.5 Flash｜JSON 最小テスト（見積アイテムのみ）")

with st.sidebar:
    st.caption("モデルは 2.5 Flash 専用（フォールバックなし）")
    max_tokens = st.number_input("max_output_tokens", 64, 4096, 1024, step=32)
    temperature = st.slider("temperature", 0.0, 1.0, 0.4, 0.05)
    top_p = st.slider("top_p", 0.0, 1.0, 0.9, 0.05)

st.subheader("プロンプト")
user_case = st.text_area("案件条件（自由記入）", value=DEFAULT_CASE, height=180)
if st.button("▶︎ JSON を生成", type="primary", use_container_width=True):
    model = genai.GenerativeModel(
        "gemini-2.5-flash",
        generation_config={
            "candidate_count": 1,
            "max_output_tokens": int(max_tokens),
            "temperature": float(temperature),
            "top_p": float(top_p),
        },
        # Safetyはデフォルト（BLOCK_NONE を指定しない）
    )

    user_prompt = f"{SYSTEM_HINT}\n\n{user_case}\n\n出力例: " \
                  '{"items":[{"category":"撮影費","task":"カメラマン費","qty":2,"unit":"日","unit_price":80000,"note":""}]}'  # 軽い誘導

    try:
        resp = model.generate_content(user_prompt)
        raw = resp.to_dict()
        text = extract_text(resp)

        # finish_reason
        try:
            finish_reason = (raw.get("candidates") or [{}])[0].get("finish_reason", None)
        except Exception:
            finish_reason = None

        st.success(f"モデル: gemini-2.5-flash / finish_reason: {finish_reason}")

        # パース
        parsed_obj = robust_parse_items_json(text)
        st.markdown("#### 整形後 JSON")
        st.code(json.dumps(parsed_obj, ensure_ascii=False, indent=2), language="json")

        # テーブル表示（あれば）
        items = parsed_obj.get("items", [])
        if isinstance(items, list) and items:
            df = pd.DataFrame(items)
            st.markdown("#### items テーブル")
            st.dataframe(df, use_container_width=True)
        else:
            st.info("items が空です。")

        with st.expander("デバッグ：モデル生出力（RAWテキスト）", expanded=False):
            st.code(text if text else "(empty)")

        with st.expander("デバッグ：to_dict()（RAW）", expanded=False):
            st.code(json.dumps(raw, ensure_ascii=False, indent=2), language="json")

    except Exception as e:
        st.error(f"例外: {type(e).__name__}: {str(e)[:400]}")
