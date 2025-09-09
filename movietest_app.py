# movietest_app.py
# Gemini 2.5 Flash | JSON 最小テスト（単価強制・軽微リトライ付き）

import os
import re
import json
from typing import Any, Dict, List

import streamlit as st
import pandas as pd
import google.generativeai as genai

# =========================
# 初期設定
# =========================
API_KEY = os.getenv("GEMINI_API_KEY", st.secrets.get("GEMINI_API_KEY", ""))
st.set_page_config(page_title="Gemini 2.5 Flash | JSON 最小テスト", layout="centered")

if not API_KEY:
    st.error("環境変数または st.secrets に GEMINI_API_KEY を設定してください。")
    st.stop()

genai.configure(api_key=API_KEY)

MODEL_ID = "gemini-2.5-flash"
TAX_RATE = 0.10
MGMT_CAP = 0.15  # 管理費上限（あくまで参考値・検算用）

# =========================
# ユーティリティ
# =========================
def strip_code_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.I)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()

def try_parse_json(s: str) -> Dict[str, Any]:
    """できるだけ粘って JSON として辞書を返す。ダメなら {}。"""
    if not s:
        return {}
    s = strip_code_fences(s)

    # 1) 素直に
    try:
        return json.loads(s)
    except Exception:
        pass

    # 2) 先頭 { から末尾 } までを拾って再トライ
    try:
        b, e = s.find("{"), s.rfind("}")
        if b != -1 and e != -1 and e > b:
            frag = s[b:e+1]
            # True/False/None → JSON に寄せる、末尾カンマ除去など軽整形
            frag = re.sub(r"\bTrue\b", "true", frag)
            frag = re.sub(r"\bFalse\b", "false", frag)
            frag = re.sub(r"\bNone\b", "null", frag)
            frag = re.sub(r",\s*([}\]])", r"\1", frag)
            return json.loads(frag)
    except Exception:
        pass
    return {}

def extract_text(resp) -> str:
    """resp.text が空のとき parts から寄せ集める（最小限）。"""
    try:
        if getattr(resp, "text", None):
            return resp.text
    except Exception:
        pass
    try:
        d = resp.to_dict()
        cands = d.get("candidates", [])
        buf: List[str] = []
        for c in cands:
            content = c.get("content", {})
            for p in content.get("parts", []):
                t = p.get("text")
                if t:
                    buf.append(t)
        return "".join(buf)
    except Exception:
        return ""

def norm_items(df: pd.DataFrame) -> pd.DataFrame:
    """数値列を強制整形し、欠損を埋める。"""
    need_cols = ["category", "task", "qty", "unit", "unit_price", "note"]
    for c in need_cols:
        if c not in df.columns:
            df[c] = "" if c in ["category", "task", "unit", "note"] else 0

    df["qty"] = pd.to_numeric(df["qty"], errors="coerce").fillna(0.0)
    df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce").fillna(0).astype(int)
    return df[need_cols]

def compute_totals(df: pd.DataFrame) -> Dict[str, int]:
    subtotal = int((df["qty"] * df["unit_price"]).round().sum())
    tax = int(round(subtotal * TAX_RATE))
    total = subtotal + tax
    return {"subtotal": subtotal, "tax": tax, "total": total}

# =========================
# プロンプト
# =========================
SCHEMA = """\
出力は**JSONオブジェクト1個のみ**。絶対に説明文やコードフェンスを含めないでください。

【必須スキーマ】
{
  "items": [
    {
      "category": "制作費|撮影費|編集費・MA費|出演関連費|諸経費|管理費",
      "task": "具体的な項目名（例：カメラマン費）",
      "qty": 数値,                   # 小数可
      "unit": "日|人|式|本|時間|カット など",
      "unit_price": 整数(>=1000),   # JPY、必ず 1000 以上の整数
      "note": "補足（任意）"
    },
    ...
  ]
}

【厳守事項】
- 出力は JSON のみ・コードフェンス禁止。
- 各 item の unit_price は **必ず 1000 以上の整数**。0 や未設定は禁止。
- 日本の広告映像の一般的な相場レンジで妥当な金額にすること。
- 項目数は 6〜12 件程度。重複は避ける。
- 管理費は 1 行だけ（task=管理費（固定）, qty=1, unit=式）。金額は非ゼロで妥当な水準に。
- 合計/税は出さない。HTMLも禁止。"""

