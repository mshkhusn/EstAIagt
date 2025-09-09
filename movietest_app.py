# movie_app.py
# -*- coding: utf-8 -*-
#
# 概算見積（movie_app 風 UI）
# - プロンプト入力 + Gemini 2.5 Flash で JSON 生成
# - 正規化（カテゴリ/単位/数字）& 金額計算
# - note（内訳）を保持
# - （任意）映像ドメインを優先する「軽いガード」
# - Excel ダウンロード
# - デバッグ（モデル/finish_reason/RAWプレビュー）
#
# 必要: pip install streamlit pandas google-generativeai xlsxwriter

from __future__ import annotations

import os
import io
import re
import json
import math
import time
import datetime as dt
from decimal import Decimal, InvalidOperation

import streamlit as st
import pandas as pd

# Google Generative AI (Gemini)
import google.generativeai as genai


# -----------------------------
# 設定
# -----------------------------
APP_TITLE = "概算見積（movie_app スタイル / Gemini 2.5 Flash）"
MODEL_NAME = "gemini-2.5-flash"
TAX_RATE = Decimal("0.10")  # 消費税率 10%

# Streamlit ページ設定
st.set_page_config(page_title=APP_TITLE, layout="wide")


# -----------------------------
# API キー設定
# -----------------------------
def get_api_key() -> str | None:
    if "GOOGLE_API_KEY" in st.secrets:
        return st.secrets["GOOGLE_API_KEY"]
    return os.environ.get("GOOGLE_API_KEY")


api_key = get_api_key()
if not api_key:
    st.error("❌ Google API キーが未設定です。`GOOGLE_API_KEY` を環境変数または `st.secrets` に設定してください。")
    st.stop()

genai.configure(api_key=api_key)
model = genai.GenerativeModel(MODEL_NAME)


# -----------------------------
# プロンプト（システム前置き）
# -----------------------------
SYSTEM_ROLE = """
あなたは**広告映像制作の見積りを作成するエキスパート**です。
日本の映像業界の一般的な区分と相場感に沿って、合理的で説明可能な概算見積のテンプレートを生成します。

必ず JSON だけを返してください。コードフェンスは不要です。
スキーマ:
{
  "items":[
    {
      "category": "制作費|撮影費|編集費・MA費|音楽・効果音|その他|管理費",
      "task": "項目名（例: 企画構成費 / カメラマン費 / 編集費 / MA費 など）",
      "qty": 数量（整数）,
      "unit": "式|日|人|曲|本|回|部|式など",
      "unit_price": 単価（整数・円）,
      "note": "内訳・条件・補足（日本語で簡潔に。機材/人員/範囲など）"
    }
  ]
}

制約:
- 「note」には内訳（機材・人員・編集工程・拘束時間など）を短文で残す
- 不明点は常識的に補い、冗長な文章は避ける
- 金額は整数（円）で出す
- 映像以外の依頼だと判断できる場合は、そのドメインで自然な見積項目を作成してよい
- ただし依頼文に映像/動画の意図が読み取れる場合は映像ドメインを優先

出力以外のテキストは禁止。JSONのみ返すこと。
""".strip()


# -----------------------------
# 軽いバリデーション / 正規化
# -----------------------------
CANON_UNITS = {
    "式": {"式", "一式", "パッケージ"},
    "日": {"日", "day", "days"},
    "人": {"人", "名"},
    "曲": {"曲"},
    "本": {"本"},
    "回": {"回"},
    "部": {"部"},
}

VIDEO_FAVOR_KEYWORDS = {
    "制作費", "撮影", "編集", "MA", "BGM", "SE", "ナレーション", "スタジオ",
    "カメラ", "照明", "機材", "撮影機材", "ロケ", "ディレクター", "プロデューサー",
    "プロジェクト管理", "進行管理", "色調整", "効果音", "音声", "収録"
}

# カテゴリの優先順（並び替え用）
CATEGORY_ORDER = {
    "制作費": 0,
    "撮影費": 1,
    "編集費・MA費": 2,
    "音楽・効果音": 3,
    "その他": 8,
    "管理費": 9,
}


def _to_int(v, default=0) -> int:
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip().replace(",", "")
    try:
        return int(Decimal(s))
    except (InvalidOperation, ValueError):
        return default


def _canon_unit(unit: str) -> str:
    if not unit:
        return "式"
    s = str(unit).strip()
    for k, alts in CANON_UNITS.items():
        if s in alts:
            return k
    # 単位に数字や未知文字が来たら式に寄せる
    return "式" if len(s) > 3 or any(ch.isdigit() for ch in s) else s


