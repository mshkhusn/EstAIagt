import streamlit as st
import google.generativeai as genai

# 🔐 APIキーをsecretsから読み込む
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=GEMINI_API_KEY)

st.set_page_config(page_title="バナー見積もりAI", layout="centered")
st.title("🧠 バナー見積もりAIエージェント（Gemini Flash）")

st.markdown("### ✏⃣ バナータイプの選択")
banner_type = st.radio("バナータイプを選んでください", ["Static（静止画）", "Animated（GIF/APNG）", "Video（動画）"])

# 各バナータイプに応じたサイズを定義
size_options = {
    "Static（静止画）": ["300x250", "728x90", "160x600", "その他"],
    "Animated（GIF/APNG）": ["300x250", "468x60", "320x100", "その他"],
    "Video（動画）": ["16:9（横型）", "9:16（縦型）", "1:1（正方形）", "その他"]
}

selected_sizes = st.multiselect("制作するサイズを選択", size_options[banner_type])

# 選択されたサイズごとに本数入力欄
st.markdown("### ✏⃣ 本数の指定（各サイズごと）")
quantities = {}
for size in selected_sizes:
    quantities[size] = st.number_input(f"{size} の本数", min_value=0, max_value=20, value=1, step=1)

# 合計本数（0本は除外）
total_count = sum([q for q in quantities.values() if q > 0])
st.markdown(f"**合計本数：{total_count} 本**")

st.markdown("### ✏⃣ 制作情報の入力")
due_date = st.date_input("納品希望日")
media = st.text_input("掲載媒体（例：Yahoo!、Google、SNS など）")
assigned_roles = st.multiselect("必要なスタッフ", ["デザイナー", "アニメーター", "動画編集者", "ディレクター"])
need_copywriting = st.checkbox("キャッチコピー・コピーライティングあり")
need_translation = st.checkbox("翻訳・多言語対応あり")
resolution = st.selectbox("解像度の希望", ["通常（72dpi）", "高解像度（150dpi 以上）", "未定"])
design_level = st.selectbox("デザインのクオリティ感", ["シンプル", "標準", "リッチ"])
budget_hint = st.text_input("参考予算（任意）")

# --- Gemini Flash による見積もり生成 ---
if st.button("💡 Geminiに見積もりを依頼"):
    with st.spinner("AIが見積もりを作成中です..."):
        size_details = "\n".join([f"- {size}: {qty}本" for size, qty in quantities.items() if qty > 0])
        prompt = f"""
あなたは広告制作費のプロフェッショナルです。
以下の条件に基づいて、バナー広告の制作にかかる見積もりを作成してください。

【バナータイプ】：{banner_type}
【サイズ・本数】：\n{size_details}
【納品希望日】：{due_date}
【媒体】：{media or '未入力'}
【必要スタッフ】：{', '.join(assigned_roles) or '未指定'}
【コピーライティング】：{'あり' if need_copywriting else 'なし'}
【翻訳対応】：{'あり' if need_translation else 'なし'}
【解像度】：{resolution}
【デザインクオリティ】：{design_level}
【参考予算】：{budget_hint or 'なし'}

項目ごとに内訳を示し、日本円で概算金額を記載してください。
"""
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)
        st.success("📈 Geminiによる見積もり結果")
        st.text_area("📊 出力内容", response.text, height=400)
