# movie_app.py

import streamlit as st
import google.generativeai as genai
from openai import OpenAI

# ─── 1. ページ設定 ─────────────────────────────────────────────
st.set_page_config(page_title="映像制作AIエージェント", layout="centered")

# ─── 2. Secrets 読み込み & クライアント初期化 ────────────────────
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
APP_PASSWORD   = st.secrets["APP_PASSWORD"]

genai.configure(api_key=GEMINI_API_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# ─── 3. 認証 ─────────────────────────────────────────────────────
st.title("映像制作AIエージェント（3フェーズ＋品質チェック版）")
password = st.text_input("パスワードを入力してください", type="password")
if password != APP_PASSWORD:
    st.warning("🔒 認証が必要です")
    st.stop()

# ─── 4. ユーザー入力フォーム ────────────────────────────────────
st.header("制作条件の入力")
video_duration = st.selectbox("尺の長さ", ["15秒", "30秒", "60秒", "その他"])
if video_duration == "その他":
    final_duration = st.text_input("尺の長さ（自由記入）")
else:
    final_duration = video_duration

num_versions     = st.number_input("納品本数", min_value=1, max_value=10, value=1)
shoot_days       = st.number_input("撮影日数", min_value=1, max_value=10, value=2)
edit_days        = st.number_input("編集日数", min_value=1, max_value=10, value=3)
delivery_date    = st.date_input("納品希望日")
cast_main        = st.number_input("メインキャスト人数", 0, 10, 1)
cast_extra       = st.number_input("エキストラ人数", 0, 20, 0)
talent_use       = st.checkbox("タレント起用あり")
staff_roles      = st.multiselect(
    "必要なスタッフ",
    [
        "制作プロデューサー", "制作プロジェクトマネージャー",
        "ディレクター", "カメラマン", "照明スタッフ",
        "スタイリスト", "ヘアメイク", "アシスタント"
    ]
)
shoot_location     = st.text_input("撮影場所（例：都内スタジオ＋ロケ）")
kizai              = st.multiselect("撮影機材", ["4Kカメラ", "照明", "ドローン", "グリーンバック"])
set_design_quality = st.selectbox(
    "セット建て・美術装飾の規模",
    ["なし", "小（簡易装飾）", "中（通常レベル）", "大（本格セット）"]
)
use_cg         = st.checkbox("CG・VFXあり")
use_narration  = st.checkbox("ナレーション収録あり")
use_music      = st.selectbox("音楽素材", ["既存ライセンス音源", "オリジナル制作", "未定"])
ma_needed      = st.checkbox("MAあり")
deliverables   = st.multiselect("納品形式", ["mp4（16:9）", "mp4（1:1）", "mp4（9:16）", "ProRes"])
subtitle_langs = st.multiselect("字幕言語", ["日本語", "英語", "その他"])
usage_region   = st.selectbox("使用地域", ["日本国内", "グローバル", "未定"])
usage_period   = st.selectbox("使用期間", ["6ヶ月", "1年", "2年", "無期限", "未定"])
budget_hint    = st.text_input("参考予算（任意）")
extra_notes    = st.text_area("その他備考（任意）")
model_choice   = st.selectbox("使用するAIモデル", ["Gemini", "GPT-4o", "GPT-4.1"])

# ─── 5. Prompt A: 項目出しフェーズ ───────────────────────────────
promptA = f"""
あなたは広告制作費のプロフェッショナルな見積もりエージェントです。
以下の条件から、必要な制作工程・リソース（人件費・機材・スタジオ・その他オプションなど）を
漏れなくリストアップしてください。
予算、納期、仕様、スタッフ構成、撮影条件などから、実務に即した内容で正確かつ論理的に推論してください。
短納期である場合や仕様が複雑な場合には、工数や費用が増える点も加味してください。
出力前に、論理的矛盾や抜け漏れがないか自己点検してから返答してください。

【条件】
- 尺：{final_duration}
- 納品本数：{num_versions}本
- 撮影日数：{shoot_days}日
- 編集日数：{edit_days}日
- 納品希望日：{delivery_date}
- メインキャスト人数：{cast_main}人
- エキストラ人数：{cast_extra}人
- タレント：{'あり' if talent_use else 'なし'}
- 必要スタッフ：{', '.join(staff_roles) or 'なし'}
- 撮影場所：{shoot_location or 'なし'}
- 撮影機材：{', '.join(kizai) or 'なし'}
- セット建て・美術装飾：{set_design_quality}
- CG・VFX：{'あり' if use_cg else 'なし'}
- ナレーション：{'あり' if use_narration else 'なし'}
- 音楽：{use_music}
- MA：{'あり' if ma_needed else 'なし'}
- 納品形式：{', '.join(deliverables) or 'なし'}
- 字幕言語：{', '.join(subtitle_langs) or 'なし'}
- 使用地域：{usage_region}
- 使用期間：{usage_period}
- 参考予算：{budget_hint or 'なし'}
- その他備考：{extra_notes or 'なし'}
"""

# ─── 6. Prompt B: 計算フェーズ ────────────────────────────────────
promptB = """
以下のリストアップされた各項目について「単価×数量」を正確に計算し、
「項目名：計算結果（円）」の一行ずつで出力してください。
出力前に、論理的矛盾や計算ミスがないか自己点検してから返答してください。

# ●ここに「項目出し結果」を貼り付けて下さい
"""

# ─── 7. Prompt C: 最終組み立てフェーズ ────────────────────────────
promptC_template = """
あなたは広告制作費のプロフェッショナルな見積もりエージェントです。
以下の2つの情報をもとに、HTML+Markdown形式で詳細な見積書を作成してください。

1) 項目出し結果:
{items_a}

2) 計算結果:
{items_b}

# 出力形式要件
- テーブルで「項目」「単価」「数量」「金額」を明記
- 合計金額は太字または色付きで強調
- 最終行に「合計金額（税抜）: ○○○○円」を表示
- 端数処理は行わず正確に足し算
- 金額は日本円単位で表示
- フォントは Arial を想定
- 正しい HTML 構造で出力してください
- 出力前に、論理的矛盾や抜け漏れ、計算ミスがないか自己点検してから返答してください。
"""

# ─── 8. 実行 ───────────────────────────────────────────────────
if st.button("💡 見積もりを作成"):
    with st.spinner("AIが見積もりを作成中…"):

        # ① Prompt A 実行
        if model_choice == "Gemini":
            resA = genai.GenerativeModel("gemini-2.0-flash").generate_content(promptA).text
        else:
            respA = openai_client.chat.completions.create(
                model="gpt-4o" if model_choice=="GPT-4o" else "gpt-4.1",
                messages=[{"role":"system","content":"あなたは見積もりアシスタントです。"},
                          {"role":"user","content":promptA}],
                temperature=0.7,
            )
            resA = respA.choices[0].message.content

        # ② Prompt B 実行
        fullB = promptB.replace(
            "# ●ここに「項目出し結果」を貼り付けて下さい",
            "\n" + resA + "\n"
        )
        if model_choice == "Gemini":
            resB = genai.GenerativeModel("gemini-2.0-flash").generate_content(fullB).text
        else:
            respB = openai_client.chat.completions.create(
                model="gpt-4o" if model_choice=="GPT-4o" else "gpt-4.1",
                messages=[{"role":"system","content":"あなたは計算アシスタントです。"},
                          {"role":"user","content":fullB}],
                temperature=0.7,
            )
            resB = respB.choices[0].message.content

        # ③ Prompt C 実行
        promptC = promptC_template.format(items_a=resA, items_b=resB)
        if model_choice == "Gemini":
            final = genai.GenerativeModel("gemini-2.0-flash").generate_content(promptC).text
        else:
            respC = openai_client.chat.completions.create(
                model="gpt-4o" if model_choice=="GPT-4o" else "gpt-4.1",
                messages=[{"role":"system","content":"あなたは見積もりアシスタントです。"},
                          {"role":"user","content":promptC}],
                temperature=0.7,
            )
            final = respC.choices[0].message.content

        # ④ 表示
        st.success("✅ 見積もり結果")
        st.components.v1.html(
            final,
            height=900,
            scrolling=True
        )
