# app.py — Gemini 2.5 Flash | JSON 最小テスター（itemsのみ）
# -------------------------------------------------------
# - Safety を BLOCK_NONE にして無音終了を回避
# - application/json 指定で構造化出力を強制
# - 無音時のワンリトライ
# - JSONのロバスト整形（コードフェンス/末尾カンマ等に耐性）
# -------------------------------------------------------

import os
import re
import json
import ast
import base64
from typing import Any, Dict, Optional

import streamlit as st
import google.generativeai as genai
from google.generativeai.types import SafetySetting, HarmCategory, HarmBlockThreshold

# ====== Page ======
st.set_page_config(page_title="Gemini 2.5 Flash | JSON 最小テスター", layout="centered")
st.title("Gemini 2.5 Flash｜JSON 最小テスト（見積アイテムのみ）")

# ====== API Key ======
API_KEY = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY", "")
if not API_KEY:
    st.error("GEMINI_API_KEY が未設定です。Streamlit Secrets または環境変数に設定してください。")
    st.stop()
genai.configure(api_key=API_KEY)

# ====== Safety: BLOCK_NONE（誤検知での無音回避） ======
SAFETY_SETTINGS = [
    SafetySetting(category=HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                  threshold=HarmBlockThreshold.BLOCK_NONE),
    SafetySetting(category=HarmCategory.HARM_CATEGORY_HARASSMENT,
                  threshold=HarmBlockThreshold.BLOCK_NONE),
    SafetySetting(category=HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                  threshold=HarmBlockThreshold.BLOCK_NONE),
    SafetySetting(category=HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                  threshold=HarmBlockThreshold.BLOCK_NONE),
]

# ====== Model ======
MODEL_ID = "gemini-2.5-flash"
model = genai.GenerativeModel(
    MODEL_ID,
    safety_settings=SAFETY_SETTINGS,
    generation_config={
        # JSON を強制
        "response_mime_type": "application/json",
        "temperature": 0.2,
        "top_p": 0.9,
        "max_output_tokens": 2048,
    },
)

# ====== JSON Robust Parse ユーティリティ ======
STRICT_HEADER = (
    "必ず JSON オブジェクト 1個のみを**コードフェンスなし**で返してください。"
    "説明文や前置きは禁止です。ルートは items 配列のみです。"
)

def _strip_code_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()

def _remove_trailing_commas(s: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", s)

def _coerce_json_like(s: str) -> Optional[Dict[str, Any]]:
    if not s:
        return None
    # 正攻法
    try:
        return json.loads(s)
    except Exception:
        pass
    # フラグメント抽出
    try:
        first = s.find("{"); last = s.rfind("}")
        if first != -1 and last != -1 and last > first:
            frag = s[first:last+1]
            frag = _remove_trailing_commas(frag).replace("\r", "")
            frag = re.sub(r"\bTrue\b", "true", frag)
            frag = re.sub(r"\bFalse\b", "false", frag)
            frag = re.sub(r"\bNone\b", "null", frag)
            if "'" in frag and '"' not in frag:
                frag = frag.replace("'", '"')
            try:
                return json.loads(frag)
            except Exception:
                pass
    except Exception:
        pass
    # 最後の手段
    try:
        v = ast.literal_eval(s)
        if isinstance(v, dict):
            return v
    except Exception:
        pass
    return None

def robust_parse_items_json(raw: str) -> Dict[str, Any]:
    s = _strip_code_fences(raw)
    obj = _coerce_json_like(s) or {}
    items = obj.get("items")
    if not isinstance(items, list):
        # 想定外構造 → 空配列保証
        items = []
    return {"items": items}

# ====== Gemini 応答テキスト抽出 ======
def extract_text_from_resp(resp) -> str:
    """.text が空でも parts/inline_data まで探してテキスト抽出"""
    # 1) 通常
    try:
        if getattr(resp, "text", None):
            return resp.text
    except Exception:
        pass
    # 2) candidates.parts
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
                    buf.append(t); continue
                inline = getattr(p, "inline_data", None)
                if inline:
                    mime = getattr(inline, "mime_type", "") or getattr(inline, "mimeType", "")
                    data_b64 = getattr(inline, "data", None)
                    if data_b64 and "json" in (mime or "").lower():
                        try:
                            decoded = base64.b64decode(data_b64).decode("utf-8", errors="ignore")
                            if decoded: buf.append(decoded)
                        except Exception:
                            pass
        if buf:
            return "".join(buf)
    except Exception:
        pass
    # 3) どうしても無ければ to_dict を返す（デバッグ用）
    try:
        return json.dumps(resp.to_dict(), ensure_ascii=False)
    except Exception:
        return ""

def get_finish_reason(resp_dict: Dict[str, Any]) -> Optional[str]:
    try:
        cands = resp_dict.get("candidates") or []
        if not cands:
            return None
        return str(cands[0].get("finish_reason"))
    except Exception:
        return None

# ====== UI ======
st.subheader("プロンプト")
default_prompt = (
    "案件:\n"
    "- 30秒、納品1本\n"
    "- 撮影2日 / 編集3日\n"
    "- 出演者1名、都内スタジオ\n"
    "- 音声仕上げ（MA）あり\n\n"
    "※この出力は広告用の概算見積アイテムのテンプレートです。"
    "個人情報・性的/暴力/差別的内容は一切含みません。安全なビジネス用途です。\n\n"
    "【出力仕様】\n"
    "- ルートは items 配列のみ\n"
    "- 要素は {category, task, qty, unit, unit_price, note}\n"
    "- 説明文は禁止、JSONのみ\n"
)
user_prompt = st.text_area("案件条件（自由記入）", value=default_prompt, height=220)

if st.button("▶ JSON を生成", type="primary"):
    with st.spinner("Gemini 2.5 Flash が出力中…"):
        # 1) STRICT + ユーザ入力で組み立て
        prompt = (
            f"{STRICT_HEADER}\n"
            "必ず以下の key を持つ JSON を返してください：items（配列）\n"
            "各要素：category, task, qty, unit, unit_price, note\n"
            "\n"
            f"{user_prompt.strip()}\n"
        )

        # 2) 生成（無音なら1回だけリトライ）
        resp = model.generate_content(prompt)
        raw_text = extract_text_from_resp(resp)
        if not raw_text.strip():
            resp = model.generate_content(prompt)  # 1回だけ
            raw_text = extract_text_from_resp(resp)

        # 3) to_dict / finish_reason
        try:
            resp_dict = resp.to_dict()
        except Exception:
            resp_dict = {}
        finish_reason = get_finish_reason(resp_dict)

        st.success(f"モデル: {MODEL_ID} / finish_reason: {finish_reason or '(不明)'}")

        # 4) ロバスト整形
        parsed = robust_parse_items_json(raw_text)

        # 5) 表示
        st.subheader("整形後 JSON")
        st.code(json.dumps(parsed, ensure_ascii=False, indent=2), language="json")

        # ヘルプ：items が空なら注意
        if not parsed.get("items"):
            st.info("items が空です。プロンプトを少し具体化するか、語彙（キャスト→出演者 など）を無害化すると安定します。")

        with st.expander("デバッグ：モデル生出力（RAWテキスト）", expanded=False):
            st.code(raw_text or "(empty)")

        with st.expander("デバッグ：to_dict()（RAW）", expanded=False):
            st.code(json.dumps(resp_dict, ensure_ascii=False, indent=2), language="json")

else:
    st.caption("上のテキストを編集して『JSON を生成』を押してください。")
