# movie_app.py — 段階2c: Gemini 2.5 Flash 専用 + JSONモード + SAFETY回避 + 計算/HTML/Excel
# 依存: streamlit, pandas, google-generativeai, python-dateutil, openpyxl or xlsxwriter
# Secrets: GEMINI_API_KEY, APP_PASSWORD

import re
import os
import json
import ast
from typing import Optional
from io import BytesIO
from datetime import date

import streamlit as st
import pandas as pd
import google.generativeai as genai
from dateutil.relativedelta import relativedelta

from openpyxl import load_workbook  # noqa

# === ページ / Secrets ===
st.set_page_config(page_title="映像制作概算見積（Gemini 2.5 Flash）", layout="centered")
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
APP_PASSWORD   = st.secrets.get("APP_PASSWORD", "")

if not GEMINI_API_KEY:
    st.error("GEMINI_API_KEY が未設定です。Secrets を確認してください。")
    st.stop()

genai.configure(api_key=GEMINI_API_KEY)
GEMINI_MODEL_ID = "gemini-2.5-flash"

# === 定数 ===
TAX_RATE = 0.10
MGMT_FEE_CAP_RATE = 0.15
RUSH_K = 0.75

FINISH_REASON_MAP = {
    0: "FINISH_REASON_UNSPECIFIED",
    1: "STOP",
    2: "SAFETY",
    3: "RECITATION",
    4: "OTHER",
}

# === セッション ===
for k in ["items_json_raw", "items_json", "df", "meta", "final_html",
          "model_used", "gemini_raw_dict", "gemini_finish_reason"]:
    if k not in st.session_state:
        st.session_state[k] = None

# === 認証 ===
st.title("映像制作概算見積（Gemini 2.5 Flash）")
if APP_PASSWORD:
    pw = st.text_input("パスワード", type="password")
    if pw != APP_PASSWORD:
        st.warning("🔒 認証が必要です")
        st.stop()

# === 入力UI ===
st.header("制作条件の入力")
video_duration = st.selectbox("尺の長さ", ["15秒", "30秒", "60秒", "その他"])
final_duration = st.text_input("尺の長さ（自由記入）") if video_duration == "その他" else video_duration
num_versions = st.number_input("納品本数", min_value=1, max_value=10, value=1)
shoot_days = st.number_input("撮影日数", min_value=1, max_value=10, value=2)
edit_days = st.number_input("編集日数", min_value=1, max_value=10, value=3)
delivery_date = st.date_input("納品希望日", value=date.today() + relativedelta(months=1))

cast_main = st.number_input("メインキャスト人数", 0, 10, 1)
cast_extra = st.number_input("エキストラ人数", 0, 30, 0)
talent_use = st.checkbox("タレント起用あり")

default_roles = [
    "制作プロデューサー", "制作PM", "ディレクター", "カメラマン",
    "照明", "スタイリスト", "ヘアメイク"
]
selected_roles = st.multiselect("必要スタッフ", default_roles, default=default_roles)

custom_roles_text = st.text_input("その他のスタッフ（カンマ区切り）")
custom_roles = [s.strip() for s in custom_roles_text.split(",") if s.strip()]
staff_roles = selected_roles + custom_roles

shoot_location = st.text_input("撮影場所（例：都内スタジオ＋ロケ）")
kizai = st.multiselect("撮影機材", ["4Kカメラ", "照明", "ドローン", "グリーンバック"], default=["4Kカメラ", "照明"])
set_design_quality = st.selectbox("セット/美術規模", ["なし", "小（簡易）", "中（通常）", "大（本格）"])
use_cg = st.checkbox("CG・VFXあり")
use_narration = st.checkbox("ナレーション収録あり")
use_music = st.selectbox("音楽素材", ["既存ライセンス", "オリジナル制作", "未定"])
ma_needed = st.checkbox("MAあり")
deliverables = st.multiselect("納品形式", ["mp4（16:9）", "mp4（1:1）", "mp4（9:16）", "ProRes"])
subtitle_langs = st.multiselect("字幕言語", ["日本語", "英語", "その他"])
usage_region = st.selectbox("使用地域", ["日本国内", "グローバル", "未定"])
usage_period = st.selectbox("使用期間", ["3ヶ月", "6ヶ月", "1年", "2年", "無期限", "未定"])
budget_hint = st.text_input("参考予算（税抜・任意）")

