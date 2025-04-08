import streamlit as st
import google.generativeai as genai

# APIキーをsecretsから読み込み
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=GEMINI_API_KEY)

st.set_page_config(page_title="バナー見積もりAI", layout="centered")
st.title("バナー広告 見積もりAIエージェント（Gemini 2.0 Flash）")

# バナーサイズの選択
st.subheader("バナーサイズと本数の選択")
banner_sizes_all = ["120x600", "160x600", "300x250", "336x280", "728x90", "970x250", "その他"]
selected_sizes = st.multiselect("必要なバナーサイズを選択してください：", banner_sizes_all)

# 選択したサイズに対して本数を入力
size_quantity = {}
for size in selected_sizes:
    qty = st.number_input(f"{size} の本数", min_value=1, max_value=50, step=1, key=f"qty_{size}")
    size_quantity[size] = qty

total_banners = sum(size_quantity.values())
if total_banners:
    st.info(f"\n\n### ✅ 合計本数：{total_banners} 本")

# その他の制作情報
st.subheader("制作情報の入力")
banner_type = st.selectbox("バナー種別", ["Static（静止画）", "Animated（GIF/APNG）", "Video"])
due_date = st.date_input("納品希望日")
media = st.text_input("想定メディア・掲載先（任意）")
assistant_needed = st.checkbox("バナーごとにデザインアシスタントが必要")
need_responsive = st.checkbox("レスポンシブ対応が必要")
resolution = st.selectbox("解像度", ["72dpi（Web標準）", "150dpi", "300dpi"], index=0)
design_direction = st.text_area("デザインの方向性・備考（任意）")
budget_hint = st.text_input("参考予算（任意）")

# --- プロンプト生成と出力 ---
if st.button("💡 Geminiに見積もりを依頼"):
    with st.spinner("AIが見積もりを作成中です..."):
        banner_lines = "\n".join([f"- {k}：{v}本" for k, v in size_quantity.items()])
        prompt = f"""
あなたは広告制作費のプロフェッショナルです。以下条件でバナー広告の制作見積もりを提示してください：

{banner_lines}

- 種別：{banner_type}
- 合計：{total_banners}本
- 納品希望日：{due_date}
- 掲載媒体：{media or '未定'}
- デザインアシスタント：{'必要' if assistant_needed else '不要'}
- レスポンシブ対応：{'必要' if need_responsive else '不要'}
- 解像度：{resolution}
- デザイン要望：{design_direction or '特になし'}
- 参考予算：{budget_hint or '未記入'}

費用項目ごとの内訳と概算金額（日本円）を提示してください。
"""

        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)

        st.success("✅ Geminiによる見積もり結果")
        st.text_area("出力内容", response.text, height=400)
