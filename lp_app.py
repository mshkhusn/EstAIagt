import streamlit as st
import google.generativeai as genai
import requests
from bs4 import BeautifulSoup

# APIキーの読み込み
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=GEMINI_API_KEY)

st.set_page_config(page_title="LP見積もりAI", layout="centered")
st.title("📄 LP見積もりAIエージェント（Gemini 2.5 Pro）")

st.markdown("""
<style>
.small-label { font-size: 0.9rem; font-weight: 500; margin-bottom: 4px; }
</style>
""", unsafe_allow_html=True)

# --- 入力フォーム ---
st.markdown("### 基本情報")
lp_type = st.selectbox("LPの目的", ["キャンペーン訴求", "商品紹介", "資料請求/申込", "ブランディング", "その他"])
page_count = st.number_input("想定ページ数", min_value=1, max_value=20, value=3)
responsive = st.checkbox("レスポンシブ対応あり", value=True)
has_form = st.checkbox("フォーム実装あり")
has_tracking = st.checkbox("GA/広告トラッキングタグ設置あり")
has_animation = st.checkbox("アニメーション実装あり")
content_ready = st.selectbox("原稿・素材の支給状況", ["すべて支給あり", "一部支給・一部制作", "全てこちらで制作"])
design_quality = st.selectbox("デザインクオリティの希望", ["シンプル", "一般的", "リッチ"])
budget_hint = st.text_input("参考予算（任意）")

# --- 参考URL ---
st.markdown("### 参考LPサイト")
ref_url = st.text_input("参考サイトURL（任意）", placeholder="https://...")
if ref_url:
    st.caption("⏳ 参考URLの解析には時間がかかります。出力までしばらくお待ちください。")

# --- Gemini 2.5 Proで出力 ---
if st.button("💡 Geminiに見積もりを依頼"):
    with st.spinner("AIが見積もりを作成中です..."):

        site_summary = ""
        if ref_url:
            try:
                res = requests.get(ref_url, timeout=10)
                soup = BeautifulSoup(res.text, "html.parser")
                text_elements = soup.stripped_strings
                visible_text = " ".join(text_elements)
                site_summary = f"\n【参考LPから読み取れる特徴】：{visible_text[:1000]}..."  # 長すぎる場合カット
            except Exception as e:
                site_summary = f"\n【参考LPの解析エラー】：{str(e)}"

        prompt = f"""
あなたはLP制作に精通した見積もりのプロです。
以下の条件に基づいて、LP制作費用の見積もりをHTML形式で提示してください。

【LPの目的】：{lp_type}
【ページ数】：{page_count}ページ
【レスポンシブ対応】：{'あり' if responsive else 'なし'}
【フォーム実装】：{'あり' if has_form else 'なし'}
【タグ設置】：{'あり' if has_tracking else 'なし'}
【アニメーション】：{'あり' if has_animation else 'なし'}
【原稿・素材】：{content_ready}
【デザイン品質】：{design_quality}
【参考予算】：{budget_hint or 'なし'}
{site_summary}

・デザイン、コーディング、ディレクション、確認作業などの内訳ごとに表形式で金額を出力してください。
・見やすく整ったHTMLフォーマットで、太字や色なども用いてください。
・最後に注意点や補足事項があれば記載してください。
"""

        model = genai.GenerativeModel("gemini-2.5-pro")
        response = model.generate_content(prompt)
        html_output = response.text

        st.success("📊 Geminiによる見積もり結果")
        st.components.v1.html(f"""
        <div style="font-family: 'Arial', sans-serif; font-size: 15px; line-height: 1.6; padding: 10px;">
        {html_output}
        </div>
        """, height=800, scrolling=True)
