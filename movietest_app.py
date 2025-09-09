# movie_app.py
# -*- coding: utf-8 -*-
#
# 概算見積（movie_app スタイル / Gemini 2.5 Flash）
# - Streamlit UI + Gemini 2.5 Flash
# - secrets.toml に GEMINI_API_KEY を登録して利用する
# - JSONのみを返すようプロンプト設計
# - note（内訳）を保持
# - 正規化処理あり
# - Excel ダウンロード対応

from __future__ import annotations

import os
import io
import re
import json
import datetime as dt
from decimal import Decimal, InvalidOperation

import streamlit as st
import pandas as pd

# Google Generative AI (Gemini)
import google.generativeai as genai


# -----------------------------
# 設定
# -----------------------------
APP_TITLE = "概算見積（movie_app スタイル / Gemini 2.5 Flash）"
MODEL_NAME = "gemini-2.5-flash"
TAX_RATE = Decimal("0.10")  # 消費税率 10%

# Streamlit ページ設定
st.set_page_config(page_title=APP_TITLE, layout="wide")


# -----------------------------
# API キー設定
# -----------------------------
if "GEMINI_API_KEY" not in st.secrets:
    st.error("❌ st.secrets に GEMINI_API_KEY を設定してください。")
    st.stop()

genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
model = genai.GenerativeModel(MODEL_NAME)


# -----------------------------
# プロンプト（システム前置き）
# -----------------------------
SYSTEM_ROLE = """
あなたは広告映像制作の見積りを作成するエキスパートです。
日本の映像業界の一般的な区分と相場感に沿って、合理的で説明可能な概算見積を生成します。

必ず JSON だけを返してください。コードフェンスは不要です。
スキーマ:
{
  "items":[
    {
      "category": "制作費|撮影費|編集費・MA費|音楽・効果音|その他|管理費",
      "task": "項目名",
      "qty": 数量（整数）,
      "unit": "式|日|人|曲|本|回|部 など",
      "unit_price": 単価（整数・円）,
      "note": "内訳・条件・補足（日本語で簡潔に）"
    }
  ]
}

制約:
- 「note」には内訳（機材・人員・工程など）を短文で残す
- 金額は整数（円）
- 映像以外の依頼が明示されていれば対応してよいが、曖昧な場合は映像制作として解釈
- 出力は JSON のみ
""".strip()


# -----------------------------
# 正規化関連
# -----------------------------
CATEGORY_ORDER = {
    "制作費": 0,
    "撮影費": 1,
    "編集費・MA費": 2,
    "音楽・効果音": 3,
    "その他": 8,
    "管理費": 9,
}


def _to_int(v, default=0) -> int:
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip().replace(",", "")
    try:
        return int(Decimal(s))
    except (InvalidOperation, ValueError):
        return default


def normalize_items(items: list[dict]) -> list[dict]:
    norm = []
    for raw in items or []:
        category = str(raw.get("category", "")).strip() or "その他"
        task = str(raw.get("task", "")).strip() or "未定義"
        qty = _to_int(raw.get("qty"), 1)
        unit_price = _to_int(raw.get("unit_price"), 0)
        unit = str(raw.get("unit", "式")).strip()
        note = str(raw.get("note", "")).strip()

        norm.append({
            "category": category,
            "task": task,
            "qty": qty,
            "unit": unit,
            "unit_price": unit_price,
            "note": note,
            "amount": qty * unit_price,
        })

    norm.sort(key=lambda r: (CATEGORY_ORDER.get(r["category"], 50)))
    return norm


def compute_totals(rows: list[dict]) -> tuple[int, int, int]:
    subtotal = sum(r.get("amount", 0) for r in rows)
    tax = int(Decimal(subtotal) * TAX_RATE)
    total = subtotal + tax
    return subtotal, tax, total


# -----------------------------
# JSON 抽出
# -----------------------------
RE_JSON_BLOCK = re.compile(r"\{(?:.|\n)*\}", re.MULTILINE)


