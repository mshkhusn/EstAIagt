# -*- coding: utf-8 -*-
# 概算見積（段階統合 第1弾）– movie_app にUI/プロンプトを寄せつつ、Gemini 2.5 Flashで生成
# - 幅広レイアウト
# - 映像ドメイン限定チェック（任意）
# - movie_app 風の共通条件ブロック + 追加推論（簡易）
# - JSON出力をロバストにパース（コードフェンス/コメント除去、trailing comma除去、literal_eval fallback）
# - SAFETY/空出力対策として軽量再試行（structured → structured簡易 → plain）
# - note（内訳）をテーブルにもExcelにも残す

import os
import re
import json
import ast
from io import BytesIO
from datetime import date

import streamlit as st
import pandas as pd
import google.generativeai as genai

# ====== ページ設定 ======
st.set_page_config(page_title="概算見積（段階統合 v1）", layout="wide")

# ====== Secrets・API Key ======
# Streamlit Cloud の場合は Secrets から。ローカルなら環境変数に直書きでもOK
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", ""))

if not GEMINI_API_KEY:
    st.error("GEMINI_API_KEY が未設定です。`st.secrets` か環境変数に設定してください。")
    st.stop()

genai.configure(api_key=GEMINI_API_KEY)

MODEL_ID = "gemini-2.5-flash"

# =========================================
# JSON パース（頑丈版）
# =========================================
def _strip_code_fences(s: str) -> str:
    if not s:
        return s
    s = s.strip()
    # ```json ... ```
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    # <!-- … --> っぽいのを消す
    s = re.sub(r"<!--.*?-->", "", s, flags=re.DOTALL)
    # // や # で始まる行コメント除去（甘め）
    s = "\n".join([ln for ln in s.splitlines() if not ln.strip().startswith("//") and not ln.strip().startswith("#")])
    return s.strip()

