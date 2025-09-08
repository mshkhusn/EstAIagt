# app.py
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
from openpyxl.cell.cell import MergedCell
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.styles import PatternFill

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

# APIキー設定
genai.configure(api_key=GEMINI_API_KEY)
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY  # v1系/0系どちらでもOK

# =========================
# OpenAI 初期化（v1系/0系 両対応）
# =========================
USE_OPENAI_CLIENT_V1 = False   # True: v1系 OpenAI(), False: v0系 openai.*
openai_client = None
openai_version = "unknown"

try:
    # v1.x 系
    from openai import OpenAI as _OpenAI
    openai_client = _OpenAI()
    USE_OPENAI_CLIENT_V1 = True
    try:
        mod = importlib.import_module("openai")
        openai_version = getattr(mod, "__version__", "1.x")
    except Exception:
        openai_version = "1.x"
except Exception:
    # v0.x 系
    import openai as _openai
    _openai.api_key = OPENAI_API_KEY
    openai_client = _openai
    USE_OPENAI_CLIENT_V1 = False
    openai_version = getattr(openai_client, "__version__", "0.x")

# =========================
# 定数（税率・管理費・短納期）
# =========================
TAX_RATE = 0.10
MGMT_FEE_CAP_RATE = 0.15   # 管理費上限（税抜小計に対する%）
RUSH_K = 0.75              # rush係数: 1 + K * 短縮率

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
# ユーザー入力
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
    "制作プロデューサー", "制作プロジェクトマネージャー", "ディレクター", "カメラマン",
    "照明スタッフ", "スタイリスト", "ヘアメイク"
]
selected_roles = st.multiselect("必要なスタッフ（選択式）", default_roles, default=default_roles)

custom_roles_text = st.text_input("その他のスタッフ（カンマ区切りで自由に追加）")
custom_roles = [role.strip() for role in custom_roles_text.split(",") if role.strip()]
staff_roles = selected_roles + custom_roles

shoot_location = st.text_input("撮影場所（例：都内スタジオ＋ロケ）")
kizai = st.multiselect("撮影機材", ["4Kカメラ", "照明", "ドローン", "グリーンバック"], default=["4Kカメラ", "照明"])
set_design_quality = st.selectbox("セット建て・美術装飾の規模", ["なし", "小（簡易装飾）", "中（通常レベル）", "大（本格セット）"])
use_cg = st.checkbox("CG・VFXあり")
use_narration = st.checkbox("ナレーション収録あり")
use_music = st.selectbox("音楽素材", ["既存ライセンス音源", "オリジナル制作", "未定"])
ma_needed = st.checkbox("MAあり")
deliverables = st.multiselect("納品形式", ["mp4（16:9）", "mp4（1:1）", "mp4（9:16）", "ProRes"])
subtitle_langs = st.multiselect("字幕言語", ["日本語", "英語", "その他"])
usage_region = st.selectbox("使用地域", ["日本国内", "グローバル", "未定"])
usage_period = st.selectbox("使用期間", ["3ヶ月", "6ヶ月", "1年", "2年", "無期限", "未定"])
budget_hint = st.text_input("参考予算（任意）")
extra_notes = st.text_area("その他備考（任意）")

# === モデル選択（Gemini 2.5 Pro / GPT-5） & オプション ===
model_choice = st.selectbox("使用するAIモデル", ["Gemini 2.5 Pro", "GPT-5"])
do_normalize_pass = st.checkbox("LLMで正規化パスをかける（推奨）", value=True)

# =========================
# ユーティリティ
# =========================
def join_or(value_list, empty="なし", sep=", "):
    if not value_list:
        return empty
    return sep.join(map(str, value_list))

def rush_coeff(base_days: int, target_days: int) -> float:
    """短納期係数を計算（target_days: 今日→納品日 / base_days: 撮影+編集+バッファ）"""
    if target_days >= base_days or base_days <= 0:
        return 1.0
    r = (base_days - target_days) / base_days
    return round(1 + RUSH_K * r, 2)

