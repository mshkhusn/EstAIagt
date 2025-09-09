# -*- coding: utf-8 -*-
"""
movie_app.py  —  Gemini 2.5 Flash 専用・概算見積（JSON生成）
- 映像制作ドメインを既定（備考に非映像が明示される場合のみ許可）
- JSON のみの出力（{"items":[...]}）
- 各行: category, task, qty, unit, unit_price, note（内訳）
- 最低3行 + 管理費（固定）必須
- UI 幅広 / Excel ダウンロード（note入り） / ドメイン漂流の自動1回リトライ（任意）
"""

from __future__ import annotations

import json
import os
from io import BytesIO
from typing import Any, Dict, List, Tuple

import pandas as pd
import streamlit as st

# ---- Gemini ---------------------------------------------------------------
import google.generativeai as genai

# ここに環境変数で API キーを入れておくか、直接文字列で設定してください
# os.environ["GEMINI_API_KEY"] = "YOUR_API_KEY"
genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))

# --------------------------------------------------------------------------
# 画面設定
# --------------------------------------------------------------------------
st.set_page_config(
    page_title="概算見積（Gemini 2.5 Flash）",
    page_icon="🎬",
    layout="wide",
)

# --------------------------------------------------------------------------
# 強力なシステム指示（常時有効）
# --------------------------------------------------------------------------
SYSTEM_INSTRUCTION_JA = """
あなたは広告映像制作の見積りを作成するエキスパートです。
以降のやり取りでは、原則として広告映像の見積りのみを扱います。
- ただし「備考」に非映像（印刷、配布、Web/サイト制作等）が【明示】されている場合のみ、そのドメインで見積りを作成して構いません。
- 曖昧な場合は広告映像に限定します。
- 返答は JSON のみ（マークダウンや説明文を出力しない）。
- ルートは {"items": [...]}。各要素は {category, task, qty, unit, unit_price, note} を必須。
- 最低3行以上。管理費（固定：qty=1, unit=式）を必ず含める。
- note は各行の内訳を端的に記す（例：機材種別、作業範囲、含まれる工程など）。
"""

STRICT_JSON_HEADER = """あなたはJSONバリデータでもあります。以下を満たさない出力は無効です。
- 返答は JSON のみ。マークダウンや説明文は出力しない。
- ルート: {"items": [...]}
- 各要素: {"category": str, "task": str, "qty": int, "unit": str, "unit_price": int, "note": str}
- 数値は整数、日本円。unit は「式/日/人/部/本/回/曲」など自然な単位を用いる。
- note は各行の内訳（機材/役割/作業範囲等）を短く明記。
"""

def _inference_block() -> str:
    # ドメイン漂流を抑えるためのルール（system_instruction と同じ方向性）
    return """
- 原則：広告映像の概算見積りとして作成する。
- 「備考」に非映像（印刷/配布、Web/サイト制作等）が【明示】されているときのみ、そのドメインを許可。
- 曖昧なら映像に限定する。
- 最低3行以上、管理費（固定：qty=1, unit=式）を必ず含める。
- 各行の note に内訳（機材種別、含まれる工程 等）を簡潔に記す。
"""

def get_gemini_model():
    """system_instruction を常時付与した 2.5 Flash モデル"""
    return genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=SYSTEM_INSTRUCTION_JA
    )

# --------------------------------------------------------------------------
# プロンプトビルド
# --------------------------------------------------------------------------
def build_structured_prompt(
    duration_label: str,
    deliverables: int,
    shoot_days: int,
    edit_days: int,
    notes: str,
    restrict_video_domain: bool,
) -> str:
    domain_guard = "（映像限定で作成）" if restrict_video_domain else "（備考に明示が無ければ映像限定）"
    return f"""{STRICT_JSON_HEADER}
{_inference_block()}

【案件条件 {domain_guard}】
- 尺の長さ: {duration_label}
- 納品本数: {deliverables} 本
- 撮影日数: {shoot_days} 日
- 編集日数: {edit_days} 日
- 備考: {notes if notes else "特になし"}

出力は JSON のみ（説明は不要）。"""

def build_minimal_prompt() -> str:
    return f"""{STRICT_JSON_HEADER}
{_inference_block()}
【最小要件】最低3行以上、管理費（固定）必須。JSONのみ。"""

def build_seed_prompt() -> str:
    seed = {
        "items": [
            {"category":"制作費","task":"企画構成費","qty":1,"unit":"式","unit_price":50000,"note":"構成案・進行管理"},
            {"category":"撮影費","task":"カメラマン費","qty":2,"unit":"日","unit_price":80000,"note":"撮影一式"},
            {"category":"編集費・MA費","task":"編集","qty":3,"unit":"日","unit_price":70000,"note":"編集一式"},
            {"category":"管理費","task":"管理費（固定）","qty":1,"unit":"式","unit_price":60000,"note":"全体進行"}
        ]
    }
    return f"""{STRICT_JSON_HEADER}
{_inference_block()}
以下の例に近い構造で、案件条件に合わせた値へ置換して JSON のみを返してください。
{json.dumps(seed, ensure_ascii=False)}"""

