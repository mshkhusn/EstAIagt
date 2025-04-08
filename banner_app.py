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
あなたは広告制作に精通したプロフェッショナルな見積もりエージェントです。

以下の条件に基づき、必要な制作工程を洗い出し、各項目の内訳と概算費用（日本円）を詳細に見積もってください。

特に以下の点に注意して推論してください：
- 制作物の種類に応じて必要なタスク・専門人材・外注費を適切に反映すること
- 短納期の場合は「特急対応費」「追加人員費」「休日稼働費」などを加味して算出すること
- コピーライティング・翻訳・アニメーション・リサイズパターン数・参考資料有無によって作業ボリュームが変化することを明示的に加味すること
- 使用用途（Web / SNS / 広告出稿など）や使用地域・期間に応じたライセンスや転用費用を考慮すること
- 素材支給の有無が作業工数に与える影響を考慮すること
- 類似実績のある業界価格を参考に、現実的な相場で出力すること

---
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

---
【出力形式要件】
- HTML + Markdown を用いて視認性を高めてください
- 費用表は「項目名」「詳細」「単価」「数量」「金額（日本円）」の形式で表にしてください
- 合計金額は太字または色付きで強調してください
- 補足や備考・注意事項も明記してください（例：「本見積もりは概算であり、要件確定後に調整される可能性があります」）
- フォントは Arial を想定し、読みやすさを重視してください
- 正しいHTML構造で出力してください
        """

        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)

        html_output = response.text

        st.success("📊 Geminiによる見積もり結果（※表示が崩れる場合は再実行してください）")
        st.components.v1.html(
            f"""
            <div style="font-family: 'Arial', sans-serif; font-size: 15px; line-height: 1.6; padding: 10px;">
                {html_output}
            </div>
            """,
            height=1200,
            scrolling=True
        )