extra_notes = st.text_area("備考（案件概要・要件など自由記入）")
do_normalize = st.checkbox("LLMで正規化パスをかける（推奨）", value=True)
do_infer_from_notes = st.checkbox("備考から不足項目を補完（推奨）", value=True)

# === ユーティリティ ===
def join_or(value_list, empty="なし", sep=", "):
    if not value_list:
        return empty
    return sep.join(map(str, value_list))

def rush_coeff(base_days: int, target_days: int) -> float:
    if target_days >= base_days or base_days <= 0:
        return 1.0
    r = (base_days - target_days) / base_days
    return round(1 + RUSH_K * r, 2)

def parse_budget_hint_jpy(s: str) -> Optional[int]:
    if not s:
        return None
    t = str(s).strip().replace(",", "").replace(" ", "").replace("円", "")
    try:
        if "億" in t:
            n = float(t.replace("億", "") or "0"); return int(n * 100_000_000)
        if "万" in t:
            n = float(t.replace("万円", "").replace("万", "") or "0"); return int(n * 10_000)
        return int(float(t))
    except Exception:
        return None

# ---- JSON ロバストパース ----
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
        obj = {"items": []}
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

# ---- プロンプト ----
STRICT_JSON_HEADER = (
    "必ずコードフェンス無しの JSON 1オブジェクトのみを返してください。"
    "説明文は不要です。生成に失敗する場合は {\"items\": []} を返してください。"
)

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
- CG: {"あり" if use_cg else "なし"} / ナレ: {"あり" if use_narration else "なし"} / 音楽: {use_music} / MA: {"あり" if ma_needed else "なし"}
- 納品形式: {join_or(deliverables, empty="未定")}
- 字幕: {join_or(subtitle_langs, empty="なし")}
- 使用地域: {usage_region} / 使用期間: {usage_period}
- 参考予算（税抜）: {budget_hint if budget_hint else "未設定"}
- 備考: {extra_notes if extra_notes else "特になし"}"""

def _inference_block() -> str:
    if not do_infer_from_notes:
        return ""
    return "\n- 備考や一般的な慣行から未指定項目を推論・補完してください。\n"

def build_prompt_json() -> str:
    # なるべく短く・無害表現に寄せる
    return f"""{STRICT_JSON_HEADER}

あなたは広告映像制作の見積り項目を作成するアシスタントです。
以下の仕様で **JSONオブジェクトのみ** を返してください。

{_common_case_block()}

