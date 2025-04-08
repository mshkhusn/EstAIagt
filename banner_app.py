import streamlit as st
import google.generativeai as genai

# APIキーの読み込み
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=GEMINI_API_KEY)

st.set_page_config(page_title="バナー見積もりAI", layout="centered")
st.title("バナー見積もりAIエージェント（Gemini 2.0 Flash）")

# --- スタイル設定 ---
st.markdown("""
<style>
.small-label { font-size: 0.9rem; font-weight: 500; margin-bottom: -6px; }
</style>
""", unsafe_allow_html=True)

# --- バナー情報入力 ---
st.markdown("### バナータイプ・サイズ・本数の入力")
st.markdown("#### <span class='small-label'>入力するバナーの組み合わせ数</span>", unsafe_allow_html=True)
row_count = st.number_input("", min_value=1, max_value=10, value=3, step=1)

# バナータイプとサイズの辞書
banner_types = {
    "静止画": ["300x250", "728x90", "160x600", "その他"],
    "アニメーション": ["300x250", "468x60", "320x100", "その他"],
    "動画": ["16:9（横型）", "9:16（縦型）", "1:1（正方形）", "その他"]
}

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
            qty = st.number_input(f"本数 #{i+1}", min_value=0, max_value=50, value=1, key=f"qty_{i}")

        if qty > 0:
            banner_rows.append({"type": banner_type, "size": size, "qty": qty})
            total_count += qty

st.markdown(f"**合計本数：{total_count} 本**")

# --- 制作情報入力 ---
st.markdown("### 制作情報の入力")
due_date = st.date_input("納品希望日")
media = st.text_input("掲載媒体（例：Yahoo!、Google、SNS など）")
assigned_roles = st.multiselect("必要なスタッフ", ["デザイナー", "コピーライター", "アニメーター", "動画編集者", "ディレクター"])
need_copywriting = st.checkbox("キャッチコピー・コピーライティングあり")
need_translation = st.checkbox("翻訳・多言語対応あり")
resolution = st.selectbox("解像度の希望", ["通常（72dpi）", "高解像度（150dpi 以上）", "未定"])
design_level = st.selectbox("デザインのクオリティ感", ["シンプル", "標準", "リッチ"])
assets_provided = st.checkbox("素材支給あり")
resize_count = st.number_input("リサイズパターン数（異なるサイズへの展開）", 0, 10, 0)
design_reference = st.checkbox("トンマナ参考資料あり")
budget_hint = st.text_input("参考予算（任意）")

# --- Gemini で見積もり生成 ---
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

--- 出力フォーマットの指示 ---
・見出し、内訳、合計などをマークダウンで整えてください
・テーブル形式で「項目」「単価」「数量」「小計」「備考」などを表示してください
・不要な空白や改行は避け、コンパクトで見やすく整えてください
・合計金額には強調表示を入れてください
"""

        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)

        # --- 改行などの調整 ---
        formatted_text = response.text.strip()
        while "\n\n\n" in formatted_text:
            formatted_text = formatted_text.replace("\n\n\n", "\n\n")

        # --- 出力表示 ---
        st.success("📊 Geminiによる見積もり結果")
        st.markdown(formatted_text, unsafe_allow_html=True)
