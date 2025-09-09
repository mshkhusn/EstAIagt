# app.py  — Gemini 2.5 Flash 専用・概算見積（柔軟版） 完全版

import os
import re
import json
import io
from datetime import date
from typing import Optional

import streamlit as st
import pandas as pd
import google.generativeai as genai


# =========================
# ページ設定
# =========================
st.set_page_config(page_title="概算見積（柔軟版：Gemini 2.5 Flash）", layout="wide")

# =========================
# Secrets / Gemini 初期化
# =========================
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
if not GEMINI_API_KEY:
    st.error("GEMINI_API_KEY が未設定です。st.secrets に設定してください。")
    st.stop()

genai.configure(api_key=GEMINI_API_KEY)


# =========================
# 定数
# =========================
TAX_RATE = 0.10
MGMT_FEE_CAP_RATE = 0.15

STRICT_JSON_HEADER = "絶対に説明文や前置きは出力しないでください。JSONオブジェクトのみを1個、コードフェンスなしで返してください。"


# =========================
# セッション
# =========================
for k in [
    "items_json_raw", "gen_finish_reason", "model_used",
    "df", "meta", "used_fallback", "fallback_reason",
    "gemini_raw_dict",
]:
    if k not in st.session_state:
        st.session_state[k] = None


# =========================
# ユーティリティ
# =========================
def join_or(value_list, empty="なし", sep=", "):
    if not value_list:
        return empty
    return sep.join(map(str, value_list))


