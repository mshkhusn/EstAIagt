import streamlit as st
import google.generativeai as genai

# 🔐 APIキーをsecretsから読み込む（安全）
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=GEMINI_API_KEY)

st.set_page_config(page_title="バナー見積もりAI", layout="centered")
st.title(":art: 広告バナー見積もりAIエージェント (Gemini 2.0 Flash)")

# --- 入力フォーム ---
st.subheader("▶ バナーサイズごとの本数を入力してください")
banner_sizes = {
    "300×250（レクタングル）": st.number_input("300×250（レクタングル）", 0, 50, 1),
    "728×90（リーダーボード）": st.number_input("728×90（リーダーボード）", 0, 50, 1),
    "160×600（ワイドスカイスクレイパー）": st.number_input("160×600（ワイドスカイスクレイパー）", 0, 50, 1),
    "320×100（モバイル）": st.number_input("320×100（モバイル）", 0, 50, 1)
}

# 0本を除いた実際のサイズ情報
filtered_banner_sizes = {k: v for k, v in banner_sizes.items() if v > 0}
total_banners = sum(filtered_banner_sizes.values())
banner_summary = "、".join([f"{k}が{v}本" for k, v in filtered_banner_sizes.items()]) or "未入力"

st.markdown(f"**🧾 合計本数：{total_banners} 本**")

# \305dの情報
banner_type = st.selectbox("バナー種別", ["Static (静止画)", "Animated (GIF/APNG)", "Video"])
due_date = st.date_input("納品希望日")
media_platform = st.text_input("掲載予定メディアは？")
assets_provided = st.checkbox("素材支給あり")
need_copy = st.checkbox("キャッチコピー作成必要")
resize_count = st.number_input("リサイズ数量", 0, 10, 0)
design_reference = st.checkbox("トンマナ資料あり")
budget_hint = st.text_input("参考予算（任意）")

# --- Geminiへ依頼 ---
if st.button("💡 Geminiに見積もりを依頼"):
    with st.spinner("AIが見積もりを作成中..."):
        prompt = (
            f"あなたは広告制作費のプロフェッショナルです\n"
            f"以下条件で広告バナー制作の概算見積もりを提示してください\n\n"
            f"- バナーサイズ別：{banner_summary}\n"
            f"- 合計本数：{total_banners} 本\n"
            f"- 種別：{banner_type}\n"
            f"- 納品希望日：{due_date}\n"
            f"- 掲載メディア：{media_platform}\n"
            f"- 素材支給：{"あり" if assets_provided else "なし"}\n"
            f"- キャッチコピー：{"必要" if need_copy else "不要"}\n"
            f"- リサイズ数：{resize_count}\n"
            f"- トンマナ資料：{"あり" if design_reference else "なし"}\n"
            f"- 参考予算：{budget_hint or '未入力'}\n\n"
            f"費用項目ごとの内訳と概算金額（日本円）を提示してください"
        )

        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)
        st.success("✅ Geminiによる見積もり結果")
        st.text_area("出力内容", response.text, height=400)
