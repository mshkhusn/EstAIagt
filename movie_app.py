import os
import json
import importlib
from io import BytesIO
from datetime import date
from copy import copy

import streamlit as st
import pandas as pd
import google.generativeai as genai
from dateutil.relativedelta import relativedelta
from openpyxl import load_workbook

# =========================
# ページ設定
# =========================
st.set_page_config(page_title="映像制作概算見積エージェント vNext", layout="centered")

# =========================
# Secrets 読み込み
# =========================
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
APP_PASSWORD   = st.secrets["APP_PASSWORD"]

genai.configure(api_key=GEMINI_API_KEY)
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

# =========================
# OpenAI 初期化（v1系/0系 両対応）
# =========================
USE_OPENAI_CLIENT_V1 = False
openai_client = None
openai_version = "unknown"

try:
    from openai import OpenAI as _OpenAI
    openai_client = _OpenAI()
    USE_OPENAI_CLIENT_V1 = True
    try:
        mod = importlib.import_module("openai")
        openai_version = getattr(mod, "__version__", "1.x")
    except Exception:
        openai_version = "1.x"
except Exception:
    import openai as _openai
    _openai.api_key = OPENAI_API_KEY
    openai_client = _openai
    USE_OPENAI_CLIENT_V1 = False
    openai_version = getattr(openai_client, "__version__", "0.x")

# =========================
# 定数
# =========================
TAX_RATE = 0.10
MGMT_FEE_CAP_RATE = 0.15
RUSH_K = 0.75

# =========================
# セッション状態
# =========================
for k in ["items_json", "df", "meta", "final_html"]:
    if k not in st.session_state:
        st.session_state[k] = None

# =========================
# 認証
# =========================
st.title("映像制作概算見積エージェント vNext")
password = st.text_input("パスワードを入力してください", type="password")
if password != APP_PASSWORD:
    st.warning("🔒 認証が必要です")
    st.stop()

# =========================
# 入力UI
# =========================
st.header("制作条件の入力")
video_duration = st.selectbox("尺の長さ", ["15秒", "30秒", "60秒", "その他"])
final_duration = st.text_input("尺の長さ（自由記入）") if video_duration == "その他" else video_duration
num_versions = st.number_input("納品本数", min_value=1, max_value=10, value=1)
shoot_days = st.number_input("撮影日数", min_value=1, max_value=10, value=2)
edit_days = st.number_input("編集日数", min_value=1, max_value=10, value=3)
delivery_date = st.date_input("納品希望日", value=date.today() + relativedelta(months=1))
cast_main = st.number_input("メインキャスト人数", 0, 10, 1)
cast_extra = st.number_input("エキストラ人数", 0, 20, 0)
talent_use = st.checkbox("タレント起用あり")

default_roles = [
    "制作プロデューサー", "制作プロジェクトマネージャー", "ディレクター",
    "カメラマン", "照明スタッフ", "スタイリスト", "ヘアメイク"
]
selected_roles = st.multiselect("必要なスタッフ", default_roles, default=default_roles)
custom_roles_text = st.text_input("その他のスタッフ（カンマ区切り）")
custom_roles = [r.strip() for r in custom_roles_text.split(",") if r.strip()]
staff_roles = selected_roles + custom_roles

shoot_location = st.text_input("撮影場所")
kizai = st.multiselect("撮影機材", ["4Kカメラ", "照明", "ドローン", "グリーンバック"], default=["4Kカメラ","照明"])
set_design_quality = st.selectbox("美術装飾", ["なし","小","中","大"])
use_cg = st.checkbox("CG・VFXあり")
use_narration = st.checkbox("ナレーションあり")
use_music = st.selectbox("音楽", ["既存ライセンス","オリジナル制作","未定"])
ma_needed = st.checkbox("MAあり")
deliverables = st.multiselect("納品形式", ["mp4(16:9)","mp4(1:1)","mp4(9:16)","ProRes"])
subtitle_langs = st.multiselect("字幕言語", ["日本語","英語","その他"])
usage_region = st.selectbox("使用地域", ["日本国内","グローバル","未定"])
usage_period = st.selectbox("使用期間", ["3ヶ月","6ヶ月","1年","2年","無期限","未定"])
budget_hint = st.text_input("参考予算")
extra_notes = st.text_area("その他備考")

model_choice = st.selectbox("使用するAIモデル", ["Gemini 2.5 Pro","GPT-5"])

# =========================
# プロンプト（省略: 上の厳格版を使う）
# =========================
def build_prompt_json() -> str:
    return f"""
あなたは広告映像制作の見積り項目を作成するエキスパートです。
条件に基づき JSON のみを返してください。
...（前回お渡しした厳格プロンプト本文をここにペースト）...
"""

