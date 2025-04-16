import streamlit as st
import google.generativeai as genai

# 🔐 secrets に登録された APIキーを読み込み
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=GEMINI_API_KEY)

st.set_page_config(page_title="WebCM見積もりAI", layout="centered")
st.title("WebCM 見積もりAIエージェント（Gemini 2.0 Flash）")

# --- 入力フォーム ---
video_duration = st.selectbox("尺の長さ", ["15秒", "30秒", "60秒", "その他"])

# 「その他」が選ばれた場合、自由入力フィールドを表示
if video_duration == "その他":
    video_duration_custom = st.text_input("尺の長さ（自由記入）を入力してください")
    final_duration = video_duration_custom or "未入力"
else:
    final_duration = video_duration

num_versions = st.number_input("納品本数", 1, 10, 1)
shoot_days = st.number_input("撮影日数", 1, 10, 2)
edit_days = st.number_input("編集日数", 1, 10, 3)
delivery_date = st.date_input("納品希望日")
cast_main = st.number_input("メインキャスト人数", 0, 10, 1)
cast_extra = st.number_input("エキストラ人数", 0, 20, 3)
talent_use = st.checkbox("タレント起用あり")
staff_roles = st.multiselect("必要なスタッフ", ["制作プロデューサー", "制作プロジェクトマネージャー", "ディレクター", "カメラマン", "照明スタッフ", "スタイリスト", "ヘアメイク", "アシスタント"])
shoot_location = st.text_input("撮影場所（例：都内スタジオ＋ロケ）")
kizai = st.multiselect("撮影機材", ["4Kカメラ", "照明", "ドローン", "グリーンバック"])
set_design_quality = st.selectbox(
    "セット建て・美術装飾の規模", 
    ["なし", "小（簡易装飾）", "中（通常レベル）", "大（本格セット）"]
)
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

# --- 出力実行 ---
if st.button("💡 Geminiに見積もりを依頼"):
    with st.spinner("AIが見積もりを作成中です..."):
        prompt = f"""
あなたは広告制作費のプロフェッショナルな見積もりエージェントです。
以下の条件に基づいて、WebCM制作に必要な費用を詳細に見積もってください。
予算、納期、仕様、スタッフ構成、撮影条件などから、実務に即した内容で正確かつ論理的に推論してください。
短納期である場合や仕様が複雑な場合には、工数や費用が増える点も加味してください。

---
【WebCM見積もり条件】
- 尺：{final_duration}
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
- セット建て・美術装飾：{set_design_quality}
- CG・VFX：{'あり' if use_cg else 'なし'}
- ナレーション：{'あり' if use_narration else 'なし'}
- 音楽：{use_music}
- MA：{'あり' if ma_needed else 'なし'}
- 納品形式：{', '.join(deliverables) if deliverables else '未定'}
- 字幕言語：{', '.join(subtitle_langs) if subtitle_langs else '未定'}
- 使用地域：{usage_region}
- 使用期間：{usage_period}
- 参考予算：{budget_hint or 'なし'}
- その他備考：{extra_notes or 'なし'}

---
# 出力形式要件
- HTML + Markdown形式で読みやすく出力
- 見積もり表は「項目名・詳細・単価・数量・金額（日本円）」のテーブルで出力
- 合計金額は太字または色付きで強調
- 備考や注意点も記載
- フォントはArialを想定
- 正しいHTML構造で出力してください

# 見積もり出力における注意点
- 各項目の「単価 × 数量 = 金額」を正確に計算してください。
- 最後に全項目の金額を合算し、正確な合計金額（税抜）を表示してください。
- 合計金額には端数処理（円未満切り捨て／四捨五入）は行わず、正確に足し算してください。
- 金額は必ず日本円（円単位）で表示してください。
- 合計金額は見やすく太字または色付きで強調してください。
- 各項目の計算と合計の再確認を行い、金額の整合性が取れていることをチェックした上で出力してください。
"""

        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)
        html_output = response.text

        st.success("✅ Geminiによる見積もり結果（※崩れる場合は再実行してください）")
        st.components.v1.html(
            f"""
            <div style="font-family: 'Arial', sans-serif; font-size: 15px; line-height: 1.6; padding: 10px;">
                {html_output}
            </div>
            """,
            height=1200,
            scrolling=True
        )
