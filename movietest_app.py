# -*- coding: utf-8 -*-
# movie_app.py  — プロンプト入力＋自動整形（Gemini 2.5 Flash / JSON生成）
import os
import io
import json
import re
from datetime import datetime

import pandas as pd
import streamlit as st

# ------------ Gemini client ------------
try:
    import google.generativeai as genai
except Exception as e:
    st.stop()

GEMINI_KEY = (
    st.secrets.get("GEMINI_API_KEY")
    if hasattr(st, "secrets") else None
) or os.getenv("GEMINI_API_KEY")

if not GEMINI_KEY:
    st.error("GEMINI_API_KEY が未設定です。st.secrets か環境変数に設定してください。")
    st.stop()

genai.configure(api_key=GEMINI_KEY)

MODEL_NAME = "gemini-2.5-flash"

# ------------ UI ------------
st.set_page_config(page_title="概算見積（プロンプト→自動整形）", layout="wide")
st.markdown("""
<style>
/* 表を横いっぱい */
.block-container {max-width: 1200px;}
.dataframe tbody tr th, .dataframe thead th {text-align: left;}
/* info badges を細く */
.small-note {font-size: 0.9rem; color:#666;}
/* 折りたたみの余白 */
details { margin-top: 0.5rem; }
</style>
""", unsafe_allow_html=True)

st.title("映像制作 概算見積（プロンプト → 自動整形）")

with st.expander("使い方", expanded=False):
    st.markdown("""
1. 下の **案件条件（自由記入）** に、尺/納品本数/日数/構成/想定媒体/欲しい要素 などを自由に書いてください。  
2. **映像ドメインに限定**にチェックすると、映像以外（印刷やWeb制作など）へ逸れにくくなります（必要ならOFFのままでOK）。  
3. **JSONを生成** を押すと、Gemini 2.5 Flash が見積アイテムのJSONを返し、表に整形します。  
4. **note（内訳）** を維持して表と **Excel** に出力します。  
""")

colA, colB = st.columns([2, 1])
with colA:
    prompt_text = st.text_area(
        "案件条件（自由記入）",
        height=220,
        placeholder="例）30秒1本 / 撮影2日・編集3日 / 都内スタジオ1日 / キャスト1名 / MAあり / オンライン納品 など"
    )
with colB:
    limit_video = st.checkbox("映像ドメインに限定（印刷/媒体/Webを含めない）", value=False)
    run_btn = st.button("▶ JSONを生成（Gemini 2.5 Flash）", use_container_width=True)

# 表示用スペース
result_area = st.container()

# ------------ 生成系：プロンプトとスキーマ ------------
SYSTEM_ROLE = (
    "あなたは広告映像制作の見積もりを作成するエキスパートです。"
    "ユーザーの案件条件から、動画制作の概算見積アイテムを日本語で構成し、"
    "次のJSONスキーマで返してください。必ずJSONのみを出力します。"
)

if limit_video:
    SYSTEM_ROLE += (
        "この依頼は映像制作に限定してください。印刷、Web制作、チラシ/配布/配送など"
        "映像外の領域に逸れないようにしてください。"
    )
else:
    SYSTEM_ROLE += (
        "ただし、ユーザーの文脈から映像以外の見積が適切な場合は、そのまま生成しても構いません。"
        "（フィルタで除外しない）"
    )

SCHEMA_EXAMPLE = {
    "items": [
        {
            "category": "制作費 / 撮影費 / 編集費・MA費 / 音楽・効果音 などカテゴリー名（日本語）",
            "task": "具体的な項目名（日本語）",
            "qty": 1,
            "unit": "式 / 日 / 人 / 本 / 曲 / など",
            "unit_price": 50000,
            "note": "内訳のメモ（例：工程や機材、注意点。不要なら空文字）"
        }
    ]
}
SCHEMA_NOTE = (
    "JSONのトップレベルは {\"items\": [...]} のみ。"
    "itemsは0件以上。金額は税抜。小計/消費税/合計は返さない。"
)

BASE_PROMPT = lambda user_text: (
    f"{SYSTEM_ROLE}\n\n"
    f"【出力JSONのスキーマ例（参考）】\n{json.dumps(SCHEMA_EXAMPLE, ensure_ascii=False, indent=2)}\n\n"
    f"【重要ルール】\n{SCHEMA_NOTE}\n\n"
    f"【ユーザー案件条件】\n{user_text.strip()}\n\n"
    "必ず JSON（application/json）だけを出力してください。"
)

# ------------ 補助：モデル呼び出し ------------
def call_gemini_json(prompt: str, temperature: float = 0.4):
    """application/json 厳格モードで実行"""
    model = genai.GenerativeModel(MODEL_NAME)
    return model.generate_content(
        prompt,
        generation_config=genai.GenerationConfig(
            temperature=temperature,
            response_mime_type="application/json",
        )
    )

def call_gemini_plain(prompt: str, temperature: float = 0.4):
    """テキスト出力（フォールバック用）"""
    model = genai.GenerativeModel(MODEL_NAME)
    return model.generate_content(
        prompt,
        generation_config=genai.GenerationConfig(
            temperature=temperature,
        )
    )