def extract_json_from_text(text: str) -> dict | None:
    if not text:
        return None
    fence = re.search(r"```json\s*(\{(?:.|\n)*?\})\s*```", text, re.IGNORECASE)
    if fence:
        try:
            return json.loads(fence.group(1))
        except Exception:
            pass
    m = RE_JSON_BLOCK.search(text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


# -----------------------------
# Gemini 呼び出し
# -----------------------------
def call_gemini(prompt: str) -> dict:
    full_prompt = SYSTEM_ROLE + "\n\n" + prompt.strip()

    try:
        res = model.generate_content(full_prompt)
        text = getattr(res, "text", "") or ""
        data = extract_json_from_text(text) or {}

        meta = {
            "model_used": MODEL_NAME,
            "finish_reason": getattr(res.candidates[0], "finish_reason", None)
            if getattr(res, "candidates", None)
            else None,
            "usage": getattr(res, "usage_metadata", None),
            "raw_preview": (text[:800] + " ...") if len(text) > 800 else text,
        }

        if not isinstance(data, dict) or "items" not in data:
            data = {"items": []}
        return {"data": data, "meta": meta}

    except Exception as e:
        return {"data": {"items": []}, "meta": {"error": str(e), "model_used": MODEL_NAME}}


# -----------------------------
# Excel ダウンロード
# -----------------------------
def build_excel_download(df: pd.DataFrame, subtotal: int, tax: int, total: int) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="estimate")
        wb = writer.book
        ws = writer.sheets["estimate"]

        fmt_money = wb.add_format({"num_format": "#,##0", "align": "right"})
        fmt_head = wb.add_format({"bold": True, "bg_color": "#F2F2F2"})

        ws.set_row(0, 20, fmt_head)
        for col_name in ("qty", "unit_price", "amount"):
            if col_name in df.columns:
                col_idx = df.columns.get_loc(col_name)
                ws.set_column(col_idx, col_idx, 12, fmt_money)
        if "note" in df.columns:
            note_idx = df.columns.get_loc("note")
            ws.set_column(note_idx, note_idx, 50)

        row = len(df) + 2
        ws.write(row, 0, "小計（税抜）")
        ws.write(row, 1, subtotal, fmt_money)
        ws.write(row + 1, 0, "消費税")
        ws.write(row + 1, 1, tax, fmt_money)
        ws.write(row + 2, 0, "合計")
        ws.write(row + 2, 1, total, fmt_money)

    return output.getvalue()


# -----------------------------
# UI
# -----------------------------
st.title(APP_TITLE)

with st.expander("入力（プロンプト）", expanded=True):
    default_text = (
        "案件:\n"
        "- 30秒、納品1本\n"
        "- 撮影2日 / 編集3日\n"
        "- キャスト1名、MAあり\n"
    )
    user_free = st.text_area("案件条件（自由記入）", value=default_text, height=180)

btn = st.button("▶︎ 見積アイテムを生成", type="primary")

st.markdown("---")

if btn:
    with st.spinner("Gemini 2.5 Flash で生成中..."):
        call = call_gemini(user_free)

    data = call["data"]
    meta = call["meta"]

    with st.expander("モデル情報", expanded=False):
        st.write(meta)
        st.text_area("RAWテキスト", meta.get("raw_preview", ""), height=180)

    items = data.get("items", [])
    norm_rows = normalize_items(items)

    df = pd.DataFrame(norm_rows, columns=["category", "task", "qty", "unit", "unit_price", "note", "amount"])
    subtotal, tax, total = compute_totals(norm_rows)

    st.subheader("見積アイテム")
    st.caption(f"モデル: {meta.get('model_used')} / 行数: {len(df)}")
    st.dataframe(df, use_container_width=True)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("小計（税抜）", f"{subtotal:,.0f} 円")
    with c2:
        st.metric("消費税", f"{tax:,.0f} 円")
    with c3:
        st.metric("合計", f"{total:,.0f} 円")

    excel_bytes = build_excel_download(df, subtotal, tax, total)
    st.download_button(
        "📥 Excelダウンロード",
        data=excel_bytes,
        file_name=f"estimate_{dt.datetime.now():%Y%m%d_%H%M}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

else:
    st.info("案件条件を入力して『見積アイテムを生成』を押してください。")