【出力仕様】
- ルート: items（配列）
- 要素キー: category / task / qty / unit / unit_price / note
- category: 「制作人件費」「企画」「撮影費」「出演関連費」「編集費・MA費」「諸経費」「管理費」
{_inference_block()}
- qty/unit は日・式・人・時間など妥当な単位
- 単価は一般的な相場レンジで推定
- 管理費は固定1行（task=管理費（固定）, qty=1, unit=式）
"""

# === Gemini 呼び出し（JSONモード + SAFETY BLOCK_NONE + 堅牢抽出） ===
def _gemini25_model():
    # Safety を BLOCK_NONE に明示（4カテゴリ）
    try:
        from google.generativeai.types import HarmCategory, HarmBlockThreshold
        safety_settings = [
            {"category": HarmCategory.HARM_CATEGORY_HARASSMENT,         "threshold": HarmBlockThreshold.BLOCK_NONE},
            {"category": HarmCategory.HARM_CATEGORY_HATE_SPEECH,        "threshold": HarmBlockThreshold.BLOCK_NONE},
            {"category": HarmCategory.HARM_CATEGORY_SEXUAL,             "threshold": HarmBlockThreshold.BLOCK_NONE},
            {"category": HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,  "threshold": HarmBlockThreshold.BLOCK_NONE},
        ]
    except Exception:
        # 型が取れない環境でも文字列指定で動作するSDKが多い
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT",        "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH",       "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUAL",            "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]

    return genai.GenerativeModel(
        GEMINI_MODEL_ID,
        # JSON モードで “必ず JSON を返す” を強制
        generation_config={
            "candidate_count": 1,
            "temperature": 0.3,
            "top_p": 0.9,
            "max_output_tokens": 2500,
            "response_mime_type": "application/json",
        },
        # ここでブロックしない
        safety_settings=safety_settings,
        # 追加のシステム指示（安全系の誤検知を避けつつ JSON を強制）
        system_instruction=(
            "You are a helpful estimator for video production. "
            "Always return a single valid JSON object only, with no preface nor code fences. "
            "Avoid including any personal data. Keep content neutral and professional."
        ),
    )

def _robust_extract_gemini_text(resp) -> str:
    try:
        if getattr(resp, "text", None):
            return resp.text
    except Exception:
        pass
    try:
        cands = getattr(resp, "candidates", None) or []
        buf = []
        for c in cands:
            content = getattr(c, "content", None)
            if not content: continue
            parts = getattr(content, "parts", None) or []
            for p in parts:
                t = getattr(p, "text", None)
                if t: buf.append(t)
        if buf: return "".join(buf)
    except Exception:
        pass
    try:
        d = resp.to_dict()
        import json as _json
        return _json.dumps(d, ensure_ascii=False)
    except Exception:
        return ""

def _finish_reason_name(resp_dict: dict) -> str:
    try:
        fr = (resp_dict.get("candidates") or [{}])[0].get("finish_reason", 0)
        return FINISH_REASON_MAP.get(fr, str(fr))
    except Exception:
        return "UNKNOWN"

def llm_generate_items_json(prompt: str) -> str:
    try:
        m = _gemini25_model()

        # 1) 通常プロンプト
        r1 = m.generate_content(prompt)
        d1 = r1.to_dict()
        st.session_state["gemini_raw_dict"] = d1
        st.session_state["gemini_finish_reason"] = _finish_reason_name(d1)
        raw = _robust_extract_gemini_text(r1)

        # 2) 空なら短縮版プロンプトで再試行
        if not raw or not raw.strip():
            short_prompt = (
                'JSONのみ。items 配列に {category, task, qty, unit, unit_price, note}。'
                '管理費は固定1行（task=管理費（固定）, qty=1, unit=式）。説明文は禁止。'
            )
            r2 = m.generate_content(short_prompt)
            d2 = r2.to_dict()
            st.session_state["gemini_raw_dict"] = {"first": d1, "retry_short": d2}
            st.session_state["gemini_finish_reason"] = _finish_reason_name(d2)
            raw = _robust_extract_gemini_text(r2)

        # 3) まだ空なら最小JSONで再試行（≒生成を強制）
        if not raw or not raw.strip():
            minimal = '{"items":[{"category":"管理費","task":"管理費（固定）","qty":1,"unit":"式","unit_price":0,"note":""}]}'
            r3 = m.generate_content(minimal)
            d3 = r3.to_dict()
            st.session_state["gemini_raw_dict"] = {"prev": st.session_state["gemini_raw_dict"], "final_minimal": d3}
            st.session_state["gemini_finish_reason"] = _finish_reason_name(d3)
            raw = _robust_extract_gemini_text(r3)

        if not raw or not raw.strip():
            raw = '{"items": []}'

        st.session_state["items_json_raw"] = raw
        st.session_state["model_used"] = GEMINI_MODEL_ID
        return robust_parse_items_json(raw)
    except Exception as e:
        st.warning(f"⚠️ Gemini 呼び出し失敗: {type(e).__name__}: {str(e)[:200]}")
        st.session_state["items_json_raw"] = '{"items": []}'
        st.session_state["gemini_finish_reason"] = "EXCEPTION"
        return '{"items": []}'

def llm_normalize_items_json(items_json: str) -> str:
    try:
        prompt = f"""{STRICT_JSON_HEADER}
