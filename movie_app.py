# app.py (OpenAI v1 専用版)
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
import google.generativeai as genai
from dateutil.relativedelta import relativedelta

# ===== openpyxl / Excel =====
from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.utils import column_index_from_string, get_column_letter

# ===== OpenAI v1 SDK =====
from openai import OpenAI

# =========================
# ページ設定
# =========================
st.set_page_config(page_title="映像制作概算見積エージェント vNext", layout="centered")

# =========================
# Secrets
# =========================
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
APP_PASSWORD   = st.secrets["APP_PASSWORD"]
OPENAI_ORG_ID  = st.secrets.get("OPENAI_ORG_ID", None)

# Gemini 初期化
genai.configure(api_key=GEMINI_API_KEY)

# OpenAI 環境変数（明示）
if not OPENAI_API_KEY:
    st.error("OPENAI_API_KEY が設定されていません。st.secrets を確認してください。")
    st.stop()
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
if OPENAI_ORG_ID:
    os.environ["OPENAI_ORG_ID"] = OPENAI_ORG_ID

# OpenAI v1 クライアント
openai_client = OpenAI()

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
RUSH_K = 0.75

# =========================
# セッション
# =========================
for k in [
    "items_json_raw", "items_json", "df", "meta", "final_html",
    "used_fallback", "fallback_reason", "gemini_block_reason", "model_used"
]:
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
# 入力
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
budget_hint = st.text_input("参考予算（税抜・任意）")

# 備考 + ご指定の注意文
extra_notes = st.text_area("備考（案件概要・要件・想定媒体・必須/除外事項などを自由記入）")
st.caption("※備考に案件概要や条件を追記すると、不足項目の自動補完が働き、見積もりの精度が上がります。")

# モデル選択
model_choice = st.selectbox(
    "使用するAIモデル",
    ["Gemini 2.5 Flash", "Gemini 2.5 Pro", "Gemini 2.0 Flash", "gpt-4.1-mini", "gpt-4.1", "GPT-5"]
)
do_normalize_pass = st.checkbox("LLMで正規化パスをかける（推奨）", value=True)
do_infer_from_notes = st.checkbox("備考から不足項目を推論して補完（推奨）", value=True)

# =========================
# ユーティリティ
# =========================
def join_or(value_list, empty="なし", sep=", "):
    if not value_list:
        return empty
    return sep.join(map(str, value_list))

def rush_coeff(base_days: int, target_days: int) -> float:
    if target_days >= base_days or base_days <= 0:
        return 1.0
    r = (base_days - target_days) / base_days
    return round(1 + RUSH_K * r, 2)

# ---------- 予算パース（税抜） ----------
def parse_budget_hint_jpy(s: str) -> Optional[int]:
    if not s:
        return None
    t = str(s).strip().replace(",", "").replace(" ", "")
    t = t.replace("円", "")
    try:
        if "億" in t:
            n = float(t.replace("億", "") or "0")
            return int(n * 100_000_000)
        if "万" in t:
            n = float(t.replace("万円", "").replace("万", "") or "0")
            return int(n * 10_000)
        n = float(t)
        return int(n)
    except Exception:
        return None

# ---------- JSON ロバストパース ----------
JSON_ITEMS_FALLBACK = {"items": []}

def _strip_code_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()

