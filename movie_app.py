# app.py
import os
import json
import importlib
from io import BytesIO
from datetime import date

import streamlit as st
import pandas as pd
import google.generativeai as genai
from dateutil.relativedelta import relativedelta

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
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY  # v1系でもv0系でも害なし

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
MGMT_FEE_CAP_RATE = 0.15   # 種別で変えるなら外部YAML化推奨
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

# === モデル選択（Gemini 2.5 Pro / GPT-5） ===
model_choice = st.selectbox("使用するAIモデル", ["Gemini 2.5 Pro", "GPT-5"])

# =========================
# ユーティリティ
# =========================
def rush_coeff(base_days: int, target_days: int) -> float:
    """短納期係数を計算（target_days: 今日→納品日 / base_days: 撮影+編集+バッファ）"""
    if target_days >= base_days or base_days <= 0:
        return 1.0
    r = (base_days - target_days) / base_days
    return round(1 + RUSH_K * r, 2)

def build_prompt_json() -> str:
    """LLMへのプロンプト（JSONのみ出力させる）"""
    return f"""
あなたは広告制作費の見積り項目を作る専門家です。以下条件から、**JSONのみ**で返してください。
必須仕様:
- 最上位に "items": Array を持つJSON
- 各itemは {{ "category": str, "task": str, "qty": number, "unit": str, "unit_price": number, "note": str }} のみ
- **金額の合計やHTMLは出力しない**
- 管理費は「固定金額」で item を1つだけ作成（categoryは「管理費」、taskは「管理費（固定）」）。全体5〜10%相当を目安に案出し。
- 単価は整数、数量は整数または小数OK
- カテゴリは以下から用いる：制作人件費/企画/撮影費/出演関連費/編集費・MA費/諸経費/管理費

条件:
- 尺: {final_duration}
- 本数: {num_versions}本
- 撮影日数: {shoot_days}日
- 編集日数: {edit_days}日
- 納品希望日: {delivery_date.isoformat()}
- メインキャスト: {cast_main}人 / エキストラ: {cast_extra}人 / タレント: {"あり" if talent_use else "なし"}
- スタッフ: {", ".join(staff_roles) if staff_roles else "未指定"}
- 撮影場所: {shoot_location or "未定"}
- 撮影機材: {", ".join(kizai) if kizai else "未指定"}
- 美術装飾: {set_design_quality}
- CG: {"あり" if use_cg else "なし"} / ナレーション: {"あり" if use_narration else "なし"} / 音楽: {use_music} / MA: {"あり" if ma_needed else "なし"}
- 納品形式: {", ".join(deliverables) if deliverables else "未指定"}
- 字幕: {", ".join(subtitle_langs) if subtitle_langs else "なし"}
- 地域: {usage_region} / 期間: {usage_period}
- 参考予算: {budget_hint or "未設定"}
- 備考: {extra_notes or "特になし"}

出力は**JSONのみ**、前後の説明やマークダウン禁止。
"""

def call_gpt_json(prompt: str) -> str:
    """GPT-5 を呼び出し（v1系/0系 どちらでも動く）"""
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

def llm_generate_items_json(prompt: str) -> str:
    """
    LLMからJSON（items配列）だけを受け取る。
    期待JSON:
    {
      "items": [
        {"category":"撮影費","task":"カメラマン","qty":2,"unit":"日","unit_price":80000,"note":""},
        ...
        {"category":"管理費","task":"管理費（固定）","qty":1,"unit":"式","unit_price":120000,"note":""}
      ]
    }
    """
    try:
        if model_choice == "Gemini 2.5 Pro":
            model = genai.GenerativeModel("gemini-2.5-pro")
            res = model.generate_content(prompt).text
        else:  # GPT-5
            res = call_gpt_json(prompt)

        # JSONフェンス除去
        res = res.strip()
        if res.startswith("```json"):
            res = res.removeprefix("```json").removesuffix("```").strip()
        elif res.startswith("```"):
            res = res.removeprefix("```").removesuffix("```").strip()
        return res

    except Exception:
        # フォールバック（最小骨格）
        return json.dumps({"items":[
            {"category":"制作人件費","task":"制作プロデューサー","qty":1,"unit":"日","unit_price":80000,"note":"fallback"},
            {"category":"撮影費","task":"カメラマン","qty":shoot_days,"unit":"日","unit_price":80000,"note":"fallback"},
            {"category":"編集費・MA費","task":"編集","qty":edit_days,"unit":"日","unit_price":70000,"note":"fallback"},
            {"category":"管理費","task":"管理費（固定）","qty":1,"unit":"式","unit_price":120000,"note":"fallback"}
        ]}, ensure_ascii=False)

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
    """カテゴリ見出し付きのHTMLテーブルを生成（安全にサーバ側で作成）"""
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
        if cat != current_cat:
            html.append(f"<tr><td colspan='6' style='text-align:left;background:#f6f6f6;font-weight:bold'>{cat}</td></tr>")
            current_cat = cat
        html.append(
            "<tr>"
            f"<td>{cat}</td>"
            f"<td>{r.get('task','')}</td>"
            f"{td_right(f'{int(r.get('unit_price',0)):,}')}"
            f"<td>{str(r.get('qty',''))}</td>"
            f"<td>{r.get('unit','')}</td>"
            f"{td_right(f'{int(r.get('小計',0)):,}')}"
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
    """Excel出力（xlsxwriter が無ければ openpyxl に自動フォールバック）"""
    out = df_items.copy()
    out = out[["category","task","unit_price","qty","unit","小計"]]
    out.columns = ["カテゴリ","項目","単価（円）","数量","単位","金額（円）"]

    buf = BytesIO()

    # 利用可能なエンジンを自動選択
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

            last_row = len(out) + 2  # 1-based（ヘッダー込み）
            ws.write(last_row,   4, "小計（税抜）")
            ws.write_number(last_row,   5, int(meta["taxable"]), fmt_int)
            ws.write(last_row+1, 4, "消費税")
            ws.write_number(last_row+1, 5, int(meta["tax"]), fmt_int)
            ws.write(last_row+2, 4, "合計")
            ws.write_number(last_row+2, 5, int(meta["total"]), fmt_int)

        else:  # openpyxl
            from openpyxl.utils import get_column_letter
            ws = writer.book["見積もり"]
            # 列幅
            widths = {"A":20, "B":20, "C":14, "D":8, "E":8, "F":14}
            for col, w in widths.items():
                ws.column_dimensions[col].width = w
            # 数値列の表示形式（#,##0）
            for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=3, max_col=3):
                for cell in row: cell.number_format = '#,##0'
            for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=6, max_col=6):
                for cell in row: cell.number_format = '#,##0'
            # 合計の追記（値書き込み）
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
# 実行ボタン
# =========================
if st.button("💡 見積もりを作成"):
    with st.spinner("AIが見積もり項目を作成中…"):
        prompt = build_prompt_json()
        items_json = llm_generate_items_json(prompt)

        # JSON→DF
        try:
            df_items = df_from_items_json(items_json)
        except Exception:
            st.error("JSONの解析に失敗しました。入力条件を見直すか、もう一度お試しください。")
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
    download_excel(st.session_state["df"], st.session_state["meta"])

# =========================
# 開発者向けダイアグ
# =========================
with st.expander("開発者向け情報（バージョン確認）", expanded=False):
    st.write({
        "openai_version": openai_version,
        "use_openai_client_v1": USE_OPENAI_CLIENT_V1,
    })