# --------------------------------------------------------------------------
# 生成呼び出し・整形
# --------------------------------------------------------------------------
def gemini_call(user_prompt: str) -> Tuple[str, str, Dict[str, Any]]:
    """
    Gemini に投げて text, finish_reason, meta を返す。
    text が空文字のときはモデルの 'to_dict()' から拾えないケースなので空で返す。
    """
    model = get_gemini_model()
    resp = model.generate_content(user_prompt)

    text_out = ""
    finish = None

    # まずは .text（通常はここに JSON が来る）
    if hasattr(resp, "text") and resp.text:
        text_out = resp.text.strip()

    # finish_reason を補足
    try:
        finish = getattr(resp, "finish_reason", None)
        if finish is None and getattr(resp, "candidates", None):
            finish = resp.candidates[0].finish_reason
    except Exception:
        pass

    meta = {
        "prompt_token_count": getattr(getattr(resp, "usage_metadata", None), "prompt_token_count", None),
        "total_token_count": getattr(getattr(resp, "usage_metadata", None), "total_token_count", None),
        "finish_reason": finish,
        "model_used": "gemini-2.5-flash",
    }

    return text_out, finish, meta

def extract_json_from_text(text: str) -> Dict[str, Any]:
    """
    モデル出力から JSON を抽出・パース。
    - ```json ... ``` や ``` ... ``` のフェンスに対応
    - それ以外は生文字列そのまま json.loads にかける
    """
    if not text:
        return {}

    s = text.strip()
    fences = ["```json", "```"]
    if s.startswith("```"):
        # 最初の ``` を外して末尾 ``` まで
        try:
            s_ = s.strip("`")
            # 先頭に "json" が付いている場合もあるが json.loads は同じ
            if s_.lower().startswith("json"):
                s_ = s_[4:].strip()
            s = s_
        except Exception:
            pass

    # たまにコードフェンスが中途半端なことがあるので最後の ``` を除去
    if s.endswith("```"):
        s = s[:-3].strip()

    try:
        data = json.loads(s)
        if isinstance(data, dict) and "items" in data and isinstance(data["items"], list):
            return data
    except Exception:
        pass

    # ダメなら空
    return {}

def add_amount_and_format(df: pd.DataFrame) -> pd.DataFrame:
    """amount 列を追加（qty*unit_price）し、表示用のフォーマット列は UI 側で設定"""
    if df.empty:
        return df
    df["amount"] = df["qty"].astype(int) * df["unit_price"].astype(int)
    return df

def ensure_admin_row(df: pd.DataFrame) -> pd.DataFrame:
    """管理費（固定）行が無ければ追加する"""
    if df.empty:
        return df
    has_admin = any(df["category"].astype(str).str.contains("管理費", na=False))
    if not has_admin:
        df = pd.concat([
            df,
            pd.DataFrame([{
                "category": "管理費",
                "task": "管理費（固定）",
                "qty": 1,
                "unit": "式",
                "unit_price": 60000,
                "note": "全体進行・品質管理"
            }])
        ], ignore_index=True)
    return df

DRIFT_KEYWORDS = ["印刷", "チラシ", "フライヤ", "ポスター", "配送", "配布", "Web", "ウェブ", "サイト制作", "DM", "封入", "折込"]

def looks_like_non_video(items: List[Dict[str, Any]], notes: str) -> bool:
    """ドメイン漂流（非映像）らしさの簡易検出。備考に明示されていれば True。"""
    src = notes or ""
    for it in items or []:
        src += " " + str(it.get("category", "")) + " " + str(it.get("task", "")) + " " + str(it.get("note", ""))
    return any(k in src for k in DRIFT_KEYWORDS)

# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------
st.title("概算見積（柔軟版：Gemini 2.5 Flash）")

with st.expander("入力（自由記入）", expanded=True):
    colL, colR = st.columns([1, 1])
    with colL:
        duration = st.selectbox("尺の長さ", ["15秒", "30秒", "60秒", "90秒", "120秒"], index=1)
        deliverables = st.number_input("納品本数", min_value=1, max_value=20, value=1, step=1)
    with colR:
        shoot_days = st.number_input("撮影日数", min_value=0, max_value=30, value=2, step=1)
        edit_days = st.number_input("編集日数", min_value=0, max_value=60, value=3, step=1)

    notes = st.text_area(
        "備考（自由記入）",
        placeholder="例：スタジオ撮影、出演者1名、MAあり など（※印刷/Web等は明示した場合のみ可）",
        height=110,
    )
    restrict_video = st.checkbox("映像ドメインに限定（印刷/媒体/Web を含めない）", value=False)