def build_prompt(user_notes: str) -> str:
    return f"""あなたは広告映像制作の見積り項目を作成するアシスタントです。
以下の案件条件を読み、上記スキーマに従って items のみを返してください。

【案件条件（自由記入）】
{user_notes}

{SCHEMA}
"""

# =========================
# UI
# =========================
st.title("Gemini 2.5 Flash ｜ JSON 最小テスト（見積アイテムのみ）")

with st.form("f"):
    notes = st.text_area(
        "案件条件（自由記入）",
        placeholder="例：\n- 30秒、納品1本\n- 撮影2日 / 編集3日\n- 都内スタジオ / キャスト1名 / MAあり\n- 参考：商品紹介映像、インタビューなし",
        height=180,
    )
    colb = st.columns(2)
    with colb[0]:
        submit = st.form_submit_button("▶ JSON を生成", use_container_width=True)

st.caption("モデル: **gemini-2.5-flash**")

# =========================
# 実行
# =========================
if submit:
    prompt = build_prompt(notes or "(空文字)")

    model = genai.GenerativeModel(
        MODEL_ID,
        generation_config={
            "temperature": 0.3,
            "top_p": 0.9,
            "max_output_tokens": 2048,
        },
    )

    # 1回目
    resp1 = model.generate_content(prompt)
    text = extract_text(resp1)

    # 必要なら 1回だけリトライ（簡易）
    run_info = [{"run": 1, "finish": getattr(resp1, "finish_reason", None), "text_len": len(text or "")}]
    if not text or len(text.strip()) < 3:
        resp2 = model.generate_content(prompt + "\n\n前回の応答が空でした。**必ず JSON オブジェクト1個のみ**を出力してください。")
        text = extract_text(resp2)
        run_info.append({"run": 2, "finish": getattr(resp2, "finish_reason", None), "text_len": len(text or "")})

    obj = try_parse_json(text)
    items = obj.get("items") if isinstance(obj, dict) else None

    if not isinstance(items, list) or len(items) == 0:
        st.warning("items が空です。プロンプトを少し具体的にして再試行してください。")
        with st.expander("デバッグ：モデル生出力（RAWテキスト）", expanded=False):
            st.code(text or "(empty)")
        with st.expander("デバッグ：to_dict()（最終応答）", expanded=False):
            try:
                st.code((resp2 if len(run_info) > 1 else resp1).to_dict())
            except Exception:
                st.write("(to_dict 取得不可)")
        st.dataframe(pd.DataFrame(run_info))
        st.stop()

    # 表示用に DataFrame 化
    df = pd.DataFrame(items)
    df = norm_items(df)

    # 単価が 1000 未満のものがあれば赤字で示す（検知）
    bad = df["unit_price"] < 1000
    if bad.any():
        st.error("⚠ unit_price に 1000 未満が含まれています（モデルへ強制済みですが、出力が守られなかったケース）。必要に応じて再生成してください。")

    # 計算
    totals = compute_totals(df)

    st.subheader("整形後 JSON")
    st.code(json.dumps({"items": json.loads(df.to_json(orient="records", force_ascii=False))}, ensure_ascii=False, indent=2), language="json")

    st.subheader("見積アイテム（検算付き）")
    df_view = df.copy()
    df_view["金額（円）"] = (df_view["qty"] * df_view["unit_price"]).round().astype(int)
    st.dataframe(df_view, use_container_width=True)

    st.write(
        f"**小計（税抜）**：{totals['subtotal']:,} 円　／　"
        f"**消費税**：{totals['tax']:,} 円　／　"
        f"**合計**：**{totals['total']:,} 円**"
    )

    with st.expander("デバッグ：to_dict()（最終応答）", expanded=False):
        try:
            st.code((resp2 if len(run_info) > 1 else resp1).to_dict())
        except Exception:
            st.write("(to_dict 取得不可)")

    with st.expander("サマリ（各 run）", expanded=False):
        st.dataframe(pd.DataFrame(run_info), use_container_width=True)