def _remove_trailing_commas(s: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", s)

def robust_coerce_json(s: str):
    if not s:
        return None
    # 1) そのまま
    try:
        return json.loads(s)
    except Exception:
        pass
    # 2) 本体抽出 + 補正
    try:
        first = s.find("{"); last = s.rfind("}")
        if first != -1 and last != -1 and last > first:
            frag = s[first:last+1]
            frag = _remove_trailing_commas(frag)
            frag2 = frag.replace("\r", "")
            # True/False/None のJSON化
            frag2 = re.sub(r"\bTrue\b", "true", frag2)
            frag2 = re.sub(r"\bFalse\b", "false", frag2)
            frag2 = re.sub(r"\bNone\b", "null", frag2)
            # ‘ や ’ → "
            frag2 = frag2.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
            if "'" in frag2 and '"' not in frag2:
                frag2 = frag2.replace("'", '"')
            try:
                return json.loads(frag2)
            except Exception:
                pass
    except Exception:
        pass
    # 3) literal_eval
    try:
        return ast.literal_eval(s)
    except Exception:
        return None

def robust_parse_items_json(raw: str) -> dict:
    s = _strip_code_fences(raw or "")
    obj = robust_coerce_json(s)
    if not isinstance(obj, dict):
        obj = {}
    items = obj.get("items")
    if not isinstance(items, list):
        # よくある別名
        if isinstance(obj.get("result"), dict) and isinstance(obj["result"].get("items"), list):
            items = obj["result"]["items"]
        elif isinstance(obj.get("data"), list):
            items = obj["data"]
        else:
            items = []
    obj["items"] = items
    return obj

# =========================================
# プロンプト（movie_app に寄せた最小形）
# =========================================
def build_prompt(duration_label: str,
                 versions: int,
                 shoot_days: int,
                 edit_days: int,
                 notes: str,
                 limit_video_only: bool) -> str:
    """
    - movie_app の _common_case_block をミニマム再現
    - limit_video_only=True の場合は映像ドメイン限定の指示を付与
    - 生成は items 配列のみ、note（内訳）歓迎, 単価/数量も妥当レンジで
    """
    domain_guard = ""
    if limit_video_only:
        domain_guard = (
            "【重要な制約】この依頼はあくまで映像制作（動画制作）に関する概算見積のみを対象としてください。"
            "印刷物やWebサイト制作など映像以外に該当する見積項目は含めないでください。\n"
        )

    # movie_app風の条件表示（最小）
    common = f"""【案件条件】
- 尺: {duration_label}
- 本数: {versions}本
- 撮影日数: {shoot_days}日 / 編集日数: {edit_days}日
- 備考: {notes if notes.strip() else "特になし"}"""

    # JSON仕様
    spec = """【出力仕様】
- JSON 1オブジェクトのみ。ルートに items 配列。
- 各要素キー: category / task / qty / unit / unit_price / note
- category は「制作費」「撮影費」「編集費・MA費」「出演関連費」「諸経費」「管理費」など、映像制作で自然な分類で構わない。
- qty, unit は妥当（日/式/人/時間/本など）。単価は日本の広告映像相場の一般レンジで推定。
- note は見積項目の内訳・前提・注記を簡潔に。最終出力にも残す。
- 合計や税額などは出力しない。"""

    system_guard = (
        "絶対に説明文や余計な文は出力しないでください。"
        "JSONオブジェクトのみを1個、コードフェンスなしで返してください。"
    )

    prompt = f"""{system_guard}

{domain_guard}
あなたは広告映像制作の見積り項目を作成するエキスパートです。
以下の条件に沿って、**JSONのみ**を返してください。

{common}

{spec}
"""
    return prompt

# =========================================
# Gemini 生成（軽量再試行つき）
# =========================================
def gen_items_with_retry(prompt: str, max_retries: int = 3) -> (dict, str, str):
    """
    - 1回目: structured（JSON強め）
    - 2回目: structured簡易（プロンプト短縮）
    - 3回目: plain（最低仕様）
    """
    model = genai.GenerativeModel(
        MODEL_ID,
        generation_config={
            "temperature": 0.3,
            "top_p": 0.9,
            "max_output_tokens": 2000,
            "response_mime_type": "application/json",  # structured寄り
        },
    )

    last_raw = ""
    finish_label = "UNKNOWN"

    # 1) structured
    try:
        resp = model.generate_content(prompt)
        last_raw = getattr(resp, "text", "") or ""
        finish_label = "structured"
        obj = robust_parse_items_json(last_raw)
        if obj.get("items"):
            return obj, last_raw, finish_label
    except Exception:
        pass

    # 2) structured 簡易
    try:
        p2 = "次の仕様で JSON 1つのみを返してください（items のみ）。keys: category, task, qty, unit, unit_price, note。\n"
        p2 += prompt
        resp2 = model.generate_content(p2)
        last_raw = getattr(resp2, "text", "") or ""
        finish_label = "structured_simple"
        obj = robust_parse_items_json(last_raw)
        if obj.get("items"):
            return obj, last_raw, finish_label
    except Exception:
        pass

    # 3) plain（最低仕様）
    try:
        p3 = (
            "JSONのみを返すこと。コードフェンス不要。"
            "ルートは items 配列のみ。keys: category, task, qty, unit, unit_price, note。\n"
            "（最低限でよいので、撮影費・編集費・管理費など、映像制作の妥当な項目を数個で構成して出力）\n"
        )
        p3 += prompt
        resp3 = model.generate_content(p3)
        last_raw = getattr(resp3, "text", "") or ""
        finish_label = "plain"
        obj = robust_parse_items_json(last_raw)
        if obj.get("items"):
            return obj, last_raw, finish_label
    except Exception:
        pass

    return {"items": []}, last_raw, finish_label

# =========================================
# DataFrame / 計算 / Excel
# =========================================
def df_from_items(obj: dict) -> pd.DataFrame:
    items = obj.get("items", []) or []
    rows = []
    for x in items:
        rows.append({
            "category": str((x or {}).get("category", "")),
            "task": str((x or {}).get("task", "")),
            "qty": pd.to_numeric((x or {}).get("qty", 0), errors="coerce"),
            "unit": str((x or {}).get("unit", "")),
            "unit_price": pd.to_numeric((x or {}).get("unit_price", 0), errors="coerce"),
            "note": str((x or {}).get("note", "")),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=["category","task","qty","unit","unit_price","note"])
    df["qty"] = pd.to_numeric(df["qty"], errors="coerce").fillna(0)
    df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce").fillna(0).astype(int)
    df["amount"] = (df["qty"] * df["unit_price"]).round().astype(int)
    return df

TAX_RATE = 0.10
def summary_from_df(df: pd.DataFrame):
    sub = int(df["amount"].sum()) if not df.empty else 0
    tax = int(round(sub * TAX_RATE))
    total = sub + tax
    return sub, tax, total

def download_excel(df: pd.DataFrame):
    out = df.copy()
    out = out[["category","task","qty","unit","unit_price","amount","note"]]
    out.columns = ["カテゴリ","項目","数量","単位","単価（円）","金額（円）","内訳/注記"]

    buf = BytesIO()
    try:
        import xlsxwriter  # noqa
        engine = "xlsxwriter"
    except ModuleNotFoundError:
        engine = "openpyxl"

    with pd.ExcelWriter(buf, engine=engine) as writer:
        out.to_excel(writer, index=False, sheet_name="見積アイテム")
        if engine == "xlsxwriter":
            wb = writer.book
            ws = writer.sheets["見積アイテム"]
            fmt_int = wb.add_format({"num_format": "#,##0"})
            ws.set_column("A:A", 16)
            ws.set_column("B:B", 28)
            ws.set_column("C:E", 12, fmt_int)
            ws.set_column("F:F", 14, fmt_int)
            ws.set_column("G:G", 40)
        else:
            ws = writer.book["見積アイテム"]
            widths = {"A":16, "B":28, "C":12, "D":12, "E":12, "F":14, "G":40}
            for col,w in widths.items():
                ws.column_dimensions[col].width = w

    buf.seek(0)
    st.download_button(
        "📥 Excelダウンロード（note入り）",
        data=buf,
        file_name="estimate_items.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="dl_xlsx"
    )

# =========================================
# UI（movie_app に段階的に寄せた版）
# =========================================
st.title("概算見積（段階統合：Gemini 2.5 Flash）")

col0, col1, col2 = st.columns([1,1,2])
with col0:
    duration = st.selectbox("尺の長さ", ["15秒", "30秒", "60秒", "90秒", "その他"], index=1)
    versions = st.number_input("納品本数", 1, 10, 1)
with col1:
    shoot_days = st.number_input("撮影日数", 0, 15, 2)
    edit_days  = st.number_input("編集日数", 0, 20, 3)
with col2:
    notes = st.text_area("備考（自由記入）",
                         placeholder="例: インタビューなし、スタジオ撮影、MAあり、BGM既存ライセンス など",
                         height=96)

if duration == "その他":
    duration_label = st.text_input("尺の長さ（自由記入）", value="30秒")
else:
    duration_label = duration

limit_video_only = st.checkbox("映像ドメインに限定（印刷/媒体/Webを含めない）", value=False)

st.markdown("---")

if "raw_text" not in st.session_state:
    st.session_state["raw_text"] = ""
if "gen_finish" not in st.session_state:
    st.session_state["gen_finish"] = ""

btn = st.button("▶ 見積アイテムを生成（Gemini 2.5 Flash）", type="primary")

if btn:
    with st.spinner("AIが見積り項目を作成中…"):
        prompt = build_prompt(
            duration_label=duration_label,
            versions=int(versions),
            shoot_days=int(shoot_days),
            edit_days=int(edit_days),
            notes=notes,
            limit_video_only=limit_video_only
        )
        obj, raw, finish = gen_items_with_retry(prompt, max_retries=3)
        st.session_state["raw_text"] = raw
        st.session_state["gen_finish"] = finish

        df = df_from_items(obj)
        sub, tax, total = summary_from_df(df)

        st.success(f"モデル: {MODEL_ID} / 行数: {len(df)} / finish: {finish}")
        if df.empty:
            st.info("items が空でした。備考をもう少し具体的にすると安定します。")
        else:
            # 見やすい表（note含む）
            st.dataframe(
                df[["category","task","qty","unit","unit_price","note","amount"]]
                  .rename(columns={
                      "category":"カテゴリ","task":"項目","qty":"数量",
                      "unit":"単位","unit_price":"単価（円）","note":"内訳/注記","amount":"金額（円）"
                  }),
                use_container_width=True,
                height=420
            )

        st.write(f"**小計（税抜）**：{sub:,} 円　／　**消費税**：{tax:,} 円　／　**合計**：{total:,} 円")
        download_excel(df)

        with st.expander("デバッグ：生成 RAW（JSONテキストとして整形前）", expanded=False):
            st.code(st.session_state.get("raw_text","") or "(empty)")

else:
    st.caption("※ フィルタ除去は行いません。必要に応じて「映像ドメインに限定」をONにできます。")
