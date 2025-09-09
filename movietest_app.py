# movie_app_stage_a_flex.py
# Stage A（柔軟版・note保持）: フィルタ除去なし。UIで「映像のみ」ガードを切替可能。
# 生成結果は note 列を保持し、Excel ダウンロードにも含めます。

import os
import re
import json
from io import BytesIO
from datetime import date

import streamlit as st
import pandas as pd
import google.generativeai as genai

st.set_page_config(page_title="概算見積（柔軟版：Gemini 2.5 Flash）", layout="centered")

# ====== Secrets / Gemini ======
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=GEMINI_API_KEY)

# ====== Utils ======
def _strip_code_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()

def robust_items_parse(raw: str) -> dict:
    """LLM 出力から {items:[...]} を最大限ロバストに復元"""
    if not raw:
        return {"items": []}
    t = _strip_code_fences(raw)
    # 1) そのまま JSON
    try:
        obj = json.loads(t)
        if isinstance(obj, dict) and isinstance(obj.get("items"), list):
            return obj
    except Exception:
        pass
    # 2) JSON 断片の切り出し
    try:
        first = t.find("{"); last = t.rfind("}")
        if 0 <= first < last:
            frag = t[first:last+1]
            frag = re.sub(r",\s*([}\]])", r"\1", frag)              # 末尾カンマ除去
            frag2 = frag.replace("\r", "")
            frag2 = re.sub(r"\bTrue\b", "true", frag2)
            frag2 = re.sub(r"\bFalse\b", "false", frag2)
            frag2 = re.sub(r"\bNone\b", "null", frag2)
            if "'" in frag2 and '"' not in frag2:
                frag2 = frag2.replace("'", '"')
            obj = json.loads(frag2)
            if isinstance(obj, dict) and isinstance(obj.get("items"), list):
                return obj
    except Exception:
        pass
    return {"items": []}

def df_from_items(obj: dict) -> pd.DataFrame:
    items = obj.get("items", []) if isinstance(obj, dict) else []
    rows = []
    for x in items:
        if not isinstance(x, dict):
            continue
        rows.append({
            "category": str(x.get("category", "")),
            "task": str(x.get("task", "")),
            "qty": pd.to_numeric(x.get("qty", 0), errors="coerce"),
            "unit": str(x.get("unit", "")),
            "unit_price": pd.to_numeric(x.get("unit_price", 0), errors="coerce"),
            "note": str(x.get("note", "")),
        })
    if not rows:
        return pd.DataFrame(columns=["category","task","qty","unit","unit_price","note","amount"])
    df = pd.DataFrame(rows)
    df["qty"] = df["qty"].fillna(0).astype(float)
    df["unit_price"] = df["unit_price"].fillna(0).astype(float)
    # 単価の下駄（1,000円未満を 1,000 に）
    df.loc[df["unit_price"] < 1000, "unit_price"] = 1000
    df["amount"] = (df["qty"] * df["unit_price"]).round().astype(int)
    return df

def totals(df: pd.DataFrame, tax_rate=0.10):
    taxable = int(df["amount"].sum()) if len(df) else 0
    tax = int(round(taxable * tax_rate))
    total = taxable + tax
    return {"taxable": taxable, "tax": tax, "total": total}