# ---------- JSON ロバストパース ----------
def _strip_code_fences(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```(json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _remove_trailing_commas(s: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", s)


def _coerce_json_like(s: str):
    if not s:
        return None
    # 素直に JSON
    try:
        return json.loads(s)
    except Exception:
        pass
    # ルートの { ... } を強引に抽出
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
    # Python literal 的なもの
    try:
        import ast
        return ast.literal_eval(s)
    except Exception:
        return None


def robust_parse_items_json(raw: str) -> str:
    """
    モデルの出力から、壊れに強く items JSON を救出する。最低限 { "items": [] } を返す。
    """
    s = _strip_code_fences(raw or "")
    obj = _coerce_json_like(s)
    if not isinstance(obj, dict):
        obj = {}
    items = obj.get("items")
    if not isinstance(items, list):
        # よくある “result/items” や “data” の誤配置を回収
        if isinstance(obj.get("result"), dict) and isinstance(obj["result"].get("items"), list):
            items = obj["result"]["items"]
        elif isinstance(obj.get("data"), list):
            items = obj["data"]
        else:
            items = []
    obj_out = {"items": []}
    # 1レコードごとに安全に整形
    for x in items:
        try:
            obj_out["items"].append({
                "category": str((x or {}).get("category", "")).strip(),
                "task":     str((x or {}).get("task", "")).strip(),
                "qty":      float((x or {}).get("qty", 0) or 0),
                "unit":     str((x or {}).get("unit", "")).strip(),
                "unit_price": int(float((x or {}).get("unit_price", 0) or 0)),
                "note":     str((x or {}).get("note", "")).strip(),
            })
        except Exception:
            continue
    return json.dumps(obj_out, ensure_ascii=False)


# =========================
# プロンプト組み立て
# =========================
def _common_case_block(duration_label: str, deliverables: int, shoot_days: int, edit_days: int, notes: str, restrict_video_domain: bool) -> str:
    domain_line = "映像ドメインに限定（印刷/媒体/Web を含めない）" if restrict_video_domain else "映像ドメインに限定しない（案件内容に応じて自由）"
    return f"""【案件条件】
- 尺の長さ: {duration_label}
- 納品本数: {deliverables}本
- 撮影日数: {shoot_days}日 / 編集日数: {edit_days}日
- ドメイン: {domain_line}
- 備考: {notes if notes else "特になし"}"""


def _inference_block() -> str:
    return """
- 備考や一般的な広告映像制作の慣行から、未指定の付随項目を適切に補完すること。
- ただしユーザーの備考で映像以外の見積りが明確に読み取れる場合は、そのドメインの見積りを作ってよい（フィルタ除去はしない）。
"""


def build_structured_prompt(duration_label, deliverables, shoot_days, edit_days, notes, restrict_video_domain) -> str:
    return f"""{STRICT_JSON_HEADER}
あなたは広告映像の概算見積り項目のエキスパートです。**JSONだけ**を1個返してください。
JSONは次の仕様です:
- ルートに "items": [] を1つだけ持つこと
- 各要素は {{ "category","task","qty","unit","unit_price","note" }} をすべて持つ
- 数量/単価は数値として返す
- 最低3行以上
- 可能なら "note" に簡潔な内訳(役割・範囲)を書く
- 管理費（固定）も1行含める（task=管理費（固定）, qty=1, unit=式）

{_common_case_block(duration_label, deliverables, shoot_days, edit_days, notes, restrict_video_domain)}
{_inference_block()}
"""


def build_minimal_prompt() -> str:
    return f"""{STRICT_JSON_HEADER}
次の仕様でJSON(1オブジェクト)のみを返してください。コードフェンス禁止。
- ルート: items 配列
- 各要素: category, task, qty, unit, unit_price, note
- 最低3行以上、数値は数値で
- 管理費は1行（task=管理費（固定）, qty=1, unit=式）
"""


def build_seed_prompt() -> str:
    seed = {
        "items": [
            {"category":"制作費","task":"企画構成費","qty":1,"unit":"式","unit_price":50000,"note":"構成案・進行"},
            {"category":"撮影費","task":"カメラマン費","qty":2,"unit":"日","unit_price":80000,"note":"撮影一式"},
            {"category":"編集費・MA費","task":"編集","qty":3,"unit":"日","unit_price":70000,"note":"オフライン/オンライン"}
        ]
    }
    return f"""{STRICT_JSON_HEADER}
以下のシードに沿って**映像制作の見積り**として整形し、最低3行以上の items を返してください。
- ルート: items 配列
- 各要素: category, task, qty, unit, unit_price, note
- 管理費（固定）を必ず含める（qty=1, unit=式）
- 返答はJSONのみ、コードフェンス禁止、説明文不要

シード例:
{json.dumps(seed, ensure_ascii=False, indent=2)}
"""


# =========================
# LLM 呼び出し（Gemini 2.5 Flash）
# =========================
def _gemini_call(text_prompt: str):
    model = genai.GenerativeModel(
        "gemini-2.5-flash",
        generation_config={
            "temperature": 0.2,
            "top_p": 0.9,
            "max_output_tokens": 2500,
        },
    )
    resp = model.generate_content(text_prompt)

    # raw dict 保存
    try:
        st.session_state["gemini_raw_dict"] = resp.to_dict()
    except Exception:
        pass

    # text 取得（parts fallback 付き）
    txt = ""
    try:
        if getattr(resp, "text", None):
            txt = resp.text or ""
    except Exception:
        txt = ""

    if not txt:
        try:
            cands = getattr(resp, "candidates", []) or []
            buf = []
            for c in cands:
                parts = getattr(c, "content", None)
                parts = getattr(parts, "parts", None) or []
                for p in parts:
                    t = getattr(p, "text", None)
                    if t:
                        buf.append(t)
            if buf:
                txt = "\n".join(buf)
        except Exception:
            pass

    return txt, getattr(resp, "finish_reason", None)


def llm_generate_items_json(duration_label, deliverables, shoot_days, edit_days, notes, restrict_video_domain) -> str:
    """
    ①構造化プロンプト → ②最小JSON → ③seed付き
    の順に試し、items>=1 を得られた段階で返す。最終的に fallback を返す。
    """
    def _try_and_parse(prompt: str) -> Optional[str]:
        text, finish = _gemini_call(prompt)
        st.session_state["gen_finish_reason"] = finish or "(unknown)"
        raw = (text or "").strip()
        st.session_state["items_json_raw"] = raw
        parsed = robust_parse_items_json(raw) if raw else None
        if not parsed:
            return None
        try:
            if len(json.loads(parsed).get("items") or []) >= 1:
                st.session_state["model_used"] = "gemini-2.5-flash"
                return parsed
        except Exception:
            return None
        return None

    st.session_state["used_fallback"] = False
    st.session_state["fallback_reason"] = None

    # ① 構造化寄り
    p1 = build_structured_prompt(duration_label, deliverables, shoot_days, edit_days, notes, restrict_video_domain)
    r1 = _try_and_parse(p1)
    if r1:
        return r1

    # ② 最小
    st.session_state["used_fallback"] = True
    p2 = build_minimal_prompt()
    r2 = _try_and_parse(p2)
    if r2:
        return r2

    # ③ seed
    p3 = build_seed_prompt()
    r3 = _try_and_parse(p3)
    if r3:
        return r3

    # final fallback
    st.session_state["fallback_reason"] = "Gemini returned empty/invalid JSON in 3 attempts."
    st.warning("⚠️ モデルから有効なJSONが得られなかったため、安全な固定値で継続します。")
    fallback = {
        "items": [
            {"category": "制作費",      "task": "企画構成費", "qty": 1, "unit": "式", "unit_price": 50000, "note": "構成案・進行"},
            {"category": "撮影費",      "task": "カメラマン費", "qty": 2, "unit": "日", "unit_price": 80000, "note": "撮影一式"},
            {"category": "編集費・MA費","task": "編集",      "qty": 3, "unit": "日", "unit_price": 70000, "note": "編集一式"},
            {"category": "管理費",      "task": "管理費（固定）","qty": 1, "unit": "式", "unit_price": 60000, "note": "進行管理"}
        ]
    }
    st.session_state["items_json_raw"] = json.dumps(fallback, ensure_ascii=False)
    st.session_state["model_used"] = "gemini-2.5-flash"
    return json.dumps(fallback, ensure_ascii=False)


# =========================
# 計算系
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
            "category": str((x or {}).get("category", "")),
            "task":     str((x or {}).get("task", "")),
            "qty":      float((x or {}).get("qty", 0) or 0),
            "unit":     str((x or {}).get("unit", "")),
            "unit_price": int(float((x or {}).get("unit_price", 0) or 0)),
            "note":     str((x or {}).get("note", "")),
        })
    df = pd.DataFrame(norm)
    if df.empty:
        df = pd.DataFrame(columns=["category", "task", "qty", "unit", "unit_price", "note"])
    return df


def compute_totals(df_items: pd.DataFrame):
    df = df_items.copy()
    if df.empty:
        meta = {"taxable": 0, "tax": 0, "total": 0}
        return df, meta

    df["amount"] = (df["qty"].astype(float) * df["unit_price"].astype(int)).round().astype(int)

    taxable = int(df["amount"].sum())
    tax = int(round(taxable * TAX_RATE))
    total = taxable + tax
    meta = {"taxable": taxable, "tax": tax, "total": total}
    return df, meta


# =========================
# ダウンロード（note入りExcel）
# =========================
def download_excel(df_calc: pd.DataFrame, meta: dict):
    if df_calc.empty:
        return
    out = df_calc[["category", "task", "qty", "unit", "unit_price", "amount", "note"]].copy()
    out.columns = ["category","task","qty","unit","unit_price","amount","note"]

    buf = io.BytesIO()
    try:
        import xlsxwriter
        engine = "xlsxwriter"
    except Exception:
        from openpyxl import Workbook  # noqa
        engine = "openpyxl"

    with pd.ExcelWriter(buf, engine=engine) as writer:
        out.to_excel(writer, index=False, sheet_name="estimate")
        if engine == "xlsxwriter":
            wb = writer.book
            ws = writer.sheets["estimate"]
            fmt_int = wb.add_format({"num_format": "#,##0"})
            ws.set_column("A:A", 14)
            ws.set_column("B:B", 24)
            ws.set_column("C:C", 8)
            ws.set_column("D:D", 8)
            ws.set_column("E:E", 12, fmt_int)
            ws.set_column("F:F", 12, fmt_int)
            ws.set_column("G:G", 40)
            last = len(out) + 2
            ws.write(last, 4, "小計（税抜）"); ws.write_number(last, 5, int(meta["taxable"]), fmt_int)
            ws.write(last+1, 4, "消費税");     ws.write_number(last+1, 5, int(meta["tax"]), fmt_int)
            ws.write(last+2, 4, "合計");       ws.write_number(last+2, 5, int(meta["total"]), fmt_int)
        else:
            ws = writer.book["estimate"]
            ws.column_dimensions["A"].width = 14
            ws.column_dimensions["B"].width = 24
            ws.column_dimensions["C"].width = 8
            ws.column_dimensions["D"].width = 8
            ws.column_dimensions["E"].width = 12
            ws.column_dimensions["F"].width = 12
            ws.column_dimensions["G"].width = 40
            last = ws.max_row + 2
            ws.cell(row=last,   column=5, value="小計（税抜）")
            ws.cell(row=last,   column=6, value=int(meta["taxable"]))
            ws.cell(row=last+1, column=5, value="消費税")
            ws.cell(row=last+1, column=6, value=int(meta["tax"]))
            ws.cell(row=last+2, column=5, value="合計")
            ws.cell(row=last+2, column=6, value=int(meta["total"]))

    buf.seek(0)
    st.download_button("📥 Excelダウンロード（note入り）", buf, "estimate.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# =========================
# UI
# =========================
st.title("概算見積（柔軟版：Gemini 2.5 Flash）")

colA, colB, colC, colD = st.columns([1.1, 1, 1, 2])

with colA:
    duration_label = st.selectbox("尺の長さ", ["15秒", "30秒", "60秒", "その他"], index=1)
with colB:
    deliverables = st.number_input("納品本数", min_value=1, max_value=20, value=1, step=1)
with colC:
    shoot_days = st.number_input("撮影日数", min_value=0, max_value=20, value=2, step=1)
with colD:
    edit_days = st.number_input("編集日数", min_value=0, max_value=20, value=3, step=1)

notes = st.text_area("備考（自由記入）", placeholder="例：インタビューなし、スタジオ撮影、BGM・ナレーションあり、MAあり、など")
restrict_video_domain = st.checkbox("映像ドメインに限定（印刷/媒体/Web を含めない）", value=False)

st.markdown("---")
btn = st.button("▶️ 見積アイテムを生成（Gemini 2.5 Flash）", type="primary", use_container_width=True)

if btn:
    with st.spinner("Gemini が見積り項目を生成中…"):
        items_json_str = llm_generate_items_json(
            duration_label=duration_label,
            deliverables=int(deliverables),
            shoot_days=int(shoot_days),
            edit_days=int(edit_days),
            notes=notes,
            restrict_video_domain=restrict_video_domain
        )

        df_items = df_from_items_json(items_json_str)
        df_calc, meta = compute_totals(df_items)

        st.session_state["df"] = df_calc
        st.session_state["meta"] = meta

# モデル実行メタ
meta_box = {
    "model_used": st.session_state.get("model_used") or "(n/a)",
    "finish_reason": st.session_state.get("gen_finish_reason") or "(n/a)",
    "used_fallback": bool(st.session_state.get("used_fallback")),
    "fallback_reason": st.session_state.get("fallback_reason"),
}
st.info(meta_box)

# 出力表示
if st.session_state.get("df") is not None:
    df_calc = st.session_state["df"]
    meta = st.session_state["meta"]

    if df_calc.empty:
        st.warning("items が空でした。備考をもう少し具体的にすると安定します。")
    else:
        # 表示テーブル
        st.dataframe(
            df_calc[["category","task","qty","unit","unit_price","note","amount"]],
            use_container_width=True,
            height=min(600, 80 + 33 * max(3, len(df_calc)))
        )

        # 合計
        c1, c2, c3 = st.columns(3)
        c1.metric("小計（税抜）", f"{meta['taxable']:,} 円")
        c2.metric("消費税",     f"{meta['tax']:,} 円")
        c3.metric("合計",       f"{meta['total']:,} 円")

        download_excel(df_calc, meta)

# デバッグ
with st.expander("デバッグ：生成 RAW（JSONテキストとして整形前）", expanded=False):
    st.code(st.session_state.get("items_json_raw") or "(empty)", language="json")

with st.expander("デバッグ：Gemini RAW to_dict()", expanded=False):
    st.code(json.dumps(st.session_state.get("gemini_raw_dict") or {}, ensure_ascii=False, indent=2), language="json")