def _remove_trailing_commas(s: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", s)

def _coerce_json_like(s: str):
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        pass
    try:
        first = s.find("{"); last = s.rfind("}")
        if first != -1 and last != -1 and last > first:
            frag = s[first:last+1]
            frag = _remove_trailing_commas(frag)
            frag2 = frag.replace("\r", "")
            frag2 = re.sub(r"\bTrue\b", "true", frag2)
            frag2 = re.sub(r"\bFalse\b", "false", frag2)
            frag2 = re.sub(r"\bNone\b", "null", frag2)
            if "'" in frag2 and '"' not in frag2:
                frag2 = frag2.replace("'", '"')
            try:
                return json.loads(frag2)
            except Exception:
                pass
    except Exception:
        pass
    try:
        return ast.literal_eval(s)
    except Exception:
        return None

def robust_parse_items_json(raw: str) -> str:
    s = _strip_code_fences(raw)
    obj = _coerce_json_like(s)
    if not isinstance(obj, dict):
        obj = JSON_ITEMS_FALLBACK.copy()
    items = obj.get("items")
    if not isinstance(items, list):
        if isinstance(obj.get("result"), dict) and isinstance(obj["result"].get("items"), list):
            items = obj["result"]["items"]
        elif isinstance(obj.get("data"), list):
            items = obj["data"]
        else:
            items = []
    obj["items"] = items
    return json.dumps(obj, ensure_ascii=False)

# ---------- プロンプト ----------
def _common_case_block() -> str:
    return f"""【案件条件】
- 尺: {final_duration}
- 本数: {num_versions}本
- 撮影日数: {shoot_days}日 / 編集日数: {edit_days}日
- 納品希望日: {delivery_date.isoformat()}
- キャスト: メイン{cast_main}人 / エキストラ{cast_extra}人 / タレント: {"あり" if talent_use else "なし"}
- スタッフ候補: {join_or(staff_roles, empty="未指定")}
- 撮影場所: {shoot_location if shoot_location else "未定"}
- 撮影機材: {join_or(kizai, empty="未指定")}
- 美術装飾: {set_design_quality}
- CG: {"あり" if use_cg else "なし"} / ナレーション: {"あり" if use_narration else "なし"} / 音楽: {use_music} / MA: {"あり" if ma_needed else "なし"}
- 納品形式: {join_or(deliverables, empty="未定")}
- 字幕: {join_or(subtitle_langs, empty="なし")}
- 使用地域: {usage_region} / 使用期間: {usage_period}
- 参考予算（税抜）: {budget_hint if budget_hint else "未設定"}
- 備考: {extra_notes if extra_notes else "特になし"}"""

def _inference_block() -> str:
    if not do_infer_from_notes:
        return ""
    return """
- 備考や案件概要、一般的な広告映像制作の慣行から、未指定の必須/付随項目を推論して適宜補完すること。
"""

def build_prompt_json() -> str:
    return f"""
あなたは広告映像制作の見積り項目を作成するエキスパートです。
以下の条件を満たし、**JSONのみ**を返してください。

{_common_case_block()}

【出力仕様】
- JSON 1オブジェクト、ルートは items 配列のみ。
- 各要素キー: category / task / qty / unit / unit_price / note
- category は「制作人件費」「企画」「撮影費」「出演関連費」「編集費・MA費」「諸経費」「管理費」いずれか。
{_inference_block()}
- qty, unit は妥当な値（日/式/人/時間/カット等）。単価は日本の広告映像相場の一般レンジで推定。
- 管理費は固定1行（task=管理費（固定）, qty=1, unit=式）。
- 合計/税/HTMLなどは出力しない。
"""

# ---------- モデルIDマッピング ----------
def _gemini_model_id_from_choice(choice: str) -> str:
    if "2.5 Flash" in choice:
        return "gemini-2.5-flash"
    if "2.5 Pro" in choice:
        return "gemini-2.5-pro"
    if "2.0 Flash" in choice:
        return "gemini-2.0-flash"
    return "gemini-2.5-flash"

def _map_openai_model(choice: str) -> str:
    if choice == "gpt-4.1-mini":
        return "gpt-4.1-mini"
    if choice == "gpt-4.1":
        return "gpt-4.1"
    if choice == "GPT-5":
        st.warning("このAPIキーでは GPT-5 が未開放の可能性があるため、gpt-4.1 に自動切替します。")
        return "gpt-4.1"
    return "gpt-4.1"

# ---------- LLM 呼び出し ----------
def llm_generate_items_json(prompt: str) -> str:
    """
    選択モデルで items JSON を生成。
    Geminiは .text が空のとき candidates.parts[].text から復元。
    """
    def _robust_extract_gemini_text(resp) -> str:
        try:
            if hasattr(resp, "text") and resp.text:
                return resp.text
        except Exception:
            pass
        try:
            cands = getattr(resp, "candidates", None) or []
            for c in cands:
                content = getattr(c, "content", None)
                if not content:
                    continue
                parts = getattr(content, "parts", None) or []
                buf = []
                for p in parts:
                    t = getattr(p, "text", None)
                    if t:
                        buf.append(t)
                if buf:
                    return "".join(buf)
        except Exception:
            pass
        return ""

    try:
        st.session_state["used_fallback"] = False
        st.session_state["fallback_reason"] = None
        st.session_state["gemini_block_reason"] = None
        st.session_state["model_used"] = None

        if model_choice.startswith("Gemini"):
            model_id = _gemini_model_id_from_choice(model_choice)
            model = genai.GenerativeModel(
                model_id,
                generation_config={
                    "response_mime_type": "application/json",
                    "candidate_count": 1,
                    "temperature": 0.4,
                    "top_p": 0.9,
                    "max_output_tokens": 2500,
                },
                # Civic Integrity / Toxicity は指定しない（SDK未対応版があるため）
                safety_settings=[
                    {"category": "HARM_CATEGORY_HARASSMENT",       "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_HATE_SPEECH",       "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_SEXUAL",            "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                ],
            )
            resp = model.generate_content(prompt)
            try:
                pf = getattr(resp, "prompt_feedback", None)
                st.session_state["gemini_block_reason"] = getattr(pf, "block_reason", None) if pf else None
            except Exception:
                pass
            res = _robust_extract_gemini_text(resp)
            if not res or len(res.strip()) < 5:
                model2 = genai.GenerativeModel(
                    model_id,
                    generation_config={"candidate_count": 1, "temperature": 0.4, "top_p": 0.9, "max_output_tokens": 2500},
                    safety_settings=[
                        {"category": "HARM_CATEGORY_HARASSMENT",       "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_HATE_SPEECH",       "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_SEXUAL",            "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                    ],
                )
                resp2 = model2.generate_content(prompt)
                res = _robust_extract_gemini_text(resp2)
            st.session_state["model_used"] = model_id

        else:
            gpt_model = _map_openai_model(model_choice)
            resp = openai_client.chat.completions.create(
                model=gpt_model,
                messages=[
                    {"role": "system", "content": "You MUST return a single valid JSON object only."},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=8000,
            )
            res = resp.choices[0].message.content or ""
            st.session_state["model_used"] = gpt_model

        st.session_state["items_json_raw"] = res

        if not res or len(res.strip()) < 5:
            raise RuntimeError("LLM empty/short response")

        parsed = robust_parse_items_json(res)
        try:
            if not json.loads(parsed).get("items"):
                raise RuntimeError("Parsed items empty")
        except Exception:
            raise RuntimeError("Parsed items malformed")

        return parsed

    except Exception as e:
        st.session_state["used_fallback"] = True
        st.session_state["fallback_reason"] = f"{type(e).__name__}: {str(e)[:200]}"
        st.warning("⚠️ モデル応答の解析に失敗しました。固定のfallbackを使用します。\n"
                   f"reason={type(e).__name__}: {str(e)[:200]}")
        fallback = {
            "items":[
                {"category":"制作人件費","task":"制作プロデューサー","qty":1,"unit":"日","unit_price":80000,"note":"fallback"},
                {"category":"撮影費","task":"カメラマン","qty":max(1, int(shoot_days)),"unit":"日","unit_price":80000,"note":"fallback"},
                {"category":"編集費・MA費","task":"編集","qty":max(1, int(edit_days)),"unit":"日","unit_price":70000,"note":"fallback"},
                {"category":"管理費","task":"管理費（固定）","qty":1,"unit":"式","unit_price":120000,"note":"fallback"}
            ]
        }
        st.session_state["items_json_raw"] = json.dumps(fallback, ensure_ascii=False)
        return json.dumps(fallback, ensure_ascii=False)

def llm_normalize_items_json(items_json: str) -> str:
    try:
        prompt = f"""
次のJSONを検査・正規化してください。返答は**修正済みJSONのみ**で、説明は不要です。
- スキーマ外キー削除、欠損補完（qty/unit/unit_price/note）
- category 正規化（制作人件費/企画/撮影費/出演関連費/編集費・MA費/諸経費/管理費）
- 単位表記のゆれを正規化
- 管理費は固定1行（task=管理費（固定）, qty=1, unit=式）
【入力JSON】
{items_json}
"""
        if model_choice.startswith("Gemini"):
            model_id = _gemini_model_id_from_choice(model_choice)
            model = genai.GenerativeModel(
                model_id,
                generation_config={
                    "response_mime_type": "application/json",
                    "candidate_count": 1,
                    "temperature": 0.2,
                    "top_p": 0.9,
                    "max_output_tokens": 2000,
                },
            )
            res = model.generate_content(prompt).text
        else:
            gpt_model = _map_openai_model(model_choice)
            resp = openai_client.chat.completions.create(
                model=gpt_model,
                messages=[
                    {"role": "system", "content": "You MUST return a single valid JSON object only."},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=4000,
            )
            res = resp.choices[0].message.content or ""

        return robust_parse_items_json(res)
    except Exception:
        return items_json

# ---------- 計算 ----------
def df_from_items_json(items_json: str) -> pd.DataFrame:
    data = json.loads(items_json)
    items = data.get("items", [])
    norm = []
    for x in items:
        norm.append({
            "category": str(x.get("category","")),
            "task": str(x.get("task","")),
            "qty": float(x.get("qty", 0) or 0),
            "unit": str(x.get("unit","")),
            "unit_price": int(float(x.get("unit_price", 0) or 0)),
            "note": str(x.get("note","")),
        })
    return pd.DataFrame(norm)

def compute_totals(df_items: pd.DataFrame, base_days: int, target_days: int):
    accel = rush_coeff(base_days, target_days)
    df_items = df_items.copy()
    df_items["小計"] = (df_items["qty"] * df_items["unit_price"]).round().astype(int)

    is_mgmt = (df_items["category"] == "管理費")
    df_items.loc[~is_mgmt, "小計"] = (df_items.loc[~is_mgmt, "小計"] * accel).round().astype(int)

    mgmt_current = int(df_items.loc[is_mgmt, "小計"].sum()) if is_mgmt.any() else 0
    subtotal_after_rush = int(df_items.loc[~is_mgmt, "小計"].sum())
    mgmt_cap = int(round(subtotal_after_rush * MGMT_FEE_CAP_RATE))
    mgmt_final = min(mgmt_current, mgmt_cap) if mgmt_current > 0 else mgmt_cap

    if is_mgmt.any():
        idx = df_items[is_mgmt].index[0]
        df_items.at[idx, "unit_price"] = mgmt_final
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

# ---------- 予算に（税抜）で寄せる ----------
def scale_prices_to_budget(df_items: pd.DataFrame,
                           base_days: int,
                           target_days: int,
                           target_taxable_jpy: int,
                           low: float = 0.6,
                           high: float = 1.6,
                           round_to: int = 100) -> pd.DataFrame:
    df_now, meta_now = compute_totals(df_items, base_days, target_days)
    nonmgmt_after_rush = float(meta_now["subtotal_after_rush_excl_mgmt"])
    if nonmgmt_after_rush <= 0:
        return df_items.copy()

    desired_nonmgmt_after_rush = target_taxable_jpy / (1.0 + MGMT_FEE_CAP_RATE)
    s = desired_nonmgmt_after_rush / nonmgmt_after_rush
    s = max(low, min(high, s))

    df_scaled = df_items.copy()
    is_mgmt = (df_scaled["category"] == "管理費")

    df_scaled.loc[~is_mgmt, "unit_price"] = (
        df_scaled.loc[~is_mgmt, "unit_price"].astype(float) * s
    ).round().astype(int)

    if round_to and round_to > 1:
        def _round(x): return int(round(x / round_to) * round_to)
        df_scaled.loc[~is_mgmt, "unit_price"] = df_scaled.loc[~is_mgmt, "unit_price"].map(_round)

    return df_scaled

# ---------- 表示 ----------
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
        if cat != current_cat:
            html.append(f"<tr><td colspan='6' style='text-align:left;background:#f6f6f6;font-weight:bold'>{cat}</td></tr>")
            current_cat = cat
        unit_price_str = f"{int(r.get('unit_price',0)):,}"
        qty_str = str(r.get('qty',''))
        unit_str = r.get('unit','')
        amount_str = f"{int(r.get('小計',0)):,}"
        task_str = r.get('task','')
        html.append(
            "<tr>"
            f"<td>{cat}</td>"
            f"<td>{task_str}</td>"
            f"{td_right(unit_price_str)}"
            f"<td>{qty_str}</td>"
            f"<td>{unit_str}</td>"
            f"{td_right(amount_str)}"
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
            last_row = len(out) + 2
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
# DD見積書テンプレ出力（事前拡張テンプレ対応：行挿入なし）
# =========================
TOKEN_ITEMS = "{{ITEMS_START}}"
COLMAP = {"task": "B", "qty": "O", "unit": "Q", "unit_price": "S", "amount": "W"}
BASE_START_ROW    = 19
BASE_SUBTOTAL_ROW = 72

def _find_token(ws, token: str):
    for row in ws.iter_rows(values_only=False):
        for cell in row:
            if isinstance(cell.value, str) and cell.value.strip() == token:
                return cell.row, cell.column
    return None, None

def _ensure_amount_formula(ws, row, qty_col_idx, price_col_idx, amount_col_idx):
    c = ws.cell(row=row, column=amount_col_idx)
    v = c.value
    if not (isinstance(v, str) and v.startswith("=")):
        qcol = get_column_letter(qty_col_idx)
        pcol = get_column_letter(price_col_idx)
        c.value = f"={qcol}{row}*{pcol}{row}"
    c.number_format = '#,##0'

def _update_subtotal_formula(ws, subtotal_row, start_row, end_row, amount_col_idx):
    ac = get_column_letter(amount_col_idx)
    if end_row < start_row:
        ws.cell(row=subtotal_row, column=amount_col_idx).value = 0
        ws.cell(row=subtotal_row, column=amount_col_idx).number_format = '#,##0'
    else:
        ws.cell(row=subtotal_row, column=amount_col_idx).value = f"=SUM({ac}{start_row}:{ac}{end_row})"
        ws.cell(row=subtotal_row, column=amount_col_idx).number_format = '#,##0'

def _find_subtotal_anchor_auto(ws, amount_col_idx: int):
    last_r = None
    for r in range(1, ws.max_row + 1):
        v = ws.cell(row=r, column=amount_col_idx).value
        if isinstance(v, str):
            s = v.strip().upper()
            if s.startswith("=") and "SUM(" in s:
                last_r = r
    if last_r is not None:
        return last_r, amount_col_idx
    return None, None

def _write_preextended(ws, df_items: pd.DataFrame):
    r0, c0 = _find_token(ws, TOKEN_ITEMS)
    if r0:
        ws.cell(row=r0, column=c0).value = None
    start_row = r0 or BASE_START_ROW

    c_task = column_index_from_string(COLMAP["task"])
    c_qty  = column_index_from_string(COLMAP["qty"])
    c_unit = column_index_from_string(COLMAP["unit"])
    c_price= column_index_from_string(COLMAP["unit_price"])
    c_amt  = column_index_from_string(COLMAP["amount"])

    sub_r, _ = _find_subtotal_anchor_auto(ws, c_amt)
    if sub_r is None:
        sub_r = BASE_SUBTOTAL_ROW
    end_row = sub_r - 1
    capacity = end_row - start_row + 1
    n = len(df_items)

    if capacity <= 0:
        st.error("テンプレートの明細枠が不正です（小計行がITEMS_STARTより上にあります）。")
        return
    if n > capacity:
        st.warning(f"テンプレの明細枠（{capacity}行）を超えました。先頭から{capacity}行のみを書き込みます。")
        n = capacity

    for r in range(start_row, end_row + 1):
        cell_task = ws.cell(row=r, column=c_task)
        if not isinstance(cell_task, MergedCell):
            cell_task.value = None
        ws.cell(row=r, column=c_qty).value   = None
        ws.cell(row=r, column=c_unit).value  = None
        ws.cell(row=r, column=c_price).value = None
        _ensure_amount_formula(ws, r, c_qty, c_price, c_amt)

    for i in range(n):
        r = start_row + i
        row = df_items.iloc[i]
        ws.cell(row=r, column=c_task).value  = str(row.get("task",""))
        ws.cell(row=r, column=c_qty).value   = float(row.get("qty", 0) or 0)
        ws.cell(row=r, column=c_unit).value  = str(row.get("unit",""))
        ws.cell(row=r, column=c_price).value = int(float(row.get("unit_price", 0) or 0))

    last_detail_row = start_row + n - 1 if n > 0 else start_row - 1
    _update_subtotal_formula(ws, sub_r, start_row, last_detail_row, c_amt)

def export_with_template(template_bytes: bytes, df_items: pd.DataFrame, meta: dict):
    wb = load_workbook(filename=BytesIO(template_bytes))
    ws = wb.active
    _write_preextended(ws, df_items)
    out = BytesIO()
    wb.save(out)
    out.seek(0)
    st.download_button(
        "📥 DD見積書テンプレ（.xlsx）でダウンロード",
        out,
        "見積もり_DDテンプレ.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="dl_dd_template"
    )

# =========================
# 実行
# =========================
if st.button("💡 見積もりを作成"):
    with st.spinner("AIが見積もり項目を作成中…"):
        prompt = build_prompt_json()
        items_json_str = llm_generate_items_json(prompt)

        if do_normalize_pass:
            items_json_str = llm_normalize_items_json(items_json_str)

        try:
            df_items = df_from_items_json(items_json_str)
        except Exception:
            st.error("JSONの解析に失敗しました。もう一度お試しください。")
            with st.expander("デバッグ：モデル生出力を見る"):
                st.code(st.session_state.get("items_json_raw", "(no raw)"))
            with st.expander("デバッグ：ロバスト整形後JSONを見る"):
                st.code(items_json_str, language="json")
            st.stop()

        base_days = int(shoot_days + edit_days + 5)
        target_days = (delivery_date - date.today()).days

        # --- 通常計算 ---
        df_calc, meta = compute_totals(df_items, base_days, target_days)

        # --- 参考予算（税抜）に合わせて調整 ---
        budget_total = parse_budget_hint_jpy(budget_hint)
        if budget_total:
            df_scaled = scale_prices_to_budget(
                df_items=df_items,
                base_days=base_days,
                target_days=target_days,
                target_taxable_jpy=budget_total,
            )
            df_calc, meta = compute_totals(df_scaled, base_days, target_days)
            df_items = df_scaled  # 以降の出力はスケール後

        final_html = render_html(df_calc, meta)

        st.session_state["items_json"] = items_json_str
        st.session_state["df"] = df_calc
        st.session_state["meta"] = meta
        st.session_state["final_html"] = final_html

# =========================
# 表示 & ダウンロード
# =========================
if st.session_state["final_html"]:
    st.info({
        "model_choice": model_choice,
        "normalize_pass": do_normalize_pass,
        "used_fallback": bool(st.session_state.get("used_fallback")),
        "fallback_reason": st.session_state.get("fallback_reason"),
        "gemini_block_reason": st.session_state.get("gemini_block_reason"),
        "model_used": st.session_state.get("model_used") or "(n/a)"
    })

    st.success("✅ 見積もり結果（サーバ計算で整合性チェック済み）")
    st.components.v1.html(st.session_state["final_html"], height=900, scrolling=True)
    download_excel(st.session_state["df"], st.session_state["meta"])

    st.markdown("---")
    st.subheader("DD見積書テンプレで出力")
    tmpl = st.file_uploader("DD見積書テンプレート（.xlsx）をアップロード", type=["xlsx"], key="tmpl_upload")
    if tmpl is not None:
        st.caption("テンプレに `{{ITEMS_START}}` を明細1行目（例：B19）に置いてください。小計セルはW列のSUM式で自動検出（例：W72）。行挿入は行いません。")
        export_with_template(tmpl.read(), st.session_state["df"], st.session_state["meta"])

    with st.expander("デバッグ：モデル生出力（RAW）", expanded=False):
        st.code(st.session_state.get("items_json_raw", "(no raw)"))

# =========================
# 開発者向け
# =========================
with st.expander("OpenAI 接続テスト（任意）", expanded=False):
    if st.button("▶︎ gpt-4.1-mini に簡易テスト送信"):
        try:
            r = openai_client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": "Return {\"ok\":true} as JSON only."}],
                response_format={"type": "json_object"},
                max_tokens=100,
            )
            st.code(r.choices[0].message.content or "(empty)")
        except Exception as e:
            st.error(f"OpenAI呼び出しで例外: {type(e).__name__}: {str(e)[:300]}")

with st.expander("開発者向け情報（バージョン確認）", expanded=False):
    st.write({
        "openai_version": openai_version,
        "infer_from_notes": do_infer_from_notes,
        "normalize_pass": do_normalize_pass,
        "model_choice": model_choice,
    })