st.write("---")

# 生成ボタン
btn = st.button("▶ 見積アイテムを生成（Gemini 2.5 Flash）", type="primary")

# セッション状態で表を持つ（DLしても消えない）
if "df_result" not in st.session_state:
    st.session_state.df_result = pd.DataFrame()
if "meta_result" not in st.session_state:
    st.session_state.meta_result = {}

if btn:
    # 1st トライ
    prompt = build_structured_prompt(duration, deliverables, shoot_days, edit_days, notes, restrict_video)
    text, finish, meta = gemini_call(prompt)

    data = extract_json_from_text(text)
    run_count = 1

    # 失敗（空 or items 無し）の場合、保険で最小/シードを順に当てる
    if not data.get("items"):
        run_count += 1
        text2, finish2, _ = gemini_call(build_minimal_prompt())
        data = extract_json_from_text(text2)

    if not data.get("items"):
        run_count += 1
        text3, finish3, _ = gemini_call(build_seed_prompt())
        data = extract_json_from_text(text3)

    # 漂流検知（備考に映像外が明示でない・かつ restrict_video=ON のときのみ、1回だけ映像限定リトライ）
    if data.get("items") and restrict_video and looks_like_non_video(data["items"], notes):
        run_count += 1
        strict_prompt = build_structured_prompt(duration, deliverables, shoot_days, edit_days, notes + "（映像に限定して作成）", True)
        text4, finish4, _ = gemini_call(strict_prompt)
        data2 = extract_json_from_text(text4)
        if data2.get("items"):
            data = data2

    # DataFrame 化
    items = data.get("items", [])
    if items:
        df = pd.DataFrame(items, columns=["category", "task", "qty", "unit", "unit_price", "note"])
        # 型整形
        for c in ("qty", "unit_price"):
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
        df = ensure_admin_row(df)
        df = add_amount_and_format(df)
        st.session_state.df_result = df.copy()
    else:
        st.session_state.df_result = pd.DataFrame()

    # メタ情報
    meta["runs"] = run_count
    st.session_state.meta_result = meta

# モデル情報
if st.session_state.meta_result:
    meta = st.session_state.meta_result
    st.info(
        f"モデル: {meta.get('model_used')} / 行数: {meta.get('runs')} / finish: {meta.get('finish_reason')}  "
        f"/ prompt_tokens: {meta.get('prompt_token_count')} / total_tokens: {meta.get('total_token_count')}"
    )

# 結果表示
df_show = st.session_state.df_result.copy()

if df_show.empty:
    st.warning("items が空でした。備考をもう少し具体的にすると安定します。")
else:
    # 表示
    st.subheader("見積アイテム（note＝内訳を保持）")
    fmt_df = df_show.copy()
    # 表示用フォーマット
    fmt_df["qty"] = fmt_df["qty"].map(lambda x: f"{x:,}")
    fmt_df["unit_price"] = fmt_df["unit_price"].map(lambda x: f"{x:,}")
    fmt_df["amount"] = fmt_df["amount"].map(lambda x: f"{x:,}")

    st.dataframe(
        fmt_df[["category", "task", "qty", "unit", "unit_price", "note", "amount"]],
        use_container_width=True,
        hide_index=True,
        height=min(480, 120 + 35 * len(fmt_df)),
    )

    # 小計
    subtotal = st.session_state.df_result["amount"].sum()
    tax = int(round(subtotal * 0.10))
    total = subtotal + tax

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("小計（税抜）", f"{subtotal:,} 円")
    with col2:
        st.metric("消費税", f"{tax:,} 円")
    with col3:
        st.metric("合計", f"{total:,} 円")

    # Excel ダウンロード（note入り、表は消えない）
    def to_excel_bytes(df: pd.DataFrame) -> bytes:
        output = BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            df.to_excel(writer, sheet_name="estimate", index=False)
        return output.getvalue()

    xls = to_excel_bytes(st.session_state.df_result)
    st.download_button(
        "📥 Excelダウンロード（note入り）",
        data=xls,
        file_name="estimate_items.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=False,
    )

# Debug（任意）
with st.expander("デバッグ：生成 RAW（JSONテキストとして整形前）", expanded=False):
    st.caption("モデルが ```json フェンスで返す場合があるので、そのまま貼っています。")
    # 直近呼び出しテキストは保持していないため、UI簡潔化の都合で省略

st.write("※ フィルタ除去は行いません。備考に応じて「映像ドメインに限定」チェックでガードをかけられます。")