# =========================
# OpenAI呼び出し
# =========================
def call_gpt_json(prompt: str) -> str:
    if USE_OPENAI_CLIENT_V1:
        resp = openai_client.chat.completions.create(model="gpt-5",messages=[{"role":"user","content":prompt}])
        return resp.choices[0].message.content
    else:
        resp = openai_client.ChatCompletion.create(model="gpt-5",messages=[{"role":"user","content":prompt}])
        return resp["choices"][0]["message"]["content"]

def llm_generate_items_json(prompt: str) -> str:
    if model_choice=="Gemini 2.5 Pro":
        model = genai.GenerativeModel("gemini-2.5-pro")
        res = model.generate_content(prompt).text
    else:
        res = call_gpt_json(prompt)
    res = res.strip()
    if res.startswith("```json"):
        res = res.removeprefix("```json").removesuffix("```").strip()
    elif res.startswith("```"):
        res = res.removeprefix("```").removesuffix("```").strip()
    return res

# =========================
# DataFrame 変換 & 集計関数
# =========================
def df_from_items_json(items_json: str) -> pd.DataFrame:
    data = json.loads(items_json)
    items = data.get("items", [])
    return pd.DataFrame(items)

def compute_totals(df_items: pd.DataFrame, base_days: int, target_days: int):
    accel = 1.0
    if target_days < base_days and base_days>0:
        r = (base_days-target_days)/base_days
        accel = round(1+RUSH_K*r,2)
    df = df_items.copy()
    df["小計"] = (df["qty"].astype(float)*df["unit_price"].astype(float)).round().astype(int)
    taxable = int(df["小計"].sum())
    tax = int(round(taxable*TAX_RATE))
    total = taxable+tax
    return df, {"rush_coeff":accel,"taxable":taxable,"tax":tax,"total":total}

# =========================
# 会社テンプレ適用
# =========================
def insert_rows_with_format(ws, start_row, count):
    ws.insert_rows(start_row+1, amount=count)
    for i in range(count):
        for col in range(1, ws.max_column+1):
            cell_above = ws.cell(row=start_row, column=col)
            cell_new = ws.cell(row=start_row+1+i, column=col)
            if cell_above.has_style:
                cell_new._style = copy(cell_above._style)

def fill_company_template(template_bytes: bytes, df_items: pd.DataFrame, meta: dict):
    wb = load_workbook(filename=BytesIO(template_bytes))
    ws = wb.active

    # TODO: あなたのテンプレに合わせて座標を調整
    start_row = 15   # 明細開始行
    start_col = 2    # B列
    subtotal_cell = "F40"
    tax_cell = "F41"
    total_cell = "F42"

    prepared_rows = 10
    needed_rows = len(df_items)
    if needed_rows > prepared_rows:
        insert_rows_with_format(ws, start_row+prepared_rows-1, needed_rows-prepared_rows)

    for i, r in df_items.iterrows():
        row = start_row+i
        ws.cell(row=row, column=start_col+0, value=r["category"])
        ws.cell(row=row, column=start_col+1, value=r["task"])
        ws.cell(row=row, column=start_col+2, value=int(r["unit_price"]))
        ws.cell(row=row, column=start_col+3, value=float(r["qty"]))
        ws.cell(row=row, column=start_col+4, value=r["unit"])
        ws.cell(row=row, column=start_col+5, value=int(r["小計"]))

    ws[subtotal_cell] = int(meta["taxable"])
    ws[tax_cell] = int(meta["tax"])
    ws[total_cell] = int(meta["total"])

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    st.download_button("📥 会社テンプレでダウンロード", buf, "見積もり_会社テンプレ.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# =========================
# 実行
# =========================
if st.button("💡 見積もりを作成"):
    prompt = build_prompt_json()
    items_json = llm_generate_items_json(prompt)
    df_items = df_from_items_json(items_json)
    base_days = shoot_days+edit_days+5
    target_days = (delivery_date-date.today()).days
    df_calc, meta = compute_totals(df_items, base_days, target_days)
    st.session_state["df"]=df_calc
    st.session_state["meta"]=meta
    st.success("✅ 見積もり作成完了")

# =========================
# 出力
# =========================
if st.session_state["df"] is not None:
    st.dataframe(st.session_state["df"])
    tmpl = st.file_uploader("会社見積テンプレートをアップロード", type=["xlsx"])
    if tmpl:
        fill_company_template(tmpl.read(), st.session_state["df"], st.session_state["meta"])
