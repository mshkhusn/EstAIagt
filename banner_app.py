import streamlit as st
import google.generativeai as genai

# APIキーの読み込み
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=GEMINI_API_KEY)

st.set_page_config(page_title="バナー見積もりAI", layout="centered")
st.title("バナー見積もりAIエージェント（Gemini Flash）")

st.markdown("""
<style>
.small-label { font-size: 0.9rem; font-weight: 500; margin-bottom: 4px; }
</style>
""", unsafe_allow_html=True)

st.markdown("##バナータイプ・サイズ・本数の入力")

# 定義：バナータイプと対応サイズ
banner_types = {
    "静止画": ["300x250", "728x90", "160x600", "その他"],
    "アニメーション": ["300x250", "468x60", "320x100", "その他"],
    "動画": ["16:9（横型）", "9:16（縦型）", "1:1（正方形）", "その他"]
}

# 入力行数を選択
st.markdown("#### "+"<span class='small-label'>入力するバナーの組み合わせ数</span>", unsafe_allow_html=True)
row_count = st.number_input("", min_value=1, max_value=10, value=3, step=1)

banner_rows = []
total_count = 0

for i in range(int(row_count)):
    with st.container():
        cols = st.columns([2, 3, 2])
        with cols[0]:
            banner_type = st.selectbox(f"タイプ #{i+1}", list(banner_types.keys()), key=f"type_{i}")
        with cols[1]:
            size = st.selectbox(f"サイズ #{i+1}", banner_types[banner_type], key=f"size_{i}")
        with cols[2]:
            qty = st.number_input(f"本数 #{i+1}", min_value=0, max_value=50, value=1, step=1, key=f"qty_{i}")

        if qty > 0:
            banner_rows.append({"type": banner_type, "size": size, "qty": qty})
            total_count += qty

st.markdown(f"**合計本数：{total_count} 本**")

st.markdown("##制作情報の入力")
due_date = st.date_input("納品希望日")
media = st.text_input("掲載媒体（例：Yahoo!、Google、SNS など）")
assigned_roles = st.multiselect("必要なスタッフ", ["デザイナー", "コピーライター", "アニメーター", "動画編集者", "ディレクター"])
need_copywriting = st.checkbox("キャッチコピー・コピーライティングあり")
need_translation = st.checkbox("翻訳・多言語対応あり")
resolution = st.selectbox("解像度の希望", ["通常（72dpi）", "高解像度（150dpi 以上）", "未定"])
design_level = st.selectbox("デザインのクオリティ感", ["シンプル", "標準", "リッチ"])
budget_hint = st.text_input("参考予算（任意）")
assets_provided = st.checkbox("素材支給あり")
resize_count = st.number_input("リサイズパターン数（異なるサイズへの展開）", 0, 10, 0)
design_reference = st.checkbox("トンマナ参考資料あり")

# --- Gemini Flash による見積もり生成 ---
if st.button("💡 Geminiに見積もりを依頼"):
    with st.spinner("AIが見積もりを作成中です..."):
        size_details = "\n".join([f"- {row['type']}：{row['size']} × {row['qty']}本" for row in banner_rows])
        prompt = f"""
あなたは広告制作費のプロフェッショナルです。
以下の条件に基づいて、バナー広告の制作にかかる見積もりを作成してください。

【バナーの内訳】
{size_details}

【納品希望日】：{due_date}
【媒体】：{media or '未入力'}
【必要スタッフ】：{', '.join(assigned_roles) or '未指定'}
【コピーライティング】：{'あり' if need_copywriting else 'なし'}
【翻訳対応】：{'あり' if need_translation else 'なし'}
【解像度】：{resolution}
【デザインクオリティ】：{design_level}
【素材支給】：{'あり' if assets_provided else 'なし'}
【リサイズパターン】：{resize_count}種
【トンマナ資料】：{'あり' if design_reference else 'なし'}
【参考予算】：{budget_hint or 'なし'}

項目ごとに内訳を示し、日本円で概算金額を記載してください。
"""
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)
        st.success("📊 Geminiによる見積もり結果")
        st.text_area("📋 出力内容", response.text, height=400)
