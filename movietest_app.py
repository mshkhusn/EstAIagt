# movie_app_stage_a.py
# Stage A: UIフォーム付き・JSON出力ミニ版（Gemini 2.5 Flash 専用 / フォールバックは2.0を使わない）
# - 目的: 元の movie_app に段階的に近づけるための最初の統合版
# - 機能: 入力フォーム -> プロンプト組立 -> 2.5 Flash で items JSON 生成 -> 表 + 合計表示
# - 未実装(次段階で追加): 管理費上限・Rush係数・Excel出力・テンプレ書き出し等

import os
import re
import json
from datetime import date

import streamlit as st
import pandas as pd
import google.generativeai as genai

# ============== ページ設定 ==============
st.set_page_config(page_title="映像制作見積（段階統合 Stage A）", layout="centered")

# ============== Secrets / API Key ==============
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=GEMINI_API_KEY)

# ============== ユーティリティ ==============
def _strip_code_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()

def robust_items_parse(raw: str) -> dict:
    """
    可能な限り { "items": [...] } に整形して返す（dict）
    """
    if not raw:
        return {"items": []}
    t = _strip_code_fences(raw)

    # 素直に JSON
    try:
        obj = json.loads(t)
        if isinstance(obj, dict) and isinstance(obj.get("items"), list):
            return obj
    except Exception:
        pass

    # { ... } 抽出して軽微な修正
    try:
        first = t.find("{"); last = t.rfind("}")
        if 0 <= first < last:
            frag = t[first:last+1]
            frag = re.sub(r",\s*([}\]])", r"\1", frag)  # 末尾カンマ修正
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
        return pd.DataFrame(columns=["category","task","qty","unit","unit_price","amount"])
    df = pd.DataFrame(rows)
    df["qty"] = df["qty"].fillna(0).astype(float)
    df["unit_price"] = df["unit_price"].fillna(0).astype(float)

    # 単価の最低下駄（安全寄り）
    df.loc[df["unit_price"] < 1000, "unit_price"] = 1000
    df["amount"] = (df["qty"] * df["unit_price"]).round().astype(int)
    return df

def totals(df: pd.DataFrame, tax_rate=0.10):
    taxable = int(df["amount"].sum()) if len(df) else 0
    tax = int(round(taxable * tax_rate))
    total = taxable + tax
    return {"taxable": taxable, "tax": tax, "total": total}

# ============== プロンプト組立 ==============
def build_case_block(
    final_duration: str,
    num_versions: int,
    shoot_days: int,
    edit_days: int,
    cast_main: int,
    ma_needed: bool,
    notes: str
) -> str:
    return (
        "【案件条件】\n"
        f"- 尺: {final_duration}\n"
        f"- 納品本数: {num_versions}本\n"
        f"- 撮影日数: {shoot_days}日 / 編集日数: {edit_days}日\n"
        f"- キャスト（メイン）: {cast_main}人\n"
        f"- MA: {'あり' if ma_needed else 'なし'}\n"
        f"- 備考: {notes if notes else '特になし'}\n"
    )

# 2.5 Flash に JSON を出させるための“段階的 MIME 設定”ラダー
# （2.0へは落とさない／同一モデル内で形式だけ緩める）
_MINI_SYSTEM = (
    "あなたは広告映像の見積り項目テンプレートを作るアシスタントです。"
    "出力は安全かつビジネス用途に限定してください。"
)
_JSON_SPEC = (
    "次の仕様で **JSON オブジェクト1個** を返してください。\n"
    "- ルートは {\"items\": [...]} のみ\n"
    "- 各要素: category, task, qty, unit, unit_price, note\n"
    "- 価格は概算で構いませんが 1,000 円未満は 1,000 に揃えてください\n"
    "- 合計や税は出力に含めない\n"
)

def call_g25_items_json(prompt_block: str) -> dict:
    # STEP 1: structured + permissive
    for mode in [
        {"mime": "application/json"},
        {"mime": None},           # structured（MIME 指定なし）
        {"mime": "text/plain"},   # plain
    ]:
        model = genai.GenerativeModel(
            "gemini-2.5-flash",
            generation_config={
                "temperature": 0.2,
                "top_p": 0.9,
                "candidate_count": 1,
                "max_output_tokens": 2048,
                **({"response_mime_type": mode["mime"]} if mode["mime"] else {}),
            },
        )

        full_prompt = (
            f"{_MINI_SYSTEM}\n\n"
            f"{prompt_block}\n\n"
            "【出力仕様】\n"
            f"{_JSON_SPEC}\n"
            "JSON 以外の文章は出力しないでください。"
        )
        try:
            resp = model.generate_content(full_prompt)
            raw = (resp.text or "").strip()
            obj = robust_items_parse(raw)
            # items が入っていれば採用
            if isinstance(obj, dict) and isinstance(obj.get("items"), list) and len(obj["items"]) > 0:
                return obj
        except Exception:
            pass

    # すべて空/失敗 -> 空 items を返す
    return {"items": []}

# ============== UI ==============
st.title("映像制作見積（段階統合 Stage A / Gemini 2.5 Flash 専用）")

st.subheader("制作条件（縮小版）")
col1, col2 = st.columns(2)
with col1:
    final_duration = st.selectbox("尺の長さ", ["15秒", "30秒", "60秒", "その他"], index=1)
    if final_duration == "その他":
        final_duration = st.text_input("尺（自由記入）", value="45秒")
    num_versions = st.number_input("納品本数", min_value=1, max_value=10, value=1)
    cast_main = st.number_input("メインキャスト人数", min_value=0, max_value=10, value=1)

with col2:
    shoot_days = st.number_input("撮影日数", min_value=1, max_value=10, value=2)
    edit_days = st.number_input("編集日数", min_value=1, max_value=10, value=3)
    ma_needed = st.checkbox("MAあり", value=True)

notes = st.text_area("備考（任意）", placeholder="案件概要・媒体などを簡単に")

st.markdown("---")
if st.button("▶ 見積アイテムを生成（Gemini 2.5 Flash）", type="primary"):
    with st.spinner("生成中..."):
        case_block = build_case_block(
            final_duration=final_duration,
            num_versions=int(num_versions),
            shoot_days=int(shoot_days),
            edit_days=int(edit_days),
            cast_main=int(cast_main),
            ma_needed=bool(ma_needed),
            notes=notes,
        )
        items_obj = call_g25_items_json(case_block)
        df = df_from_items(items_obj)
        meta = totals(df, tax_rate=0.10)

    st.success(f"モデル: gemini-2.5-flash / 行数: {len(df)}")

    if len(df):
        st.dataframe(df[["category","task","qty","unit","unit_price","note","amount"]], use_container_width=True)
    else:
        st.info("items が空でした。備考にもう少し具体的な条件（例: スタジオ / ロケ、BGM、ナレーション等）を加えて再実行してみてください。")

    st.markdown(
        f"**小計（税抜）** : {meta['taxable']:,} 円　/　"
        f"**消費税** : {meta['tax']:,} 円　/　"
        f"**合計** : **{meta['total']:,} 円**"
    )

    with st.expander("デバッグ：生成 JSON"):
        st.code(json.dumps(items_obj, ensure_ascii=False, indent=2), language="json")

else:
    st.caption("※ このバージョンでは、2.5 Flash 以外のモデルや 2.0 への切替・他社APIへのフォールバックは一切行いません。")
