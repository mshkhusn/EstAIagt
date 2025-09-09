# app.py （AI見積もりくん２ / GPT系のみ対応）

import os
import re
import json
import importlib
from io import BytesIO
from datetime import date
import ast
from typing import Optional

import streamlit as st
import pandas as pd
from dateutil.relativedelta import relativedelta
from openpyxl.styles import Font

# ===== openpyxl / Excel =====
from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string, get_column_letter

# ===== OpenAI v1 SDK =====
from openai import OpenAI
import httpx  

# =========================
# ページ設定
# =========================
st.set_page_config(page_title="AI見積もりくん２", layout="centered")

# =========================
# Secrets
# =========================
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
APP_PASSWORD   = st.secrets["APP_PASSWORD"]
OPENAI_ORG_ID  = st.secrets.get("OPENAI_ORG_ID", None)

# OpenAI 環境変数（明示）
if not OPENAI_API_KEY:
    st.error("OPENAI_API_KEY が設定されていません。st.secrets を確認してください。")
    st.stop()
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
if OPENAI_ORG_ID:
    os.environ["OPENAI_ORG_ID"] = OPENAI_ORG_ID

# OpenAI v1 クライアント
openai_client = OpenAI(
    http_client=httpx.Client(timeout=60.0)
)

# バージョン表示
try:
    openai_version = importlib.import_module("openai").__version__
except Exception:
    openai_version = "unknown"

# =========================
# 定数
# =========================
TAX_RATE = 0.10
MGMT_FEE_CAP_RATE = 0.15

# =========================
# セッション
# =========================
for k in [
    "chat_history", "items_json_raw", "items_json", "df", "meta", "final_html"
]:
    if k not in st.session_state:
        st.session_state[k] = None

if st.session_state["chat_history"] is None:
    st.session_state["chat_history"] = [
        {"role": "system", "content": "あなたは広告クリエイティブ制作のプロフェッショナルです。相場感をもとに見積もりを作成するため、ユーザーにヒアリングを行います。"},
        {"role": "assistant", "content": "こんにちは！こちらは「AI見積もりくん２」です。見積もり作成のために、まず案件概要を教えてください。"}
    ]

# =========================
# 認証
# =========================
st.title("💰 AI見積もりくん２")
password = st.text_input("パスワードを入力してください", type="password")
if password != APP_PASSWORD:
    st.warning("🔒 認証が必要です")
    st.stop()

# =========================
# チャットUI
# =========================
st.header("チャットでヒアリング")

for msg in st.session_state["chat_history"]:
    if msg["role"] == "assistant":
        st.chat_message("assistant").write(msg["content"])
    elif msg["role"] == "user":
        st.chat_message("user").write(msg["content"])

if user_input := st.chat_input("要件を入力してください..."):
    st.session_state["chat_history"].append({"role": "user", "content": user_input})

    with st.chat_message("user"):
        st.write(user_input)

    with st.chat_message("assistant"):
        with st.spinner("AIが考えています..."):
            resp = openai_client.chat.completions.create(
                model="gpt-4.1",
                messages=st.session_state["chat_history"],
                temperature=0.4,
                max_tokens=1200
            )
            reply = resp.choices[0].message.content
            st.write(reply)
            st.session_state["chat_history"].append({"role": "assistant", "content": reply})

# =========================
# プロンプト for 見積もり生成
# =========================
def build_prompt_for_estimation(chat_history):
    return f"""
必ず有効な JSON のみを返してください。説明文は禁止です。

あなたは広告制作の見積もり作成エキスパートです。
以下の会話履歴をもとに、見積もりの内訳を作成してください。

【会話履歴】
{json.dumps(chat_history, ensure_ascii=False, indent=2)}

【出力仕様】
- JSON 1オブジェクト、ルートは items 配列のみ。
- 各要素キー: category / task / qty / unit / unit_price / note
- category は「制作人件費」「企画」「撮影費」「出演関連費」「編集費・MA費」「諸経費」「管理費」いずれか。
- qty, unit は妥当な値（日/式/人/時間/カット等）
- 単価は広告制作の一般相場で推定
- 管理費は固定1行（task=管理費（固定）, qty=1, unit=式）
- 合計や税は含めない
"""

# =========================
# JSONパース
# =========================
def robust_parse_items_json(raw: str) -> str:
    try:
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            obj = {"items": []}
        if "items" not in obj:
            obj["items"] = []
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return json.dumps({"items":[]}, ensure_ascii=False)

# =========================
# 計算
# =========================
def df_from_items_json(items_json: str) -> pd.DataFrame:
    try:
        data = json.loads(items_json) if items_json else {}
    except Exception:
        data = {}
    items = data.get("items", []) or []
    norm = []
    for x in items:
        norm.append({
            "category": str(x.get("category", "")),
            "task": str(x.get("task", "")),
            "qty": x.get("qty", 0),
            "unit": str(x.get("unit", "")),
            "unit_price": x.get("unit_price", 0),
            "note": str(x.get("note", "")),
        })
    df = pd.DataFrame(norm)
    df["小計"] = (df["qty"].astype(float) * df["unit_price"].astype(float)).astype(int)
    return df

def compute_totals(df: pd.DataFrame):
    taxable = int(df["小計"].sum())
    tax = int(round(taxable * TAX_RATE))
    total = taxable + tax
    return {
        "taxable": taxable,
        "tax": tax,
        "total": total
    }

# =========================
# 表示 & ダウンロード
# =========================
if st.button("📝 AI見積もりくんで見積もりを生成する"):
    with st.spinner("AIが見積もりを生成中…"):
        prompt = build_prompt_for_estimation(st.session_state["chat_history"])
        resp = openai_client.chat.completions.create(
            model="gpt-4.1",
            messages=[{"role":"system","content":"You MUST return only valid JSON."},
                      {"role":"user","content":prompt}],
            response_format={"type":"json_object"},
            temperature=0.2,
            max_tokens=4000
        )
        raw = resp.choices[0].message.content or '{"items":[]}'
        items_json = robust_parse_items_json(raw)
        df = df_from_items_json(items_json)
        meta = compute_totals(df)

        st.session_state["items_json_raw"] = raw
        st.session_state["items_json"] = items_json
        st.session_state["df"] = df
        st.session_state["meta"] = meta

if st.session_state["df"] is not None:
    st.success("✅ 見積もり結果プレビュー")
    st.dataframe(st.session_state["df"])

    st.write(f"**小計（税抜）:** {st.session_state['meta']['taxable']:,}円")
    st.write(f"**消費税:** {st.session_state['meta']['tax']:,}円")
    st.write(f"**合計:** {st.session_state['meta']['total']:,}円")

    # Excel DL
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        st.session_state["df"].to_excel(writer, index=False, sheet_name="見積もり")
    buf.seek(0)
    st.download_button("📥 Excelでダウンロード", buf, "見積もり.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    # DD見積書テンプレ
    tmpl = st.file_uploader("DD見積書テンプレートをアップロード（.xlsx）", type=["xlsx"])
    if tmpl is not None:
        wb = load_workbook(filename=BytesIO(tmpl.read()))
        ws = wb.active
        # TODO: テンプレ出力ロジックを移植（movie_appの仕組みを流用）
        out = BytesIO()
        wb.save(out)
        out.seek(0)
        st.download_button("📥 DD見積書テンプレで出力", out, "見積もり_DDテンプレ.xlsx")
