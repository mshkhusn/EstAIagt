import streamlit as st
import google.generativeai as genai
import requests
from bs4 import BeautifulSoup

# 🔐 APIキーの読み込み
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=GEMINI_API_KEY)

st.set_page_config(page_title="LP見積もりAI", layout="centered")
st.title("📈 LP見積もりAIエージェント (Gemini 2.5 Pro)")

st.markdown("""
<style>
.small-label { font-size: 0.9rem; font-weight: 500; margin-bottom: 4px; }
</style>
""", unsafe_allow_html=True)

# 入力項目
st.markdown("### ページ要件")
page_type = st.selectbox("ページ種別", ["キャンペーンLP", "商品紹介", "ブランドサイト", "その他"])
elements = st.multiselect("含まれる要素", ["ビジュアル", "モーション", "動画", "フォーム", "お問い合わせ", "試算", "ランディングページ"], default=["ビジュアル"])
lang_support = st.checkbox("多言語対応あり")
responsive = st.checkbox("レスポンシブ対応")
backend_link = st.checkbox("CMS/APIなどとの連携あり")
seo_required = st.checkbox("SEO/追跡コード対応")
design_level = st.selectbox("デザインレベル", ["シンプル", "標準", "リッチ"])
expected_pages = st.number_input("情報量ボリューム(セクション数)", 1, 10, 3)
delivery_date = st.date_input("納品希望日")
budget_hint = st.text_input("参考予算(任意)")

# 参考URLの入力
st.markdown("### 参考LPサイト")
ref_url = st.text_input("参考サイトURL", placeholder="https://...")
st.caption("\ud83d\udd5b 参考URLの解析には時間がかかります。出力までしばらくお待ちください")

ref_summary = ""
if ref_url:
    try:
        html = requests.get(ref_url, timeout=10).text
        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.string.strip() if soup.title else "(title不明)"
        tag_count = len(soup.find_all())
        has_video = bool(soup.find("video"))
        has_animation = any("animate" in str(tag.get("class", "")) for tag in soup.find_all())

        ref_summary = f"\n[参考LP構造解析] タイトル: {title}\n- HTMLタグ数: {tag_count}\n- 動画要素: {'あり' if has_video else 'なし'}\n- アニメーション的classの検出: {'あり' if has_animation else 'なし'}\n- ブランド要素の富みから、高度なUI/インタラクションやコーポレート要件を含むと体系して見停もりを行ってください\n"
    except Exception as e:
        ref_summary = f"[参考LPの解析に失敗しました]：{e}"  # 安全な出力に留める

# 見積もり作成
if st.button("📊 Gemini 2.5 Pro で見積もり作成"):
    with st.spinner("AIが見積もりを作成中..."):
        prompt = f"""
あなたはLP制作費用見積もりのプロフェッショナルです。以下の情報をもとに、内訳と約算価格をHTMLで解析して仕様を推定してください。

---

【LP種別】: {page_type}
【要素】: {', '.join(elements)}
【多言語対応】: {'あり' if lang_support else 'なし'}
【レスポンシブ】: {'あり' if responsive else 'なし'}
【システム連携】: {'あり' if backend_link else 'なし'}
【SEO/追跡】: {'あり' if seo_required else 'なし'}
【デザインレベル】: {design_level}
【情報量ボリューム】: {expected_pages}P
【納品希望日】: {delivery_date}
【参考予算】: {budget_hint or 'なし'}

{ref_summary}

---

セクション別に「内訳」「概算金額」を演算し、補足説明を付けたテーブル風HTML表示で表示して下さい。
"""

        model = genai.GenerativeModel("gemini-2.5-pro-exp-03-25")
        response = model.generate_content(prompt)
        html_output = response.text

        st.success("✅ Gemini 2.5 Pro による見積もり結果")
        st.components.v1.html(f"""
        <div style='font-family: Arial, sans-serif; font-size: 15px; line-height: 1.7; padding: 10px;'>
        {html_output}
        </div>
        """, height=800, scrolling=True)
