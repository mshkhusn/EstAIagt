# movie_app.py — 生成=gemini-2.0-flash / 正規化=gemini-2.5-flash（2.5失敗時は2.0へ自動切替）
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

# ===== ページ / Secrets =====
st.set_page_config(page_title="映像制作概算見積（2.0生成→2.5正規化）", layout="centered")
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
APP_PASSWORD   = st.secrets.get("APP_PASSWORD", "")

if not GEMINI_API_KEY:
    st.error("GEMINI_API_KEY が未設定です。Secrets を確認してください。")
    st.stop()

genai.configure(api_key=GEMINI_API_KEY)

# モデルID
MODEL_GEN = "gemini-2.0-flash"   # 生成用（安定）
MODEL_NORM_PRIMARY = "gemini-2.5-flash"  # 正規化の第一候補
MODEL_NORM_FALLBACK = "gemini-2.0-flash" # 2.5が無音時のフォールバック

# 係数
TAX_RATE = 0.10
MGMT_FEE_CAP_RATE = 0.15
RUSH_K = 0.75

# ===== セッション =====
for k in ["items_json_raw", "items_json", "df", "meta", "final_html",
          "gen_model_used", "norm_model_used",
          "gen_raw_dict", "norm_raw_dict",
          "gen_finish_reason", "norm_finish_reason"]:
    if k not in st.session_state:
        st.session_state[k] = None

# ===== 認証 =====
st.title("映像制作概算見積（2.0生成→2.5正規化）")
if APP_PASSWORD:
    pw = st.text_input("パスワード", type="password")
    if pw != APP_PASSWORD:
        st.warning("🔒 認証が必要です")
        st.stop()

# ===== 入力UI =====
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

# ===== ユーティリティ =====
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

# ===== Gemini 呼び出し（2.0 生成 / 2.5 正規化） =====
def _gemini_model(model_id: str, json_mode: bool = True):
    cfg = {
        "candidate_count": 1,
        "temperature": 0.3,
        "top_p": 0.9,
        "max_output_tokens": 2500,
    }
    if json_mode:
        cfg["response_mime_type"] = "application/json"
    return genai.GenerativeModel(model_id, generation_config=cfg)

def _robust_extract(resp) -> str:
    try:
        if getattr(resp, "text", None):
            return resp.text
    except Exception:
        pass
    try:
        cands = getattr(resp, "candidates", None) or []
        buf = []
        for c in cands:
            parts = getattr(getattr(c, "content", None), "parts", None) or []
            for p in parts:
                t = getattr(p, "text", None)
                if t: buf.append(t)
        if buf: return "".join(buf)
    except Exception:
        pass
    try:
        return json.dumps(resp.to_dict(), ensure_ascii=False)
    except Exception:
        return ""

def _finish_reason_name(d: dict) -> str:
    try:
        fr = (d.get("candidates") or [{}])[0].get("finish_reason", 0)
        return {0:"UNSPEC",1:"STOP",2:"SAFETY",3:"RECIT",4:"OTHER"}.get(fr, str(fr))
    except Exception:
        return "UNKNOWN"

def generate_items_with_20(prompt: str) -> str:
    m = _gemini_model(MODEL_GEN, json_mode=True)
    r = m.generate_content(prompt)
    d = r.to_dict()
    st.session_state["gen_raw_dict"] = d
    st.session_state["gen_finish_reason"] = _finish_reason_name(d)
    st.session_state["gen_model_used"] = MODEL_GEN
    raw = _robust_extract(r)
    if not raw.strip():
        raw = '{"items":[]}'
    return robust_parse_items_json(raw)

def normalize_with_25(items_json: str) -> str:
    prompt = f"""{STRICT_JSON_HEADER}
次のJSONを検査・正規化してください。返答は**修正済みJSONのみ**です。
- スキーマ外キー削除、欠損補完（qty/unit/unit_price/note）
- category 正規化（制作人件費/企画/撮影費/出演関連費/編集費・MA費/諸経費/管理費）
- 単位のゆれを正規化（例: 日/式/人/時間 等）
- 管理費は固定1行（task=管理費（固定）, qty=1, unit=式）
【入力JSON】
{items_json}
"""
    # まず 2.5 でトライ
    m = _gemini_model(MODEL_NORM_PRIMARY, json_mode=True)
    r = m.generate_content(prompt)
    d = r.to_dict()
    st.session_state["norm_raw_dict"] = d
    st.session_state["norm_finish_reason"] = _finish_reason_name(d)
    st.session_state["norm_model_used"] = MODEL_NORM_PRIMARY
    raw = _robust_extract(r)

    # 2.5 が無音/空返しなら 2.0 へフォールバック（※生成は2.0で済んでいるので“正規化のみ”の切替）
    if not raw.strip():
        m2 = _gemini_model(MODEL_NORM_FALLBACK, json_mode=True)
        r2 = m2.generate_content(prompt)
        d2 = r2.to_dict()
        st.session_state["norm_raw_dict"] = {"primary": d, "fallback": d2}
        st.session_state["norm_finish_reason"] = _finish_reason_name(d2) + " (fallback)"
        st.session_state["norm_model_used"] = MODEL_NORM_FALLBACK
        raw = _robust_extract(r2)

    if not raw.strip():
        return items_json  # 最後の砦：元のJSONを返す
    return robust_parse_items_json(raw)

# ===== 計算・表示 =====
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

# ===== 実行 =====
if st.button("💡 見積もりを作成"):
    with st.spinner("Gemini が見積もり項目を作成中…"):
        prompt = build_prompt_json()

        # 1) 2.0 で生成
        items_json = generate_items_with_20(prompt)

        # 2) 2.5 で正規化（失敗時は2.0で正規化）
        if do_normalize:
            items_json = normalize_with_25(items_json)

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
            # 参考予算スケーリング（必要なら戻す）
            pass

        df_calc, meta = compute_totals(df_items, base_days, target_days)
        final_html = render_html(df_calc, meta)

        st.session_state["items_json"] = items_json
        st.session_state["df"] = df_calc
        st.session_state["meta"] = meta
        st.session_state["final_html"] = final_html
        st.session_state["items_json_raw"] = items_json  # プレビュー用

# ===== 表示/デバッグ =====
if st.session_state["final_html"]:
    st.info({
        "gen_model_used": st.session_state.get("gen_model_used"),
        "gen_finish_reason": st.session_state.get("gen_finish_reason"),
        "norm_model_used": st.session_state.get("norm_model_used"),
        "norm_finish_reason": st.session_state.get("norm_finish_reason"),
    })
    st.success("✅ 見積もり結果（計算済み）")
    st.components.v1.html(st.session_state["final_html"], height=900, scrolling=True)

    with st.expander("デバッグ：正規化後 JSON（RAW）"):
        st.code(st.session_state.get("items_json_raw","(no raw)"), language="json")

    with st.expander("デバッグ：生成 RAW to_dict()", expanded=False):
        st.code(json.dumps(st.session_state.get("gen_raw_dict", {}), ensure_ascii=False, indent=2), language="json")

    with st.expander("デバッグ：正規化 RAW to_dict()", expanded=False):
        st.code(json.dumps(st.session_state.get("norm_raw_dict", {}), ensure_ascii=False, indent=2), language="json")