def normalize_items(items: list[dict], video_only_hint: bool) -> list[dict]:
    """数量/単価/カテゴリ/単位/メモなどを正規化。"""
    norm = []
    for raw in items or []:
        category = str(raw.get("category", "")).strip() or "その他"
        task = str(raw.get("task", "")).strip() or "未定義"
        qty = _to_int(raw.get("qty"), 1)
        unit_price = _to_int(raw.get("unit_price"), 0)
        unit = _canon_unit(raw.get("unit", "式"))
        note = str(raw.get("note", "")).strip()

        # あり得ない数値の矯正（マイナス/巨大値など）
        qty = max(0, min(qty, 10**6))
        unit_price = max(0, min(unit_price, 10**9))

        # カテゴリゆれを軽く吸収
        cat_alias = {
            "編集費": "編集費・MA費",
            "MA費": "編集費・MA費",
            "音響": "音楽・効果音",
            "効果音": "音楽・効果音",
            "管理費（固定）": "管理費",
            "企画・構成": "制作費",
            "制作": "制作費",
        }
        category = cat_alias.get(category, category)

        # 動画ドメイン優先ヒントがオン → 明らかに非映像ドメインの可能性が高い（Web, 印刷など）
        # ただしユーザーが明示している場合は残すため「除外」はせず、優先カテゴリの方へ寄せるだけ
        if video_only_hint:
            if any(k in task for k in VIDEO_FAVOR_KEYWORDS) or any(k in note for k in VIDEO_FAVOR_KEYWORDS):
                pass
            else:
                # ざっくり映像寄りのカテゴリに寄せる（タスク名はそのまま）
                non_video_triggers = {"チラシ", "印刷", "ウェブ", "Web", "LP", "バナー", "DTP", "コピー用紙", "オフィスチェア"}
                if any(t in task + note for t in non_video_triggers):
                    # 触らない（ユーザーの意図で非映像も残したいケースがあったため）
                    pass
                else:
                    # どれにも該当しない場合は、制作費に寄せる
                    category = "制作費"

        # 1行の辞書に正規化
        norm.append({
            "category": category,
            "task": task,
            "qty": qty,
            "unit": unit,
            "unit_price": unit_price,
            "note": note,
            "amount": qty * unit_price,
        })

    # 並び替え（カテゴリ順→管理費は最後、同カテゴリはそのまま）
    norm.sort(key=lambda r: (CATEGORY_ORDER.get(r["category"], 50)))
    return norm


def compute_totals(rows: list[dict]) -> tuple[int, int, int]:
    subtotal = sum(r.get("amount", 0) for r in rows)
    tax = int(Decimal(subtotal) * TAX_RATE)
    total = subtotal + tax
    return subtotal, tax, total


# -----------------------------
# JSON 抽出ユーティリティ
# -----------------------------
RE_JSON_BLOCK = re.compile(r"\{(?:.|\n)*\}", re.MULTILINE)