次のJSONを検査・正規化してください。返答は**修正済みJSONのみ**です。
- スキーマ外キー削除、欠損補完（qty/unit/unit_price/note）
- category 正規化（制作人件費/企画/撮影費/出演関連費/編集費・MA費/諸経費/管理費）
- 単位表記のゆれを正規化
- 管理費は固定1行（task=管理費（固定）, qty=1, unit=式）
【入力JSON】
{items_json}
"""
        m = _gemini25_model()
        r = m.generate_content(prompt)
        raw = _robust_extract_gemini_text(r)
        if not raw or not raw.strip():
            return items_json
        return robust_parse_items_json(raw)
    except Exception:
        return items_json

# === 計算・表示系（段階2bと同じ） ===
def df_from_items_json(items_json: str) -> pd.DataFrame:
    try:
        data = json.loads(items_json) if items_json else {}
    except Exception:
        data = {}
    items = data.get("items", []) or []
    norm = []
    for x in items:
        norm.append({
            "category": str((x or {}).get("category", "")),
            "task": str((x or {}).get("task", "")),
            "qty": (x or {}).get("qty", 0),
            "unit": str((x or {}).get("unit", "")),
            "unit_price": (x or {}).get("unit_price", 0),
            "note": str((x or {}).get("note", "")),
        })
    df = pd.DataFrame(norm)
    for col in ["category", "task", "qty", "unit", "unit_price", "note"]:
        if col not in df.columns:
            df[col] = "" if col in ["category", "task", "unit", "note"] else 0
    df["qty"] = pd.to_numeric(df["qty"], errors="coerce").fillna(0.0)
    df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce").fillna(0).astype(int)
    return df

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

def scale_prices_to_budget(df_items: pd.DataFrame,
                           base_days: int,
                           target_days: int,
                           target_taxable_jpy: int,
                           low: float = 0.6,
                           high: float = 5.0,
                           round_to: int = 1000) -> pd.DataFrame:
    df_now, meta_now = compute_totals(df_items, base_days, target_days)
    nonmgmt_after_rush = float(meta_now["subtotal_after_rush_excl_mgmt"])
    if nonmgmt_after_rush <= 0:
        return df_items.copy()
    desired = target_taxable_jpy / (1.0 + MGMT_FEE_CAP_RATE)
    s = max(low, min(high, desired / nonmgmt_after_rush))
    df_scaled = df_items.copy()
    is_mgmt = (df_scaled["category"] == "管理費")
    df_scaled.loc[~is_mgmt, "unit_price"] = (
        df_scaled.loc[~is_mgmt, "unit_price"].astype(float) * s
    ).round().astype(int)
    if round_to and round_to > 1:
        def _r(x): return int(round(x / round_to) * round_to)
        df_scaled.loc[~is_mgmt, "unit_price"] = df_scaled.loc[~is_mgmt, "unit_price"].map(_r)
    return df_scaled

def render_html(df_items: pd.DataFrame, meta: dict) -> str:
    def td_r(x): return f"<td style='text-align:right'>{x}</td>"
    html = []
    html.append("<p>以下はカテゴリ別に整理した概算見積です。</p>")
    html.append(f"<p>短納期係数：{meta['rush_coeff']} ／ 管理費上限：{int(MGMT_FEE_CAP_RATE*100)}% ／ 消費税率：{int(TAX_RATE*100)}%</p>")
    html.append("<table border='1' cellspacing='0' cellpadding='6' style='border-collapse:collapse;width:100%'>")
    html.append("<thead><tr>"
                "<th>カテゴリ</th><th>項目</th>"
                "<th style='text-align:right'>単価</th><th>数量</th><th>単位</th>"
                "<th style='text-align:right'>金額（円）</th></tr></thead><tbody>")
    current_cat = None
    for _, r in df_items.iterrows():
        cat = r.get("category","")
        if cat != current_cat:
            html.append(f"<tr><td colspan='6' style='background:#f6f6f6;font-weight:bold'>{cat}</td></tr>")
            current_cat = cat
        html.append(
            "<tr>"
            f"<td>{cat}</td>"
            f"<td>{r.get('task','')}</td>"
            f"{td_r(f'{int(r.get('unit_price',0)):,}')}"
            f"<td>{r.get('qty','')}</td>"
            f"<td>{r.get('unit','')}</td>"
            f"{td_r(f'{int(r.get('小計',0)):,}')}"
            "</tr>"
        )
    html.append("</tbody></table>")
    html.append(
        f"<p><b>小計（税抜）</b>：{meta['taxable']:,}円 ／ "
        f"<b>消費税</b>：{meta['tax']:,}円 ／ "
        f"<b>合計</b>：<span style='color:#d00'>{meta['total']:,}円</span></p>"
    )
    return "\n".join(html)

def download_excel(df_items: pd.DataFrame, meta: dict):
    out = df_items[["category","task","unit_price","qty","unit","小計"]].copy()
    out.columns = ["カテゴリ","項目","単価（円）","数量","単位","金額（円）"]
    buf = BytesIO()
    try:
        import xlsxwriter  # noqa: F401
        engine = "xlsxwriter"
    except ModuleNotFoundError:
        engine = "openpyxl"
    with pd.ExcelWriter(buf, engine=engine) as writer:
        out.to_excel(writer, index=False, sheet_name="見積もり")
    buf.seek(0)
    st.download_button("📥 Excelでダウンロード", buf, "見積もり.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# === 実行 ===
if st.button("💡 見積もりを作成"):
    with st.spinner("Gemini 2.5 Flash が見積もり項目を作成中…"):
        prompt = build_prompt_json()
        items_json = llm_generate_items_json(prompt)
        if do_normalize:
            items_json = llm_normalize_items_json(items_json)

        try:
            df_items = df_from_items_json(items_json)
        except Exception:
            st.error("JSON解析に失敗しました。RAW出力を確認してください。")
            with st.expander("RAW出力"):
                st.code(st.session_state.get("items_json_raw", "(no raw)"))
            st.stop()

        base_days = int(shoot_days + edit_days + 5)
        target_days = (delivery_date - date.today()).days

        budget_total = parse_budget_hint_jpy(budget_hint)
        if budget_total:
            df_items = scale_prices_to_budget(df_items, base_days, target_days, budget_total)

        df_calc, meta = compute_totals(df_items, base_days, target_days)
        final_html = render_html(df_calc, meta)

        st.session_state["items_json"] = items_json
        st.session_state["df"] = df_calc
        st.session_state["meta"] = meta
        st.session_state["final_html"] = final_html

# === 表示/デバッグ ===
if st.session_state["final_html"]:
    st.info({
        "model_used": st.session_state.get("model_used") or "(n/a)",
        "normalize_pass": do_normalize,
        "finish_reason": st.session_state.get("gemini_finish_reason")
    })
    st.success("✅ 見積もり結果（計算済み）")
    st.components.v1.html(st.session_state["final_html"], height=900, scrolling=True)
    download_excel(st.session_state["df"], st.session_state["meta"])

    with st.expander("デバッグ：Gemini RAW to_dict()", expanded=False):
        import json as _json
        raw = st.session_state.get("gemini_raw_dict", None)
        st.code(_json.dumps(raw if raw else {"note":"未実行"}, ensure_ascii=False, indent=2), language="json")

    with st.expander("デバッグ：モデル生出力（RAWテキストプレビュー）", expanded=False):
        st.code(st.session_state.get("items_json_raw", "(no raw)"))
