import streamlit as st
import google.generativeai as genai
import requests
from bs4 import BeautifulSoup
from datetime import date

# --- 設定 ---
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=GEMINI_API_KEY)

st.set_page_config(page_title="LP見積もりAI", layout="centered")
st.title("📄 LP見積もりAIエージェント（Gemini 2.5 Pro）")

# --- 入力フォーム ---
st.markdown("### 📋 製作条件の入力")

lp_purpose = st.text_input("LPの目的（例：キャンペーン訴求、新商品紹介など）")
page_depth = st.selectbox("想定ページ構成", ["1ページ（縦長LP）", "2〜3ページ構成", "それ以上"])
form_required = st.checkbox("フォームの実装が必要")
tracking_required = st.checkbox("トラッキングタグの埋め込みが必要")
responsive = st.checkbox("レスポンシブ対応（スマホ/PC）")
animation = st.selectbox("アニメーションの有無", ["なし", "簡易（フェードインなど）", "リッチ（複雑な動き）"])
assets_provided = st.multiselect("支給される素材", ["テキスト", "画像", "動画", "イラスト", "ロゴ"])
design_quality = st.selectbox("デザイン品質の希望", ["シンプル", "標準", "リッチ（高級感あり）"])
delivery_date = st.date_input("納品希望日", value=date.today())
budget_hint = st.text_input("参考予算（任意）")

# --- 参考URL ---
st.markdown("### 🔍 参考LPサイト")
lp_url = st.text_input("参考サイトURL（任意）", placeholder="https://...")
if lp_url:
    st.caption("\u231b 参考URLの解析には時間がかかります。出力までしばらくお待ちください。")

lp_site_summary = ""
if lp_url:
    try:
        r = requests.get(lp_url, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        title = soup.title.string.strip() if soup.title else "タイトルなし"
        text = soup.get_text(separator=" ", strip=True)
        cleaned = " ".join(text.split()[:600])
        lp_site_summary = f"【参考LPタイトル】{title}\n【内容サマリー】{cleaned[:1000]}..."
    except Exception as e:
        lp_site_summary = f"参考サイトの解析に失敗しました（{str(e)}）"

# --- Geminiに見積もり依頼 ---
if st.button("💡 Geminiに見積もりを依頼"):
    with st.spinner("AIが見積もりを作成中です..."):

        base_conditions = f"""
【LPの目的】：{lp_purpose or '未入力'}
【構成】：{page_depth}
【フォーム】：{'あり' if form_required else 'なし'}
【トラッキングタグ】：{'あり' if tracking_required else 'なし'}
【レスポンシブ】：{'あり' if responsive else 'なし'}
【アニメーション】：{animation}
【素材支給】：{', '.join(assets_provided) if assets_provided else 'なし'}
【デザイン品質】：{design_quality}
【納品希望日】：{delivery_date}
【参考予算】：{budget_hint or 'なし'}
"""

        site_info = f"\n【参考URLの解析結果】\n{lp_site_summary}" if lp_site_summary else ""

        prompt = (
            "あなたは広告制作のプロフェッショナルな見積もりエージェントです。\n"
            "以下の条件に基づいて、LP制作に必要な費用を詳細に見積もってください。\n"
            "参考URLがある場合は、その構成・要素・インタラクション・デザインレベルなども読み取って、\n"
            "参考にして推論し、全体の仕様レベルを高精度に評価した上で、必要工数と費用を見積もってください。\n"
            "---\n"
            f"{base_conditions}\n"
            f"{site_info}\n"
            "---\n"
            "# 出力形式要件\n"
            "- HTML + Markdown形式で読みやすく出力\n"
            "- 見積もり表は「項目・詳細・単価・数量・金額（日本円）」形式のテーブルで出力\n"
            "- 合計金額は太字または色付きで強調\n"
            "- 備考や注意点も記載\n"
            "- 表示フォントはArialを想定"
        )

        model = genai.GenerativeModel("gemini-2.5-pro-exp-03-25")
        response = model.generate_content(prompt)
        html_output = response.text

        st.success("\u2705 Geminiによる見積もり結果")
        st.markdown(
            f"""<div style="font-family: Arial, sans-serif; font-size: 15px; line-height: 1.7; padding: 10px;">
{html_output}
</div>""",
            unsafe_allow_html=True
        )