def extract_json_from_text(text: str) -> dict | None:
    """レスポンステキストから最初の JSON ブロックを抽出して読み込む。"""
    if not text:
        return None
    # 「```json ... ```」も「{...}」も拾う
    # まず code fence を優先
    fence = re.search(r"```json\s*(\{(?:.|\n)*?\})\s*```", text, re.IGNORECASE)
    if fence:
        try:
            return json.loads(fence.group(1))
        except Exception:
            pass
    # 次に最初の { ... } ブロック
    m = RE_JSON_BLOCK.search(text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


# -----------------------------
# LLM 呼び出し
# -----------------------------
def call_gemini(prompt: str) -> dict:
    """Gemini 呼び出し → JSON 返却（失敗時は空 stub）"""
    full_prompt = SYSTEM_ROLE + "\n\n" + prompt.strip()

    try:
        res = model.generate_content(full_prompt)
        # 基本は text を使う
        text = getattr(res, "text", "") or ""
        data = extract_json_from_text(text) or {}

        meta = {
            "model_used": MODEL_NAME,
            "finish_reason": getattr(res.candidates[0], "finish_reason", None) if getattr(res, "candidates", None) else None,
            "usage": getattr(res, "usage_metadata", None),
            "raw_preview": (text[:1000] + " ...") if len(text) > 1000 else text,
        }

        # items が無い・空なら空 stub を返す
        if not isinstance(data, dict) or "items" not in data:
            data = {"items": []}
        return {"data": data, "meta": meta}

    except Exception as e:
        return {"data": {"items": []}, "meta": {"error": str(e), "model_used": MODEL_NAME}}


# -----------------------------
# Excel ダウンロード
# -----------------------------
def build_excel_download(df: pd.DataFrame, subtotal: int, tax: int, total: int) -> bytes:
    """note 列込みの Excel を作成（XlsxWriter）。"""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="estimate")
        wb = writer.book
        ws = writer.sheets["estimate"]

        # 通貨書式
        fmt_money = wb.add_format({"num_format": "#,##0", "align": "right"})
        fmt_head = wb.add_format({"bold": True, "bg_color": "#F2F2F2"})

        # 先頭行をヘッダ書式
        ws.set_row(0, 20, fmt_head)

        # 金額関連列にフォーマット
        for col_name in ("qty", "unit_price", "amount"):
            if col_name in df.columns:
                col_idx = df.columns.get_loc(col_name)
                ws.set_column(col_idx, col_idx, 12, fmt_money)

        # note 列幅・任意調整
        if "note" in df.columns:
            note_idx = df.columns.get_loc("note")
            ws.set_column(note_idx, note_idx, 50)

        # 最終行の下に totals
        row = len(df) + 2
        ws.write(row + 0, 0, "小計（税抜）")
        ws.write(row + 0, 1, subtotal, fmt_money)
        ws.write(row + 1, 0, "消費税")
        ws.write(row + 1, 1, tax, fmt_money)
        ws.write(row + 2, 0, "合計")
        ws.write(row + 2, 1, total, fmt_money)

    return output.getvalue()


# -----------------------------
# UI
# -----------------------------
st.title(APP_TITLE)

with st.expander("入力（プロンプト）", expanded=True):
    c1, c2 = st.columns([1, 1])
    with c1:
        st.markdown("**案件条件（自由記入）**")
        default_text = (
            "案件:\n"
            "- 30秒、納品1本\n"
            "- 撮影2日 / 編集3日\n"
            "- 構成: 通常的な広告映像（インタビュー無し）\n"
            "- 参考: 撮影は都内スタジオ、キャスト1名、MAあり\n"
        )
        user_free = st.text_area(" ", value=default_text, height=180, label_visibility="collapsed")

    with c2:
        st.markdown("**補足オプション**")
        hint_video_only = st.checkbox("映像ドメインを優先（印刷/Webを含めないわけではない）", value=True)
        st.caption("※ 完全なフィルタではなく、映像系カテゴリへ軽く寄せるヒントです。")
        st.markdown("---")
        st.markdown("**注意**: 生成は *Gemini 2.5 Flash* を使用。返答不安定時は備考を少し具体化して再生成してください。")

btn = st.button("▶︎ 見積アイテムを生成（Gemini 2.5 Flash）", type="primary")

st.markdown("---")

if btn:
    with st.spinner("生成中..."):
        call = call_gemini(user_free)

    data = call["data"]
    meta = call["meta"]

    # モデルメタ
    with st.expander("モデル情報", expanded=False):
        st.write({k: v for k, v in meta.items() if k != "raw_preview"})
        st.text_area("RAWテキスト（プレビュー）", meta.get("raw_preview", ""), height=180)

    # 正規化
    items = data.get("items", [])
    norm_rows = normalize_items(items, video_only_hint=hint_video_only)

    # DataFrame
    df = pd.DataFrame(norm_rows, columns=["category", "task", "qty", "unit", "unit_price", "note", "amount"])
    subtotal, tax, total = compute_totals(norm_rows)

    # 結果表示
    st.subheader("見積アイテム（note＝内訳を保持）")
    st.caption(f"モデル: {meta.get('model_used')} / 行数: {len(df)} / finish: {meta.get('finish_reason')}")
    st.dataframe(df, use_container_width=True)

    # 合計
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("小計（税抜）", f"{subtotal:,.0f} 円")
    with c2:
        st.metric("消費税", f"{tax:,.0f} 円")
    with c3:
        st.metric("合計", f"{total:,.0f} 円")

    # Excel DL
    excel_bytes = build_excel_download(df, subtotal, tax, total)
    st.download_button(
        "📥 Excelダウンロード（note入り）",
        data=excel_bytes,
        file_name=f"estimate_{dt.datetime.now():%Y%m%d_%H%M}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

else:
    st.info("左上のプロンプトを編集して『見積アイテムを生成』を押してください。")