def download_excel(df: pd.DataFrame, meta: dict, filename="見積り.xlsx"):
    """note を含む Excel を配布"""
    out = df.copy()
    out = out[["category","task","qty","unit","unit_price","note","amount"]]
    out.columns = ["カテゴリ","項目","数量","単位","単価（円）","内訳・注記","金額（円）"]

    buf = BytesIO()
    try:
        import xlsxwriter  # noqa: F401
        engine = "xlsxwriter"
    except ModuleNotFoundError:
        engine = "openpyxl"

    with pd.ExcelWriter(buf, engine=engine) as writer:
        out.to_excel(writer, index=False, sheet_name="見積り")
        # 軽い整形
        if engine == "xlsxwriter":
            wb = writer.book
            ws = writer.sheets["見積り"]
            fmt_int = wb.add_format({"num_format": "#,##0"})
            ws.set_column("A:A", 14)  # カテゴリ
            ws.set_column("B:B", 26)  # 項目
            ws.set_column("C:C", 8)   # 数量
            ws.set_column("D:D", 8)   # 単位
            ws.set_column("E:E", 12, fmt_int)  # 単価
            ws.set_column("F:F", 36)  # 内訳・注記
            ws.set_column("G:G", 12, fmt_int)  # 金額
            last = len(out) + 2
            ws.write(last,   5, "小計（税抜）")
            ws.write_number(last,   6, int(meta["taxable"]), fmt_int)
            ws.write(last+1, 5, "消費税")
            ws.write_number(last+1, 6, int(meta["tax"]), fmt_int)
            ws.write(last+2, 5, "合計")
            ws.write_number(last+2, 6, int(meta["total"]), fmt_int)
        else:
            ws = writer.book["見積り"]
            # openpyxl 側は最小限（列幅）
            widths = {"A":14,"B":26,"C":8,"D":8,"E":12,"F":36,"G":12}
            for col, w in widths.items():
                ws.column_dimensions[col].width = w

    buf.seek(0)
    st.download_button("📥 Excelダウンロード（note入り）", buf, file_name=filename,
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ====== Prompts ======
_MINI_SYSTEM = (
    "あなたは見積り項目を JSON で返すアシスタントです。"
    "出力は JSON オブジェクト1個のみ（文章やコードフェンスは禁止）。"
)

_JSON_SPEC = (
    "【出力仕様】\n"
    "- ルートは {\"items\":[...]} のみ\n"
    "- 各要素キー: category, task, qty, unit, unit_price, note\n"
    "- note には、その項目の内訳/前提/条件などを短く記す（必須。空文字は不可）\n"
    "- 最低4項目以上\n"
    "- 単価は概算でよいが 1,000 円未満は 1,000 に切り上げ\n"
    "- 合計や消費税などの集計は出力しない\n"
)

_DOMAIN_GUARD_VIDEO_ONLY = (
    "【ドメイン制約（映像のみ）】\n"
    "・対象は映像制作（企画/撮影/出演/編集/MA/音楽/美術・ロケ/機材/諸経費/管理費 等）に限定。\n"
    "・印刷/配布/媒体費/Web制作/広告出稿など映像外の項目は出力しない。\n"
)

_EXAMPLE = {
  "items": [
    {"category":"制作費","task":"企画構成費","qty":1,"unit":"式","unit_price":50000,"note":"構成・絵コンテ・スケジュール調整"},
    {"category":"撮影費","task":"カメラマン費","qty":2,"unit":"日","unit_price":80000,"note":"本番/予備日、機材基本含む"},
    {"category":"編集費・MA費","task":"編集","qty":3,"unit":"日","unit_price":70000,"note":"オフライン～オンラインまで"},
    {"category":"管理費","task":"管理費（固定）","qty":1,"unit":"式","unit_price":50000,"note":"進行/安全管理/制作管理"}
  ]
}

def build_case_block(
    final_duration: str,
    num_versions: int,
    shoot_days: int,
    edit_days: int,
    notes: str
) -> str:
    return (
        "【案件条件】\n"
        f"- 尺: {final_duration}\n"
        f"- 納品本数: {num_versions}本\n"
        f"- 撮影日数: {shoot_days}日 / 編集日数: {edit_days}日\n"
        f"- 備考: {notes if notes else '特になし'}\n"
    )

def _run_model(prompt_text: str, response_mime: str | None):
    model = genai.GenerativeModel(
        "gemini-2.5-flash",
        generation_config={
            "temperature": 0.2,
            "top_p": 0.9,
            "candidate_count": 1,
            "max_output_tokens": 2048,
            **({"response_mime_type": response_mime} if response_mime else {}),
        },
    )
    resp = model.generate_content(prompt_text)
    return (resp.text or "").strip()

def call_g25_items_json(prompt_block: str, video_only: bool) -> dict:
    guard = _DOMAIN_GUARD_VIDEO_ONLY if video_only else ""
    base_prompt = (
        f"{_MINI_SYSTEM}\n\n{guard}\n{prompt_block}\n\n{_JSON_SPEC}\n"
        "【出力例（数値は状況に応じて推定し直してください）】\n"
        "```json\n" + json.dumps(_EXAMPLE, ensure_ascii=False, indent=2) + "\n```\n"
    )
    for mime in ["application/json", None, "text/plain"]:
        try:
            raw = _run_model(base_prompt, mime)
            obj = robust_items_parse(raw)
            if isinstance(obj.get("items"), list) and len(obj["items"]) >= 4:
                # noteが空の要素を簡易補完（モデルのブレ対策）
                for e in obj["items"]:
                    if isinstance(e, dict) and not str(e.get("note","")).strip():
                        e["note"] = "内訳/前提: 追って確定"
                return obj
        except Exception:
            pass

    minimal = (
        ("映像制作のみ。出力は JSON オブジェクト1個（文章禁止）。"
         "items: category, task, qty, unit, unit_price, note（note必須・短い内訳）。最低4項目。")
        if video_only else
        ("備考優先（映像以外も可）。出力は JSON オブジェクト1個（文章禁止）。"
         "items: category, task, qty, unit, unit_price, note（note必須・短い内訳）。最低4項目。")
    )
    try:
        raw2 = _run_model(minimal, "application/json")
        obj2 = robust_items_parse(raw2)
        if isinstance(obj2.get("items"), list) and len(obj2["items"]) >= 4:
            for e in obj2["items"]:
                if isinstance(e, dict) and not str(e.get("note","")).strip():
                    e["note"] = "内訳/前提: 追って確定"
            return obj2
    except Exception:
        pass
    return {"items": []}

# ====== UI ======
st.title("概算見積（柔軟版：Gemini 2.5 Flash）")

st.subheader("入力（コンパクト版）")
col1, col2 = st.columns(2)
with col1:
    final_duration = st.selectbox("尺の長さ", ["15秒", "30秒", "60秒", "その他"], index=1)
    if final_duration == "その他":
        final_duration = st.text_input("尺（自由記入）", value="45秒")
    num_versions = st.number_input("納品本数", min_value=1, max_value=10, value=1)
with col2:
    shoot_days = st.number_input("撮影日数", min_value=1, max_value=10, value=2)
    edit_days = st.number_input("編集日数", min_value=1, max_value=10, value=3)

notes = st.text_area(
    "備考（自由記入）",
    placeholder="例：映像/チラシ/Webなど自由に。具体条件を書けばそのドメインで出力します。"
)

video_only = st.checkbox("映像ドメインに限定（印刷/媒体/Web を含めない）", value=False)

st.markdown("---")
if st.button("▶ 見積アイテムを生成（Gemini 2.5 Flash）", type="primary"):
    with st.spinner("生成中..."):
        block = build_case_block(
            final_duration=str(final_duration),
            num_versions=int(num_versions),
            shoot_days=int(shoot_days),
            edit_days=int(edit_days),
            notes=notes,
        )
        items_obj = call_g25_items_json(block, video_only=video_only)
        df = df_from_items(items_obj)
        meta = totals(df, tax_rate=0.10)

    st.success(f"モデル: gemini-2.5-flash / 行数: {len(df)} / 映像限定: {video_only}")
    if len(df):
        st.dataframe(df[["category","task","qty","unit","unit_price","note","amount"]], use_container_width=True)
    else:
        msg = "items が空でした。備考をもう少し具体化して再実行してください。"
        if video_only:
            msg += "（※ 映像以外の要素は意図的に抑制しています）"
        st.info(msg)

    st.markdown(
        f"**小計（税抜）** : {meta['taxable']:,} 円　/　"
        f"**消費税** : {meta['tax']:,} 円　/　"
        f"**合計** : **{meta['total']:,} 円**"
    )

    if len(df):
        download_excel(df, meta, filename="見積り_note入り.xlsx")

    with st.expander("デバッグ：生成 JSON（RAW→整形後）", expanded=False):
        st.code(json.dumps(items_obj, ensure_ascii=False, indent=2), language="json")

else:
    st.caption("※ フィルタ除去は行いません。必要に応じて『映像ドメインに限定』チェックでガードをかけられます。")