# ---------- プロンプト（厳格版） ----------
def build_prompt_json() -> str:
    staff_roles_str = join_or(staff_roles, empty="未指定")
    kizai_str = join_or(kizai, empty="未指定")
    deliverables_str = join_or(deliverables, empty="未指定")
    subtitle_langs_str = join_or(subtitle_langs, empty="なし")
    shoot_location_str = shoot_location if shoot_location else "未定"
    budget_hint_or_none = budget_hint if budget_hint else "未設定"
    extra_notes_or_none = extra_notes if extra_notes else "特になし"

    return f"""
あなたは広告映像制作の見積り項目を作成するエキスパートです。
以下の「案件条件」と「出力仕様・ルール」を満たし、**JSONのみ**を返してください。

【案件条件】
- 尺: {final_duration}
- 本数: {num_versions}本
- 撮影日数: {shoot_days}日 / 編集日数: {edit_days}日
- 納品希望日: {delivery_date.isoformat()}  （短納期係数や税計算は**サーバ側で行う**ため出力しない）
- キャスト: メイン{cast_main}人 / エキストラ{cast_extra}人 / タレント: {"あり" if talent_use else "なし"}
- スタッフ候補: {staff_roles_str}
- 撮影場所: {shoot_location_str}
- 撮影機材: {kizai_str}
- 美術装飾: {set_design_quality}
- CG: {"あり" if use_cg else "なし"} / ナレーション: {"あり" if use_narration else "なし"} / 音楽: {use_music} / MA: {"あり" if ma_needed else "なし"}
- 納品形式: {deliverables_str}
- 字幕: {subtitle_langs_str}
- 使用地域: {usage_region} / 使用期間: {usage_period}
- 参考予算: {budget_hint_or_none}
- 備考メモ: {extra_notes_or_none}

【出力仕様】
- 返答は **JSON 1オブジェクトのみ**。前後に説明やマークダウンは不要。
- ルートキーは "items"（配列）のみ。
- 各要素は次のキーのみを持つ（順不同可・追加キー禁止）:
  - "category": string  # 次のいずれかに厳格一致 → 「制作人件費」「企画」「撮影費」「出演関連費」「編集費・MA費」「諸経費」「管理費」
  - "task": string      # 項目名（例: "ディレクター", "ロケバス", "カラーグレーディング"）
  - "qty": number       # 数量（整数/少数）
  - "unit": string      # 単位（"日","人","式","本","カット","ページ","台","時間" など）
  - "unit_price": number  # 単価（税抜/税込の明記不要。サーバ側で税計算）
  - "note": string      # 前提・根拠・含む/含まないの注意点（空でも可）
- **禁止**: 合計/小計/税/短納期係数・割増計算、HTMLやテーブル、コードフェンス。
- **管理費は固定金額の1行のみ**（category="管理費", task="管理費（固定）", qty=1, unit="式"）。目安は**全体5–10%**。

【分類規則（厳守）】
- 「制作プロデューサー」「制作PM」「ディレクター」→ 制作人件費
- 「カメラマン」「照明」「録音」「スタイリスト」「ヘアメイク」「機材」「スタジオ」「ロケバス」「美術装飾」→ 撮影費
- 俳優・モデル・エキストラ・キャスティング費・使用料（媒体/期間/地域）→ 出演関連費
- オフライン/オンライン編集・カラー・MA・ナレ撮・字幕/翻訳・VFX/MG → 編集費・MA費
- 交通/宿泊/ケータリング/申請・許認可/雑費/予備費 → 諸経費
- 企画書/コンテ/絵コンテ/演出設計/プリプロ会議 → 企画
- 単位の正規化例：人日→「日」、セット一式→「式」、カット数→「カット」、納品本数→「本」

【価格レンジのガード（1日あたり概算）】
- ディレクター: 80,000–200,000
- プロデューサー/PM: 70,000–160,000
- カメラマン: 80,000–180,000
- 照明: 60,000–140,000
- ヘアメイク/スタイリスト: 40,000–120,000
- 編集（オフ/オン含む）: 60,000–150,000
- カラー: 60,000–150,000
- MA/ナレーター（1時間基準）: 20,000–80,000
- 撮影機材一式（1日）: 50,000–200,000
- スタジオ（1日）: 80,000–300,000
- ロケバス（1日）: 50,000–120,000
※ 逸脱する場合は note に根拠（高難度/大規模/持込/ディスカウント 等）。

【数量の考え方（例）】
- 人員系: 撮影日数×人数、編集は 編集日数×必要ロール（オフ/オン/カラー/MA 等）。
- 機材/スタジオ/ロケバス: 撮影日数に準拠。
- 派生書き出し（1:1/9:16 等）: 納品本数や派生係数で数量化。

【参考予算がある場合】
- 項目削減ではなく、数量・単価の現実的見直しやランク調整で近づける。乖離時は note に理由を記載。

【抜けやすい項目の確認】
- 企画/コンテ、プリプロ会議、機材・スタジオ、ロケバス、交通/宿泊、BGM/SE、素材購入、字幕/翻訳、MA、カラー、VFX、派生書き出し、データ管理、権利表記/クレジット、二次使用（必要なら項目化）。

【最終チェック】
- **管理費（固定）1行**を必ず含める。
- 大きく外れる単価はレンジへ寄せ、noteに補正理由。
- 同義重複は統合・正規化（「演出」→「ディレクター」等）。
- **JSON構造に厳密準拠**、余計なキーや説明・合計は出力しない。
"""

