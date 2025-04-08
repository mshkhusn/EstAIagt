import streamlit as st
import google.generativeai as genai
import requests
from bs4 import BeautifulSoup

# APIキーの設定
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=GEMINI_API_KEY)

st.set_page_config(page_title="LP見積もりAI", layout="centered")
st.title("🖥️ LP見積もりAIエージェント（Gemini 2.5 Pro）")

st.markdown("""
<style>
.section-label { font-size: 0.9rem; font-weight: 600; margin-top: 1rem; }
</style>
""", unsafe_allow_html=True)

st.markdown("<div class='section-label'>🔢 基本情報の入力</div>", unsafe_allow_html=True)
page_goal = st.selectbox("LPの目的", ["商品訴求", "キャンペーン訴求", "リード獲得", "採用", "ブランディング", "その他"])
page_length = st.selectbox("ページ構成の長さ（目安）", ["1ページ完結（短め）", "1ページ完結（長め）", "複数セクション構成", "5ページ以上の構成"])
responsive = st.checkbox("レスポンシブ対応（スマホ・PC対応）", value=True)
form_included = st.checkbox("問い合わせ・応募フォームあり")
tag_tracking = st.checkbox("トラッキングタグ設置あり")
anime_effects = st.checkbox("アニメーション・インタラクションあり")
media_type = st.multiselect("使用する素材（複数選択可）", ["写真", "イラスト", "動画", "図解"], default=["写真"])

st.markdown("<div class='section-label'>🛠️ 制作オプション</div>", unsafe_allow_html=True)
assets_provided = st.checkbox("テキスト・素材などは全て支給済み")
design_quality = st.selectbox("デザイン品質の希望", ["シンプル", "標準", "リッチ", "参考LPレベル"])
budget_hint = st.text_input("参考予算（任意）")

st.markdown("<div class='section-label'>🔗 参考サイト</div>", unsafe_allow_html=True)
reference_url = st.text_input("参考URL（任意）", placeholder="https://example.com")
if reference_url:
    st.caption("※ 参考URLの解析には時間がかかります。出力までしばらくお待ちください。")

# --- プロンプト生成関数 ---
def generate_prompt():
    url_analysis = ""
    if reference_url:
        try:
            response = requests.get(reference_url, timeout=10)
            soup = BeautifulSoup(response.text, "html.parser")
            visible_text = soup.get_text(separator=" ", strip=True)[:2000]  # 最初の2000文字
            url_analysis = f"\n\n【参考LPの内容（自動取得）】：\n{visible_text}"
        except Exception as e:
            url_analysis = f"\n\n【参考LPの取得に失敗しました】：{e}"

    return f"""
あなたは広告制作費のプロフェッショナルです。
以下の条件に基づき、LP制作費の概算見積もりを作成してください。

【目的】：{page_goal}
【ページ構成】：{page_length}
【レスポンシブ対応】：{'あり' if responsive else 'なし'}
【フォーム】：{'あり' if form_included else 'なし'}
【トラッキング】：{'あり' if tag_tracking else 'なし'}
【アニメーション】：{'あり' if anime_effects else 'なし'}
【素材】：{', '.join(media_type) if media_type else '未定'}
【素材支給】：{'あり' if assets_provided else 'なし'}
【デザイン品質】：{design_quality}
【予算】：{budget_hint or 'なし'}{url_analysis}

要件の複雑性・表現の高度さ・品質要件・業界特性などを加味して、
調査・推論を行った上で下記のように記述してください：

1. 想定される制作難易度と背景の示唆（推論コメント）
2. 概算の費用内訳を表形式で提示（項目ごとの金額、合計金額）
3. 注釈として、前提条件や留意点があれば明記

出力は、視認性の高いHTML（太字・テーブル・区切り線・注意事項など）で出力してください。
"""

# --- 出力処理 ---
if st.button("💡 Geminiに見積もりを依頼"):
    with st.spinner("AIが深く解析して見積もりを作成中です..."):
        prompt = generate_prompt()
        model = genai.GenerativeModel("gemini-2.5-pro-exp-03-25")
        response = model.generate_content(prompt)
        html_output = response.text

        st.success("✅ Geminiによる見積もり結果")
        st.components.v1.html(f"""
        <div style='font-family: "Arial", sans-serif; font-size: 15px; line-height: 1.6; padding: 10px;'>
        {html_output}
        </div>
        """, height=1000, scrolling=True)
