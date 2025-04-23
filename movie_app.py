import streamlit as st
import google.generativeai as genai
from openai import OpenAI

# --- 認証・設定 ---
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
APP_PASSWORD = st.secrets["APP_PASSWORD"]
# Gemini 設定
genai.configure(api_key=GEMINI_API_KEY)
# GPT-4o クライアント設定
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# --- パスワード認証 ---
st.set_page_config(page_title="映像制作AIエージェント", layout="centered")
password_input = st.text_input("パスワードを入力してください", type="password")
if password_input != APP_PASSWORD:
    st.warning("認証が必要です。正しいパスワードを入力してください。")
    st.stop()

st.title("映像制作AIエージェント（Gemini / GPT-4o 切替対応版）")

# --- 入力フォーム ---
st.header("制作条件の入力")
video_duration = st.selectbox("尺の長さ", ["15秒", "30秒", "60秒", "その他"])
final_duration = st.text_input("尺の長さ（自由記入）を入力してください") if video_duration == "その他" else video_duration
num_versions = st.number_input("納品本数", 1, 10, 1)
shoot_days = st.number_input("撮影日数", 1, 10, 2)
edit_days = st.number_input("編集日数", 1, 10, 3)
delivery_date = st.date_input("納品希望日")
cast_main = st.number_input("メインキャスト人数", 0, 10, 1)
cast_extra = st.number_input("エキストラ人数", 0, 20, 3)
talent_use = st.checkbox("タレント起用あり")
staff_roles = st.multiselect("必要なスタッフ", [
    "制作プロデューサー", "制作プロジェクトマネージャー", "ディレクター",
    "カメラマン", "照明スタッフ", "スタイリスト", "ヘアメイク", "アシスタント"
])
shoot_location = st.text_input("撮影場所（例：都内スタジオ＋ロケ）")
kizai = st.multiselect("撮影機材", ["4Kカメラ", "照明", "ドローン", "グリーンバック"])
set_design_quality = st.selectbox("セット建て・美術装飾の規模", ["なし", "小（簡易装飾）", "中（通常レベル）", "大（本格セット）"])
use_cg = st.checkbox("CG・VFXあり")
use_narration = st.checkbox("ナレーション収録あり")
use_music = st.selectbox("音楽素材", ["既存ライセンス音源", "オリジナル制作", "未定"])
ma_needed = st.checkbox("MAあり")
deliverables = st.multiselect("納品形式", ["mp4（16:9）", "mp4（1:1）", "mp4（9:16）", "ProRes"])
subtitle_langs = st.multiselect("字幕言語", ["日本語", "英語", "その他"])
usage_region = st.selectbox("使用地域", ["日本国内", "グローバル", "未定"])
usage_period = st.selectbox("使用期間", ["6ヶ月", "1年", "2年", "無期限", "未定"])
budget_hint = st.text_input("参考予算（任意）")
extra_notes = st.text_area("その他備考（任意）")
model_choice = st.selectbox("使用するAIモデル", ["Gemini", "GPT-4o"])

# --- プロンプト生成 ---
prompt = f"""
あなたは広告制作費のプロフェッショナルな見積もりエージェントです。
以下の条件に基づいて、映像制作に必要な費用を詳細に見積もってください。
予算、納期、仕様、スタッフ構成、撮影条件などから、実務に即した内容で正確かつ論理的に推論してください。
短納期や複雑仕様の場合、工数・費用が増える点も考慮してください。

---
【映像制作見積もり条件】
- 尺：{final_duration}
- 納品本数：{num_versions}本
- 撮影日数：{shoot_days}日
- 編集日数：{edit_days}日
- 納品希望日：{delivery_date}
- メインキャスト人数：{cast_main}人
- エキストラ人数：{cast_extra}人
- タレント：{'あり' if talent_use else 'なし'}
- 必要スタッフ：{', '.join(staff_roles) if staff_roles else '未指定'}
- 撮影場所：{shoot_location or '未指定'}
- 撮影機材：{', '.join(kizai) if kizai else 'なし'}
- セット建て・美術装飾：{set_design_quality}
- CG・VFX：{'あり' if use_cg else 'なし'}
- ナレーション：{'あり' if use_narration else 'なし'}
- 音楽：{use_music}
- MA：{'あり' if ma_needed else 'なし'}
- 納品形式：{', '.join(deliverables) if deliverables else '未指定'}
- 字幕言語：{', '.join(subtitle_langs) if subtitle_langs else '未指定'}
- 使用地域：{usage_region}
- 使用期間：{usage_period}
- 参考予算：{budget_hint or 'なし'}
- その他備考：{extra_notes or 'なし'}

---
# 出力形式要件
- HTML + Markdown形式で読みやすく出力
- 見積もり表は「項目名・詳細・単価・数量・金額（日本円）」のテーブルで出力
- 合計金額は太字や色付きで強調
- 備考や注意点を記載
- フォントはArial想定
- 正しいHTML構造で出力

# 注意点
- 各項目の「単価 × 数量 = 金額」を正確に計算
- 全項目の金額を合算し、正確な合計金額（税抜）を表示
- 端数処理なしで正しく足し算
- 日本円（円単位）で表示
- 合計金額を太字や色付きで見やすく強調
- 計算と合計を再チェックし、金額の整合性を保証
"""

# --- モデル実行 ---
if st.button("💡 見積もりを作成"):
    with st.spinner("AIが見積もりを作成中です..."):
        if model_choice == "Gemini":
            model = genai.GenerativeModel("gemini-2.0-flash")
            response = model.generate_content(prompt)
            result = response.text
        else:
            response = openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "あなたは広告映像の見積もりアシスタントです。"},
                    {"role": "user", "content": prompt}
                ]
            )
            result = response.choices[0].message.content

        st.success("✅ 見積もり結果")
        st.components.v1.html(
            f"""
            <div style='font-family: Arial, sans-serif; font-size:15px; line-height:1.6; padding:10px;'>
                {result}
            </div>
            """,
            height=1200,
            scrolling=True
        )