# ---------- 正規化パス用プロンプト ----------
def build_normalize_prompt(items_json: str) -> str:
    return f"""
次のJSONを検査・正規化してください。返答は**修正済みJSONのみ**で、説明は不要です。

【やること】
- スキーマ外のキーは削除。欠損キーは補完（空や0可）。
- category を 次のいずれかに正規化：制作人件費/企画/撮影費/出演関連費/編集費・MA費/諸経費/管理費
- 単位を日本語代表表記に正規化（人日→日、セット→式 等）
- 単価・数量は数値（負値・NaNは0）
- 同義重複の task 名を統合（例: 演出=ディレクター）
- 管理費（固定）は**1行のみ**：category=管理費, task=管理費（固定）, qty=1, unit=式, unit_price=合算額
- 価格レンジからの過度な逸脱は近似値に補正し、noteに理由を追記

【入力JSON】
{items_json}
"""

# ---------- OpenAI呼び出し（v1/v0 両対応） ----------
def call_gpt_json(prompt: str) -> str:
    if USE_OPENAI_CLIENT_V1:
        resp = openai_client.chat.completions.create(
            model="gpt-5",
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content
    else:
        resp = openai_client.ChatCompletion.create(
            model="gpt-5",
            messages=[{"role": "user", "content": prompt}],
        )
        return resp["choices"][0]["message"]["content"]

# ---------- LLM項目生成 ----------
def llm_generate_items_json(prompt: str) -> str:
    try:
        if model_choice == "Gemini 2.5 Pro":
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
    except Exception:
        # フォールバック（最低限動作）
        return json.dumps({"items":[
            {"category":"制作人件費","task":"制作プロデューサー","qty":1,"unit":"日","unit_price":80000,"note":"fallback"},
            {"category":"撮影費","task":"カメラマン","qty":shoot_days,"unit":"日","unit_price":80000,"note":"fallback"},
            {"category":"編集費・MA費","task":"編集","qty":edit_days,"unit":"日","unit_price":70000,"note":"fallback"},
            {"category":"管理費","task":"管理費（固定）","qty":1,"unit":"式","unit_price":120000,"note":"fallback"}
        ]}, ensure_ascii=False)

# ---------- LLM正規化 ----------
def llm_normalize_items_json(items_json: str) -> str:
    try:
        prompt = build_normalize_prompt(items_json)
        if model_choice == "Gemini 2.5 Pro":
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
    except Exception:
        return items_json  # 失敗したら元を返す

# ---------- DataFrame/計算/HTML/Excel ----------
def df_from_items_json(items_json: str) -> pd.DataFrame:
    data = json.loads(items_json)
    items = data.get("items", [])
    norm = []
    for x in items:
        norm.append({
            "category": str(x.get("category","")),
            "task": str(x.get("task","")),
            "qty": float(x.get("qty", 0)),
            "unit": str(x.get("unit","")),
            "unit_price": int(float(x.get("unit_price", 0))),
            "note": str(x.get("note","")),
        })
    return pd.DataFrame(norm)

def compute_totals(df_items: pd.DataFrame, base_days: int, target_days: int):
    """rush適用・管理費キャップ・税・合計を計算"""
    accel = rush_coeff(base_days, target_days)
    df_items = df_items.copy()
    df_items["小計"] = (df_items["qty"] * df_items["unit_price"]).round().astype(int)

    # rushは管理費以外に適用
    is_mgmt = (df_items["category"] == "管理費")
    df_items.loc[~is_mgmt, "小計"] = (df_items.loc[~is_mgmt, "小計"] * accel).round().astype(int)

    # 管理費キャップ
    mgmt_current = int(df_items.loc[is_mgmt, "小計"].sum()) if is_mgmt.any() else 0
    subtotal_after_rush = int(df_items.loc[~is_mgmt, "小計"].sum())
    mgmt_cap = int(round(subtotal_after_rush * MGMT_FEE_CAP_RATE))
    mgmt_final = min(mgmt_current, mgmt_cap) if mgmt_current > 0 else mgmt_cap

    if is_mgmt.any():
        idx = df_items[is_mgmt].index[0]
        df_items.at[idx, "unit_price"] = mgmt_final  # qty=1前提
        df_items.at[idx, "qty"] = 1
        df_items.at[idx, "小計"] = mgmt_final
    else:
        df_items = pd.concat([df_items, pd.DataFrame([{
            "category":"管理費","task":"管理費（固定）","qty":1,"unit":"式","unit_price":mgmt_final,"小計":mgmt_final
        }])], ignore_index=True)

    taxable = int(df_items["小計"].sum())
    tax = int(round(taxable * TAX_RATE))
    total = taxable + tax

    meta = {
        "rush_coeff": accel,
        "subtotal_after_rush_excl_mgmt": subtotal_after_rush,
        "mgmt_fee_final": mgmt_final,
        "taxable": taxable,
        "tax": tax,
        "total": total,
    }
    return df_items, meta

def render_html(df_items: pd.DataFrame, meta: dict) -> str:
    def td_right(x): return f"<td style='text-align:right'>{x}</td>"

    html = []
    html.append("<p>以下は、映像制作にかかる各種費用をカテゴリごとに整理した概算見積書です。</p>")
    html.append(f"<p>短納期係数：{meta['rush_coeff']} ／ 管理費上限：{int(MGMT_FEE_CAP_RATE*100)}% ／ 消費税率：{int(TAX_RATE*100)}%</p>")
    html.append("<table border='1' cellspacing='0' cellpadding='6' style='border-collapse:collapse;width:100%'>")
    html.append("<thead><tr>"
                "<th style='text-align:left'>カテゴリ</th>"
                "<th style='text-align:left'>項目</th>"
                "<th style='text-align:right'>単価</th>"
                "<th style='text-align:left'>数量</th>"
                "<th style='text-align:left'>単位</th>"
                "<th style='text-align:right'>金額（円）</th>"
                "</tr></thead>")
    html.append("<tbody>")

    current_cat = None
    for _, r in df_items.iterrows():
        cat = r.get("category","")
        unit_price_i = int(r.get("unit_price", 0))
        qty_s = str(r.get("qty", ""))
        unit_s = r.get("unit","")
        subtotal_i = int(r.get("小計",0))

        if cat != current_cat:
            html.append(f"<tr><td colspan='6' style='text-align:left;background:#f6f6f6;font-weight:bold'>{cat}</td></tr>")
            current_cat = cat
        html.append(
            "<tr>"
            f"<td>{cat}</td>"
            f"<td>{r.get('task','')}</td>"
            f"{td_right(f'{unit_price_i:,}')}"
            f"<td>{qty_s}</td>"
            f"<td>{unit_s}</td>"
            f"{td_right(f'{subtotal_i:,}')}"
            "</tr>"
        )

    html.append("</tbody></table>")
    html.append(
        f"<p><b>小計（税抜）</b>：{meta['taxable']:,}円　／　"
        f"<b>消費税</b>：{meta['tax']:,}円　／　"
        f"<b>合計</b>：<span style='color:red'>{meta['total']:,}円</span></p>"
    )
    html.append("<p>※本見積書は自動生成された概算です。実制作内容・条件により金額が増減します。</p>")
    return "\n".join(html)

def download_excel(df_items: pd.DataFrame, meta: dict):
    """通常Excel（汎用）出力"""
    out = df_items.copy()
    out = out[["category","task","unit_price","qty","unit","小計"]]
    out.columns = ["カテゴリ","項目","単価（円）","数量","単位","金額（円）"]

    buf = BytesIO()
    try:
        import xlsxwriter  # noqa: F401
        engine = "xlsxwriter"
    except ModuleNotFoundError:
        engine = "openpyxl"

    with pd.ExcelWriter(buf, engine=engine) as writer:
        out.to_excel(writer, index=False, sheet_name="見積もり")

        if engine == "xlsxwriter":
            wb = writer.book
            ws = writer.sheets["見積もり"]
            fmt_int = wb.add_format({"num_format": "#,##0"})
            ws.set_column("A:B", 20)
            ws.set_column("C:C", 14, fmt_int)
            ws.set_column("D:D", 8)
            ws.set_column("E:E", 8)
            ws.set_column("F:F", 14, fmt_int)

            last_row = len(out) + 2  # 1-based
            ws.write(last_row,   4, "小計（税抜）")
            ws.write_number(last_row,   5, int(meta["taxable"]), fmt_int)
            ws.write(last_row+1, 4, "消費税")
            ws.write_number(last_row+1, 5, int(meta["tax"]), fmt_int)
            ws.write(last_row+2, 4, "合計")
            ws.write_number(last_row+2, 5, int(meta["total"]), fmt_int)

        else:
            ws = writer.book["見積もり"]
            widths = {"A":20, "B":20, "C":14, "D":8, "E":8, "F":14}
            for col, w in widths.items():
                ws.column_dimensions[col].width = w
            for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=3, max_col=3):
                for cell in row: cell.number_format = '#,##0'
            for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=6, max_col=6):
                for cell in row: cell.number_format = '#,##0'
            last_row = ws.max_row + 2
            ws.cell(row=last_row,   column=5, value="小計（税抜）")
            ws.cell(row=last_row,   column=6, value=int(meta["taxable"])).number_format = '#,##0'
            ws.cell(row=last_row+1, column=5, value="消費税")
            ws.cell(row=last_row+1, column=6, value=int(meta["tax"])).number_format = '#,##0'
            ws.cell(row=last_row+2, column=5, value="合計")
            ws.cell(row=last_row+2, column=6, value=int(meta["total"])).number_format = '#,##0'

    buf.seek(0)
    st.download_button("📥 Excelでダウンロード", buf, "見積もり.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# =========================
# 会社Excelテンプレ機能：枠拡張（小計前に行挿入）＋Zebraカラー対応
# =========================
TOKEN_ITEMS = "{{ITEMS_START}}"

# 列マップ（このテンプレ専用）
COLMAP = {
    "task": "B",        # 項目
    "qty": "O",         # 数量
    "unit": "Q",        # 単位
    "unit_price": "S",  # 単価
    "amount": "W",      # 金額（数式）
}

# 固定枠定義（テンプレ仕様）
BASE_START_ROW = 19
BASE_END_ROW   = 31   # 19〜31 が既定
BASE_CAPACITY  = BASE_END_ROW - BASE_START_ROW + 1
BASE_SUBTOTAL_ROW = 32  # 初期小計行

# Zebra適用範囲（B〜AA）
DETAIL_START_COL = "B"
DETAIL_END_COL   = "AA"

def _col_to_idx(col):
    return col if isinstance(col, int) else column_index_from_string(col)

DETAIL_START_IDX = _col_to_idx(DETAIL_START_COL)
DETAIL_END_IDX   = _col_to_idx(DETAIL_END_COL)

def _anchor_cell(ws, row, col):
    c = ws.cell(row=row, column=col)
    if isinstance(c, MergedCell):
        for rng in ws.merged_cells.ranges:
            if rng.min_row <= row <= rng.max_row and rng.min_col <= col <= rng.max_col:
                return ws.cell(row=rng.min_row, column=rng.min_col)
    return c

def _find_items_start(ws):
    for row in ws.iter_rows(values_only=False):
        for cell in row:
            if isinstance(cell.value, str) and cell.value.strip() == TOKEN_ITEMS:
                return cell.row, cell.column
    return None, None

def _replicate_merged_row(ws, template_row, target_row):
    """template_row と同じ横方向の結合を target_row に複製"""
    to_add = []
    for rng in list(ws.merged_cells.ranges):
        if rng.min_row == rng.max_row == template_row:
            to_add.append((rng.min_col, rng.max_col))
    for mc, xc in to_add:
        ws.merge_cells(start_row=target_row, start_column=mc,
                       end_row=target_row,   end_column=xc)

def _row_style_copy(ws, src_row, dst_row):
    """src_row のスタイル/高さを dst_row にコピー"""
    ws.row_dimensions[dst_row].height = ws.row_dimensions[src_row].height
    for col in range(1, ws.max_column+1):
        a = ws.cell(row=src_row, column=col)
        b = ws.cell(row=dst_row, column=col)
        if a.has_style:
            b._style = copy(a._style)

def _extract_solid_fill(cell):
    """
    セルの塗りつぶしを安全に取得。
    - solid 以外 / rgb 以外（indexed/theme等）は None を返す。
    - フォールバックは _detect_zebra_fills 側で白/薄グレーにする。
    """
    f = getattr(cell, "fill", None)
    if not f or f.fill_type != "solid":
        return None

    # openpyxlでは fgColor が rgb / indexed / theme のどれか
    color = getattr(f, "fgColor", None)
    rgb = getattr(color, "rgb", None)

    if isinstance(rgb, str) and len(rgb) == 8:
        return PatternFill(fill_type="solid", fgColor=rgb)

    # ここで indexed/theme のときは無理に解決しない（テンプレ色に依存）
    return None

def _detect_zebra_fills(ws, start_row):
    """
    19/20行目（代表列=明細開始列）の色を読み取り、無ければ白/薄グレーにフォールバック。
    """
    c = DETAIL_START_IDX
    f1 = _extract_solid_fill(ws.cell(row=start_row,     column=c))
    f2 = _extract_solid_fill(ws.cell(row=start_row + 1, column=c))

    if f1 is None:
        f1 = PatternFill(fill_type="solid", fgColor="FFFFFFFF")  # 白
    if f2 is None:
        f2 = PatternFill(fill_type="solid", fgColor="FFF2F2F2")  # 薄グレー

    return f1, f2

def _apply_row_fill(ws, row, fill):
    for col in range(DETAIL_START_IDX, DETAIL_END_IDX+1):
        ws.cell(row=row, column=col).fill = fill

def _apply_zebra_for_range(ws, start_row, end_row, f1, f2):
    for r in range(start_row, end_row+1):
        idx = (r - start_row) % 2
        _apply_row_fill(ws, r, f1 if idx==0 else f2)

def _ensure_amount_formula(ws, row, qty_col_idx, price_col_idx, amount_col_idx):
    c = ws.cell(row=row, column=amount_col_idx)
    v = c.value
    if not (isinstance(v, str) and v.startswith("=")):
        qcol = get_column_letter(qty_col_idx)
        pcol = get_column_letter(price_col_idx)
        c.value = f"={qcol}{row}*{pcol}{row}"
        c.number_format = '#,##0'

def _update_subtotal_formula(ws, subtotal_row, end_row, amount_col_idx):
    sub = ws.cell(row=subtotal_row, column=amount_col_idx)
    ac = get_column_letter(amount_col_idx)
    end_col = "AA"
    sub.value = f"=SUM({ac}{BASE_START_ROW}:{end_col}{end_row})"
    sub.number_format = '#,##0'

def _write_company_with_growth(ws, df_items):
    # トークン消去
    r0, c0 = _find_items_start(ws)
    if r0:
        ws.cell(row=r0, column=c0).value = None

    # 列番号
    c_task = _col_to_idx(COLMAP["task"])
    c_qty  = _col_to_idx(COLMAP["qty"])
    c_unit = _col_to_idx(COLMAP["unit"])
    c_price= _col_to_idx(COLMAP["unit_price"])
    c_amt  = _col_to_idx(COLMAP["amount"])

    n = len(df_items)
    lack = max(0, n - BASE_CAPACITY)

    # Zebra色検出
    f1, f2 = _detect_zebra_fills(ws, BASE_START_ROW)

    # 不足分は小計の直前に追加
    if lack > 0:
        ws.insert_rows(BASE_SUBTOTAL_ROW, amount=lack)
        template_row = BASE_END_ROW
        for i in range(lack):
            rr = BASE_SUBTOTAL_ROW + i
            _row_style_copy(ws, template_row, rr)
            _replicate_merged_row(ws, template_row, rr)
            _ensure_amount_formula(ws, rr, c_qty, c_price, c_amt)
        _apply_zebra_for_range(ws, BASE_SUBTOTAL_ROW, BASE_SUBTOTAL_ROW+lack-1, f1, f2)

    # 新しい終端
    end_row = BASE_END_ROW + lack
    subtotal_row = BASE_SUBTOTAL_ROW + lack

    # 全範囲に zebra 再適用
    _apply_zebra_for_range(ws, BASE_START_ROW, end_row, f1, f2)

    # 値クリア
    for r in range(BASE_START_ROW, end_row+1):
        _anchor_cell(ws, r, c_task).value  = None
        _anchor_cell(ws, r, c_qty).value   = None
        _anchor_cell(ws, r, c_unit).value  = None
        _anchor_cell(ws, r, c_price).value = None
        _ensure_amount_formula(ws, r, c_qty, c_price, c_amt)

    # 書き込み
    cap_now = end_row - BASE_START_ROW + 1
    if n > cap_now:
        st.warning(f"テンプレ拡張後の枠（{cap_now}行）を超えました。{n-cap_now} 行は出力されません。")
        n = cap_now

    for i in range(n):
        r = BASE_START_ROW + i
        row = df_items.iloc[i]
        _anchor_cell(ws, r, c_task).value  = str(row.get("task",""))
        _anchor_cell(ws, r, c_qty).value   = float(row.get("qty", 0) or 0)
        _anchor_cell(ws, r, c_unit).value  = str(row.get("unit",""))
        _anchor_cell(ws, r, c_price).value = int(float(row.get("unit_price", 0) or 0))

    # 小計更新
    _update_subtotal_formula(ws, subtotal_row, end_row, c_amt)

def export_with_company_template(template_bytes: bytes,
                                 df_items: pd.DataFrame,
                                 meta: dict,
                                 mode: str = "token",
                                 fixed_config: dict | None = None):
    """
    mode:
      - "token": シート内の {{ITEMS_START}} を探して消去（開始行はテンプレ既定の19行想定）
      - "fixed": 受け取るが、このテンプレは開始行 19 固定前提（将来拡張用）
    """
    wb = load_workbook(filename=BytesIO(template_bytes))
    ws = wb.active

    if mode == "token":
        r0, c0 = _find_items_start(ws)
        if r0:
            ws.cell(row=r0, column=c0).value = None
    # fixed モード指定が来てもテンプレ構造固定のため現状は無視

    _write_company_with_growth(ws, df_items)

    out = BytesIO()
    wb.save(out)
    out.seek(0)
    st.download_button(
        "📥 会社テンプレ（.xlsx）でダウンロード",
        out,
        "見積もり_会社テンプレ.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="dl_company_template"
    )

# =========================
# 実行ボタン
# =========================
if st.button("💡 見積もりを作成"):
    with st.spinner("AIが見積もり項目を作成中…"):
        # 1) 厳格プロンプト → JSON
        prompt = build_prompt_json()
        items_json = llm_generate_items_json(prompt)

        # 2) 任意：正規化パス
        if do_normalize_pass:
            items_json = llm_normalize_items_json(items_json)

        # 3) JSON→DF
        try:
            df_items = df_from_items_json(items_json)
        except Exception:
            st.error("JSONの解析に失敗しました。もう一度お試しください。")
            st.stop()

        # rush計算：基準 = 撮影+編集+5日、目標 = 今日→納品
        base_days = int(shoot_days + edit_days + 5)
        target_days = (delivery_date - date.today()).days

        # 合計計算 & 管理費キャップ
        df_calc, meta = compute_totals(df_items, base_days, target_days)

        # HTML生成
        final_html = render_html(df_calc, meta)

        st.session_state["items_json"] = items_json
        st.session_state["df"] = df_calc
        st.session_state["meta"] = meta
        st.session_state["final_html"] = final_html

# =========================
# 表示 & ダウンロード
# =========================
if st.session_state["final_html"]:
    st.success("✅ 見積もり結果（サーバ計算で整合性チェック済み）")
    st.components.v1.html(st.session_state["final_html"], height=900, scrolling=True)

    # 通常Excel
    download_excel(st.session_state["df"], st.session_state["meta"])

    # 会社テンプレ出力
    st.markdown("---")
    st.subheader("会社Excelテンプレで出力")
    tmpl = st.file_uploader("会社見積テンプレート（.xlsx）をアップロード", type=["xlsx"], key="tmpl_upload")

    mode = st.radio("テンプレの指定方法", ["トークン検出（推奨）", "固定セル指定"], horizontal=True)
    if tmpl is not None:
        if mode == "トークン検出（推奨）":
            st.caption("テンプレに `{{ITEMS_START}}` を置いてください（例：B19）。小計/合計は数式のままでOKです。")
            export_with_company_template(
                tmpl.read(),
                st.session_state["df"],
                st.session_state["meta"],
                mode="token"
            )
        else:
            with st.form("fixed_cells_form"):
                sheet_name = st.text_input("シート名（未入力なら先頭シート）", "")
                start_row = st.number_input("明細開始行（例: 19）", min_value=1, value=19, step=1)
                start_col = st.number_input("明細開始列（A=1, B=2 ... 例: B列は2）", min_value=1, value=2, step=1)
                prepared_rows = st.number_input("テンプレに準備済みの明細行数", min_value=1, value=13, step=1)
                submitted = st.form_submit_button("この設定で出力")
            if submitted:
                cfg = {
                    "sheet_name": sheet_name if sheet_name.strip() else None,
                    "start_row": start_row,
                    "start_col": start_col,
                    "prepared_rows": prepared_rows,
                }
                export_with_company_template(
                    tmpl.read(),
                    st.session_state["df"],
                    st.session_state["meta"],
                    mode="fixed",
                    fixed_config=cfg
                )

# =========================
# 開発者向けダイアグ
# =========================
with st.expander("開発者向け情報（バージョン確認）", expanded=False):
    st.write({
        "openai_version": openai_version,
        "use_openai_client_v1": USE_OPENAI_CLIENT_V1,
    })
