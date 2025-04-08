import streamlit as st
import google.generativeai as genai
import requests
from bs4 import BeautifulSoup

# ━━━ セクレット 読み込み ━━━
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=GEMINI_API_KEY)

# ━━━ アプリ設定 ━━━
st.set_page_config(page_title="LP見積もりAI", layout="centered")
st.title("🌐 LP見積もりAIエージェント")

st.markdown("### 基本情報")
page_type = st.selectbox("LPの種類", ["キャンペーンLP", "問合わせ紹介LP", "商品説明LP", "その他"])
industry = st.text_input("業種")
num_pages = st.slider("ページ数 (約2メインビュー以内の前提)", 1, 10, 3)
content_elements = st.multiselect("含まれる主要要素", ["ヒーローヘッダ", "説明文", "図解", "アイコン", "動画", "おしゃれな動き", "ボタン/CTA", "フォーム"])
has_form = st.checkbox("フォーム入力/問合わせ機能あり")
has_tracking = st.checkbox("GA4/ターゲッティング追跡対応")
delivery_date = st.date_input("約定納品日")
budget_hint = st.text_input("参考予算 (任意)")
assets_provided = st.checkbox("組織内統一デザインやロゴ等の支給あり")
responsive = st.checkbox("レスポンシブ対応/スマホ対応の要素あり")
seo_consideration = st.checkbox("SEOを意識したコンテンツ構成")

st.markdown("### 参考LPのURL (あれば)")
reference_url = st.text_input("参考サイトのURL", placeholder="https://example.com/")
if reference_url:
    st.caption("🔹 参考URLの解析には時間がかかります。出力までしばらくお待ちください")

# ━━━ 参考サイト解析 ━━━
reference_info = ""
if reference_url:
    try:
        res = requests.get(reference_url, timeout=10)
        soup = BeautifulSoup(res.content, "html.parser")
        title = soup.title.string.strip() if soup.title else ""
        keyword_count = len(soup.find_all(["img", "video", "form", "script"]))
        reference_info = f"\n\n[補足] 指定されたURL（{reference_url}）は「{title}」というタイトルで、画像/動画/JS等 {keyword_count} 要素を含む複雑な構造の可能性があります。"
    except:
        reference_info = f"\n\n[補足] 指定されたURL（{reference_url}）は正しく読み取れませんでしたが、類似するLPとして考慮してください。"

# ━━━ Gemini 見積もり出力 ━━━
if st.button("📊 Geminiに見積もりを依頼"):
    with st.spinner("AIが見積もりを作成中..."):
        prompt = f"""
あなたはLP制作のプロフェッショナルです。
以下の条件をもとに、構成・仕様・参考費用（日本円）の見積もりをHTMLで提示してください。

【LP種別】：{page_type}
【業種】：{industry}
【ページ数】：{num_pages}ページ
【要素】：{', '.join(content_elements) if content_elements else '未指定'}
【フォーム】：{'あり' if has_form else 'なし'}
【計測・タグ】：{'あり' if has_tracking else 'なし'}
【レスポンシブ】：{'あり' if responsive else 'なし'}
【素材支給】：{'あり' if assets_provided else 'なし'}
【SEO対応】：{'あり' if seo_consideration else 'なし'}
【納品日】：{delivery_date}
【参考予算】：{budget_hint or 'なし'}
{reference_info}

構成概要・設計意図・各項目ごとの内訳金額・想定工数などを含め、見やすくHTMLで出力してください。
重要な金額や合計費用には<strong>太字</strong>や色も使ってください。
        """
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)

        st.success("📊 GeminiによるLP見積もり")
        st.components.v1.html(f"""
            <div style='font-family: "Segoe UI", sans-serif; font-size: 15px; line-height: 1.7;'>
            {response.text}
            </div>
        """, height=1000, scrolling=True)
