
import streamlit as st
import google.generativeai as genai

# 🔐 APIキーをsecretsから読み込む（安全）
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=GEMINI_API_KEY)

st.set_page_config(page_title="バナー見積もりAI", layout="centered")
st.title("広告バナー見積もりAIエージェント（Gemini 2.0 Flash）")

# --- 入力フォーム ---
banner_size = st.selectbox("バナーサイズ", ["300×250", "728×90", "160×600", "Instagramストーリーズ", "X（旧Twitter）プロモ", "その他"])
banner_count = st.number_input("納品本数", 1, 20, 1)
banner_type = st.selectbox("バナー種別", ["静止画バナー", "アニメーションバナー（GIF/APNG）", "動画バナー"])
due_date = st.date_input("納品希望日")
media_platform = st.text_input("掲載予定媒体（例：Google Display / Instagramなど）")
assets_provided = st.checkbox("素材（画像・ロゴ・文言など）支給あり")
need_copy = st.checkbox("キャッチコピー作成が必要")
resize_count = st.number_input("リサイズパターン数（派生サイズ）", 0, 10, 0)
design_reference = st.checkbox("トンマナ資料あり")
budget_hint = st.text_input("参考予算（任意）")

# --- Geminiへ依頼ボタン ---
if st.button("💡 Geminiに見積もりを依頼"):
    with st.spinner("AIが見積もりを作成中です..."):
        prompt = (
            f"あなたは広告制作費のプロフェッショナルです。\n"
            f"以下条件で広告バナー制作の概算見積もりを提示してください。\n\n"
            f"- サイズ：{banner_size}\n"
            f"- 本数：{banner_count}本\n"
            f"- 種別：{banner_type}\n"
            f"- 納品希望日：{due_date}\n"
            f"- 掲載媒体：{media_platform}\n"
            f"- 素材支給：{'あり' if assets_provided else 'なし'}\n"
            f"- コピー作成：{'あり' if need_copy else 'なし'}\n"
            f"- リサイズ：{resize_count}パターン\n"
            f"- トンマナ資料：{'あり' if design_reference else 'なし'}\n"
            f"- 参考予算：{budget_hint or '未記入'}\n\n"
            f"費用項目ごとの内訳と概算金額（日本円）を提示してください。"
        )

        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)
        st.success("✅ Geminiによる見積もり結果")
        st.text_area("出力内容", response.text, height=400)
