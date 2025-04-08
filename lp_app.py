import streamlit as st
import google.generativeai as genai
import requests
from bs4 import BeautifulSoup

# --- APIキーの読み込み ---
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=GEMINI_API_KEY)

# --- Streamlit UI設定 ---
st.set_page_config(page_title="LP見積もりAI", layout="centered")
st.title("LP見積もりAIエージェント（Gemini 2.5 Pro）")

# --- UIのスタイル調整 ---
st.markdown("""
<style>
.small-label { font-size: 0.9rem; font-weight: 500; margin-bottom: 4px; }
</style>
""", unsafe_allow_html=True)

# --- 入力項目 ---
st.markdown("### 基本情報の入力")
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
parsed_html = ""

if ref_url:
    st.markdown("🕒 参考URLの解析には時間がかかります。出力までしばらくお待ちください。")
    try:
        response = requests.get(ref_url, timeout=10)
        soup = BeautifulSoup(response.content, "html.parser")
        # タイトル + テキスト + alt属性を抽出してテキスト化
        texts = [tag.get_text(strip=True) for tag in soup.find_all(["h1", "h2", "p", "li"])]
        alts = [img.get("alt", "") for img in soup.find_all("img")]
        parsed_html = "\n".join(texts + alts)
    except Exception as e:
        st.warning(f"参考URLの解析に失敗しました：{e}")
        parsed_html = ""

# --- Geminiで見積もり生成 ---
if st.button("💡 Geminiに見積もりを依頼"):
    with st.spinner("AIが見積もりを作成中です..."):
        prompt = f"""
あなたはLP制作費見積もりのプロフェッショナルです。
以下の条件に基づいて、必要な工程・内訳ごとの費用を明確にし、日本円で概算見積もりをHTML形式で作成してください。

【LP概要】
- 目的：{lp_type}
- 想定ページ数：{page_count}
- レスポンシブ対応：{'あり' if responsive else 'なし'}
- フォーム実装：{'あり' if has_form else 'なし'}
- トラッキングタグ対応：{'あり' if has_tracking else 'なし'}
- アニメーション：{'あり' if has_animation else 'なし'}
- 素材支給状況：{content_ready}
- デザインクオリティ：{design_quality}
- 参考予算：{budget_hint or '未記入'}

{f"【参考LPの構造・特徴（HTML解析結果）】\n{parsed_html}" if parsed_html else ""}
HTML内で以下を満たしてください：
- 項目ごとの金額をリストまたは表で記載
- 合計金額を目立つ形式で表示
- ユーザーにとって視認性の高い構成にする（太字、色、区切りなどを使って）
"""
        model = genai.GenerativeModel("gemini-2.5-pro-exp-03-25")
        response = model.generate_content(prompt)
        html_output = response.text

        # --- 表示（HTMLで装飾） ---
        st.success("✅ Geminiによる見積もり結果")
        st.components.v1.html(f"""
        <div style="font-family: 'Arial', sans-serif; font-size: 15px; line-height: 1.6; padding: 10px;">
        {html_output}
        </div>
        """, height=800, scrolling=True)
