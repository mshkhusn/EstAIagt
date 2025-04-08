import streamlit as st
import google.generativeai as genai
import requests
from bs4 import BeautifulSoup

# --- APIキー設定 ---
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=GEMINI_API_KEY)

st.set_page_config(page_title="LP見積もりAI", layout="centered")
st.title("LP制作 見積もりAIエージェント（Gemini 2.0 Flash）")

# --- 入力フォーム ---
st.header("基本情報")
purpose = st.selectbox("LPの目的", ["商品紹介", "キャンペーン", "資料DL", "採用", "その他"])
custom_purpose = st.text_input("その他の目的（任意）")
page_length = st.selectbox("想定ボリューム", ["1スクリーン程度", "縦長1ページ", "10,000px以上"])
ref_url = st.text_input("参考サイトのURL（任意）")
ref_notes = st.text_area("トンマナ資料・備考（任意）")
due_date = st.date_input("納品希望日")

st.header("コンテンツ構成")
copy_needed = st.checkbox("コピーライティングあり")
writing_scope = st.radio("ライティング対応範囲", ["原稿支給あり", "全てライティング依頼"], index=0)
assets_provided = st.selectbox("画像・素材の支給", ["すべて支給", "一部支給", "なし"])
video_needed = st.checkbox("動画・アニメーション使用あり")
form_needed = st.checkbox("問い合わせ／応募フォームあり")
ab_test = st.checkbox("A/Bテストを想定")

st.header("デザイン・開発")
design_level = st.selectbox("デザインのクオリティ感", ["シンプル", "標準", "リッチ"])
responsive = st.radio("レスポンシブ対応", ["必須", "不要"], index=0)
anime = st.checkbox("アニメーションあり")
cms = st.selectbox("CMS使用予定", ["なし（HTML）", "WordPress", "STUDIO", "その他"])
seo = st.checkbox("SEO対応希望")
domain = st.checkbox("サーバー・ドメイン取得代行希望")
budget = st.text_input("参考予算（任意）")

# --- 参考サイトの構成抽出（任意） ---
def extract_site_structure(url):
    try:
        res = requests.get(url, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        headings = soup.find_all(["h1", "h2", "h3"])
        content = "\n".join([f"{tag.name.upper()}: {tag.get_text(strip=True)}" for tag in headings])
        return content[:3000]  # 長すぎないようにカット
    except:
        return "取得できませんでした。"

ref_structure = ""
if ref_url:
    st.caption("参考サイトの構成を取得中...")
    ref_structure = extract_site_structure(ref_url)
    st.text_area("参考サイトの見出し構成（抜粋）", ref_structure, height=200)

# --- Gemini出力 ---
if st.button("💡 Geminiに見積もりを依頼"):
    with st.spinner("AIが見積もりを作成中です..."):
        prompt = f"""
あなたはLP制作における見積もり作成のプロフェッショナルです。
以下の情報をもとに、制作項目ごとに内訳と概算費用（日本円）を表形式で提示してください。
HTML形式で整形し、視認性の高い出力にしてください。

【LP制作条件】
- 目的：{purpose + '／' + custom_purpose if custom_purpose else purpose}
- ページボリューム：{page_length}
- 納期：{due_date}
- コピーライティング：{'あり' if copy_needed else 'なし'}／{writing_scope}
- 素材支給：{assets_provided}
- 動画・アニメーション：{'あり' if video_needed else 'なし'}
- フォーム：{'あり' if form_needed else 'なし'}
- ABテスト：{'あり' if ab_test else 'なし'}
- デザインクオリティ：{design_level}、レスポンシブ：{responsive}、アニメーション：{'あり' if anime else 'なし'}
- CMS：{cms}、SEO：{'あり' if seo else 'なし'}、ドメイン取得代行：{'あり' if domain else 'なし'}
- 予算感：{budget or '未記入'}
- トンマナ資料／備考：{ref_notes or 'なし'}

参考サイト構成：
{ref_structure or 'なし'}

見積もりは以下の形式でHTML出力してください：
・セクションごとに区切る
・表やリスト形式で整形
・合計金額はハイライト表示
・装飾はシンプルで見やすく
"""

        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)

        st.success("📊 Geminiによる見積もり結果")
        st.components.v1.html(
            f"""
            <div style='font-family: Arial, sans-serif; font-size: 15px; line-height: 1.6;'>
                {response.text}
            </div>
            """,
            height=1000,
            scrolling=True
        )