def extract_json_from_text(text: str) -> dict | None:
    """```json ... ``` または {} を抜き出してJSON化"""
    if not text:
        return None
    code_blocks = re.findall(r"```json(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if code_blocks:
        text = code_blocks[0]
    # 最初の { から最後の } を抜出
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None

def normalize_items(data: dict) -> list[dict]:
    """JSONから items listを抽出・型正規化"""
    items = data.get("items", []) if isinstance(data, dict) else []
    norm = []
    for it in items:
        if not isinstance(it, dict):
            continue
        category = str(it.get("category", "")).strip()
        task = str(it.get("task", "")).strip()
        note = str(it.get("note", "")).strip()
        unit = str(it.get("unit", "")).strip()
        # 数値化
        try:
            qty = float(it.get("qty", 0) or 0)
        except Exception:
            qty = 0
        try:
            unit_price = float(it.get("unit_price", 0) or 0)
        except Exception:
            unit_price = 0
        norm.append({
            "category": category,
            "task": task,
            "qty": qty,
            "unit": unit,
            "unit_price": unit_price,
            "note": note,
            "amount": qty * unit_price
        })
    return norm

def df_with_totals(items: list[dict]) -> tuple[pd.DataFrame, float, float, float]:
    df = pd.DataFrame(items, columns=["category", "task", "qty", "unit", "unit_price", "note", "amount"])
    if not len(df):
        return df, 0.0, 0.0, 0.0
    # 並び替え（任意）
    df["qty"] = df["qty"].fillna(0).astype(float)
    df["unit_price"] = df["unit_price"].fillna(0).astype(float)
    df["amount"] = df["amount"].fillna(0).astype(float)
    subtotal = float(df["amount"].sum())
    tax = round(subtotal * 0.1, 0)
    total = subtotal + tax
    return df, subtotal, tax, total

def to_excel_bytes(df: pd.DataFrame) -> bytes:
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="xlsxwriter") as writer:
        df.to_excel(writer, sheet_name="estimate", index=False)
    return out.getvalue()

# ------------ 実行 ------------
raw_dict_json = None
raw_dict_plain = None
finish_info = {}

if run_btn:
    if not prompt_text.strip():
        st.warning("案件条件を入力してください。")
    else:
        with st.spinner("Gemini 2.5 Flash が見積アイテムJSONを生成中…"):
            # 1) JSON厳格
            p = BASE_PROMPT(prompt_text)
            try:
                resp = call_gemini_json(p)
                raw_dict_json = resp.to_dict()
            except Exception as e:
                raw_dict_json = {"error": str(e)}

            # 取り出し
            items_data = None
            finish_reason = None
            try:
                finish_reason = raw_dict_json["candidates"][0].get("finish_reason")
                parts = raw_dict_json["candidates"][0]["content"].get("parts") or []
                text_json = ""
                for pr in parts:
                    if "text" in pr:
                        text_json += pr["text"]
                if text_json.strip():
                    items_data = json.loads(text_json)
            except Exception:
                pass

            # 2) フォールバック（plain→抽出）
            used_fallback = False
            if not items_data:
                used_fallback = True
                try:
                    resp2 = call_gemini_plain(p)
                    raw_dict_plain = resp2.to_dict()
                    # parts→text 全結合
                    pt = ""
                    try:
                        for pr in raw_dict_plain["candidates"][0]["content"].get("parts", []):
                            if "text" in pr:
                                pt += pr["text"]
                    except Exception:
                        pass
                    items_data = extract_json_from_text(pt)
                except Exception as e:
                    raw_dict_plain = {"error": str(e)}

            # 3) 整形＆表示
            finish_info = {
                "model_used": MODEL_NAME,
                "finish_reason": str(finish_reason) if finish_reason is not None else "(unknown)",
                "used_fallback": used_fallback
            }

            with result_area:
                st.info(f"モデル: {finish_info['model_used']} / finish: {finish_info['finish_reason']} / fallback: {finish_info['used_fallback']}")

                if not items_data:
                    st.warning("items が空でした。備考をもう少し具体的にすると安定します。")
                else:
                    items = normalize_items(items_data)
                    df, subtotal, tax, total = df_with_totals(items)
                    st.dataframe(df, use_container_width=True)

                    col1, col2, col3 = st.columns(3)
                    col1.metric("小計（税抜）", f"{int(subtotal):,} 円")
                    col2.metric("消費税（10%）", f"{int(tax):,} 円")
                    col3.metric("合計", f"{int(total):,} 円")

                    # Excel
                    excel_bytes = to_excel_bytes(df)
                    fname = f"estimate_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                    st.download_button("💾 Excelダウンロード（note入り）", data=excel_bytes, file_name=fname, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

                # --- Debug ---
                with st.expander("デバッグ：生成 RAW（JSONモード）"):
                    st.code(json.dumps(raw_dict_json, ensure_ascii=False, indent=2))
                if raw_dict_plain:
                    with st.expander("デバッグ：生成 RAW（プレーン→抽出）"):
                        st.code(json.dumps(raw_dict_plain, ensure_ascii=False, indent=2))
