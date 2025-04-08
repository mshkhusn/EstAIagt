import streamlit as st
import google.generativeai as genai

# 🔐 secrets に登録された APIキーを読み込み
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=GEMINI_API_KEY)

st.set_page_config(page_title="WebCM見積もりAI", layout="centered")
st.title("WebCM 見積もりAIエージェント（Gemini 2.0 Flash）")

# --- 入力フォーム ---
video_duration = st.selectbox("尺の長さ", ["15秒", "30秒", "60秒", "その他"])
num_versions = st.number_input("納品本数", 1, 10, 1)
shoot_days = st.number_input("撮影日数", 1, 10, 2)
edit_days = st.number_input("編集日数", 1, 10, 3)
delivery_date = st.date_input("納品希望日")
cast_main = st.number_input("メインキャスト人数", 0, 10, 1)
cast_extra = st.number_input("エキストラ人数", 0, 20, 3)
talent_use = st.checkbox("タレント起用あり")
staff_roles = st.multiselect("必要なスタッフ", ["ディレクター", "カメラ", "照明", "スタイリスト", "ヘアメイク", "アシスタント"])
shoot_location = st.text_input("撮影場所（例：都内スタジオ＋ロケ）")
kizai = st.multiselect("撮影機材", ["4Kカメラ", "照明", "ドローン", "グリーンバック"])
set_design = st.checkbox("セット建て・美術装飾あり")
use_cg = st.checkbox("CG・VFXあり")
use_narration = st.checkbox("ナレーション収録あり")
use_music = st.selectbox("音楽素材", ["既存ライセンス音源", "オリジナル制作", "未定"])
ma_needed = st.checkbox("MAあり")
deliverables = st.multiselect("納品形式", ["mp4（16:9）", "mp4（1:1）", "mp4（9:16）", "ProRes"])
subtitle_langs = st.multiselect("字幕言語", ["日本語", "英語", "その他"])
usage_region = st.selectbox("使用地域", ["日本国内", "グローバル", "未定"])
usage_period = st.selectbox("使用期間", ["6ヶ月", "1年", "2年", "無期限", "未定"])
budget_hint = st.text_input("参考予算（任意）")

# --- 出力実行 ---
if st.button("💡 Geminiに見積もりを依頼"):
    with st.spinner("AIが見積もりを作成中です..."):
        prompt = f"""
あなたは広告制作のプロフェッショナルです。以下条件でWebCM見積もりをHTML形式で提示してください。

【WebCM見積もり】

■ 条件
- 尺：{video_duration}
- 納品本数：{num_versions}本
- 撮影日数：{shoot_days}日
- 編集日数：{edit_days}日
- 納品希望日：{delivery_date}
- メインキャスト人数：{cast_main}人
- エキストラ人数：{cast_extra}人
- タレント：{'あり' if talent_use else 'なし'}
- 必要スタッフ：{', '.join(staff_roles) if staff_roles else '未入力'}
- 撮影場所：{shoot_location or '未入力'}
- 撮影機材：{', '.join(kizai) if kizai else 'なし'}
- セット建て：{'あり' if set_design else 'なし'}
- CG・VFX：{'あり' if use_cg else 'なし'}
- ナレーション：{'あり' if use_narration else 'なし'}
- 音楽：{use_music}
- MA：{'あり' if ma_needed else 'なし'}
- 納品形式：{', '.join(deliverables) if deliverables else '未定'}
- 字幕言語：{', '.join(subtitle_langs) if subtitle_langs else '未定'}
- 使用地域：{usage_region}
- 使用期間：{usage_period}
- 参考予算：{budget_hint or 'なし'}

■ 出力形式
- HTML形式で整形して出力してください
- 費用の内訳を「項目名・詳細・単価・数量・金額（日本円）」の表形式で整理してください
- 合計金額はわかりやすく強調してください（例：太字または色付き）
- 「備考」や「注意事項」も記載してください（見積金額は概算である旨も明記）
- フォントは可読性の高いもの（例：Arial）を想定し、表示が崩れないように
"""

        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)
        html_output = response.text

        st.success("✅ Geminiによる見積もり結果")
        st.components.v1.html(
            f"""
            <div style="font-family: 'Arial', sans-serif; font-size: 15px; line-height: 1.6; padding: 10px;">
                {html_output}
            </div>
            """,
            height=1000,
            scrolling=True
        )
