# movie_app.py

import streamlit as st
import google.generativeai as genai
from openai import OpenAI

# ─── 1. ページ設定 ──────────────────────────────────────────────────────────
st.set_page_config(
    page_title="映像制作AIエージェント",
    layout="centered"
)

# ─── 2. Secrets 読み込み & クライアント初期化 ────────────────────────────────
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
APP_PASSWORD   = st.secrets["APP_PASSWORD"]

genai.configure(api_key=GEMINI_API_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# ─── 3. 認証 ───────────────────────────────────────────────────────────────
st.title("映像制作AIエージェント（三段階プロンプト化版）")
password = st.text_input("パスワードを入力してください", type="password")
if password != APP_PASSWORD:
    st.warning("🔒 認証が必要です")
    st.stop()

# ─── 4. ユーザー入力フォーム ─────────────────────────────────────────────────
st.header("制作条件の入力")
video_duration = st.selectbox("尺の長さ", ["15秒", "30秒", "60秒", "その他"])
final_duration = (
    st.text_input("尺の長さ（自由記入）") if video_duration == "その他" else video_duration
)
num_versions   = st.number_input("納品本数", min_value=1, max_value=10, value=1)
shoot_days     = st.number_input("撮影日数", min_value=1, max_value=10, value=2)
edit_days      = st.number_input("編集日数", min_value=1, max_value=10, value=3)
delivery_date  = st.date_input("納品希望日")
cast_main      = st.number_input("メインキャスト人数", 0, 10, 1)
cast_extra     = st.number_input("エキストラ人数", 0, 20, 0)
talent_use     = st.checkbox("タレント起用あり")
staff_roles    = st.multiselect(
    "必要なスタッフ",
    ["制作プロデューサー", "制作プロジェクトマネージャー", "ディレクター", "カメラマン",
     "照明スタッフ", "スタイリスト", "ヘアメイク", "アシスタント"]
)
shoot_location     = st.text_input("撮影場所（例：都内スタジオ＋ロケ）")
kizai              = st.multiselect("撮影機材", ["4Kカメラ", "照明", "ドローン", "グリーンバック"])
set_design_quality = st.selectbox(
    "セット建て・美術装飾の規模",
    ["なし", "小（簡易装飾）", "中（通常レベル）", "大（本格セット）"]
)
use_cg        = st.checkbox("CG・VFXあり")
use_narration = st.checkbox("ナレーション収録あり")
use_music     = st.selectbox("音楽素材", ["既存ライセンス音源", "オリジナル制作", "未定"])
ma_needed     = st.checkbox("MAあり")
deliverables  = st.multiselect("納品形式", ["mp4（16:9）", "mp4（1:1）", "mp4（9:16）", "ProRes"])
subtitle_langs = st.multiselect("字幕言語", ["日本語", "英語", "その他"])
usage_region  = st.selectbox("使用地域", ["日本国内", "グローバル", "未定"])
usage_period  = st.selectbox("使用期間", ["6ヶ月", "1年", "2年", "無期限", "未定"])
budget_hint   = st.text_input("参考予算（任意）")
extra_notes   = st.text_area("その他備考（任意）")
model_choice  = st.selectbox("使用するAIモデル", ["Gemini", "GPT-4o", "GPT-4.1"])

# ─── 5. 条件一覧テキスト作成 ─────────────────────────────────────────────────
items = [
    ("制作プロデューサー費", 150_000, f"1名×{shoot_days}日"),
    ("制作PM費",      100_000, f"1名×{shoot_days}日"),
    ("ディレクター費",120_000, f"1名×{shoot_days}日"),
    ("カメラマン費",    100_000, "1名×1日"),
]
condition_lines = "\n".join(
    f"- {name} — 単価：{price}、数量：{qty}"
    for name, price, qty in items
)

# ─── 6. プロンプト①：行ごとの計算 ─────────────────────────────────────────
prompt1 = f"""
以下の各項目について「単価 × 数量」の計算結果を、
「項目名：計算結果（円）」の形式で一行ずつ返してください。

{condition_lines}
"""

# ─── 7. プロンプト②：合計計算 ─────────────────────────────────────────────
prompt2 = """
上記の一覧を受け取り、すべての金額を足し合わせて、
「合計金額（円）：○○○○○○」として1行で返してください。
"""

# ─── 8. プロンプト③：最終見積書生成 ────────────────────────────────────────
prompt3_template = """
あなたは広告制作費のプロフェッショナルな見積もりエージェントです。
以下の条件に基づいて、映像制作に必要な費用を詳細に見積もってください。
予算、納期、仕様、スタッフ構成、撮影条件などから、実務に即した内容で正確かつ論理的に推論してください。
短納期である場合や仕様が複雑な場合には、工数や費用が増える点も加味してください。

【項目別計算結果】
{calc1}

【合計金額】
{calc2}

# 出力形式要件
- HTML + Markdown形式で読みやすく
- テーブル「項目名・詳細・単価・数量・金額」を含む
- 合計金額は太字または色付きで強調
- 備考や注意点を記載
- フォントは Arial を想定
- 正しい HTML 構造で出力してください
"""

# ─── 9. ボタン押下時の処理 ───────────────────────────────────────────────
if st.button("💡 見積もりを作成"):
    with st.spinner("AIが見積もりを作成中…"):
        # ◆ Gemini モード
        if model_choice == "Gemini":
            calc1 = genai.GenerativeModel("gemini-2.0-flash").generate_content(prompt1).text
            calc2 = genai.GenerativeModel("gemini-2.0-flash") \
                         .generate_content(prompt2 + "\n" + calc1).text
            prompt3 = prompt3_template.format(calc1=calc1, calc2=calc2)
            final = genai.GenerativeModel("gemini-2.0-flash").generate_content(prompt3).text

        else:
            # モデル名選択
            model_name = "gpt-4o" if model_choice == "GPT-4o" else "gpt-4.1"
            # ① 行計算
            r1 = openai_client.chat.completions.create(
                model=model_name,
                messages=[{"role":"system","content":"あなたは計算アシスタントです。"},
                          {"role":"user","content":prompt1}],
            )
            calc1 = r1.choices[0].message.content
            # ② 合計計算
            r2 = openai_client.chat.completions.create(
                model=model_name,
                messages=[{"role":"system","content":"あなたは計算アシスタントです。"},
                          {"role":"user","content":prompt2 + "\n" + calc1}],
            )
            calc2 = r2.choices[0].message.content
            # ③ 見積書生成
            prompt3 = prompt3_template.format(calc1=calc1, calc2=calc2)
            r3 = openai_client.chat.completions.create(
                model=model_name,
                messages=[{"role":"system","content":"あなたは広告映像の見積もりアシスタントです。"},
                          {"role":"user","content":prompt3}],
                temperature=0.7,
            )
            final = r3.choices[0].message.content

        # ─── 10. 結果表示 ─────────────────────────────────────────────────
        st.success("✅ 完成された見積書")
        st.components.v1.html(
            f"<div style='font-family:Arial;line-height:1.6;padding:12px'>{final}</div>",
            height=900,
            scrolling=True
        )
