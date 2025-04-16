import streamlit as st
import google.generativeai as genai
import requests
from bs4 import BeautifulSoup

# --- APIキーの読み込み ---
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=GEMINI_API_KEY)

st.set_page_config(page_title="LP見積もりAI", layout="centered")
st.title("LP見積もりAIエージェント（Gemini 2.5 Pro）※使用回数制限ありver.")

# --- 基本情報 ---
st.header("1. 基本情報")
project_name = st.text_input("案件名（任意）")
client_name = st.text_input("クライアント名（任意）")
page_structure = st.text_input("想定ページ構成（例：1ページLP、ページ遷移あり など）")
goal = st.text_input("目的・ゴール（例：資料請求、購入、申込、応募 など）")
target = st.text_input("ターゲット（年齢層・性別・職業など）")
delivery_date = st.date_input("納品希望日")
budget_hint = st.text_input("参考予算（任意）")

# --- 制作仕様 ---
st.header("2. 制作仕様")
responsive = st.checkbox("レスポンシブ対応（PC/スマホ）", value=True)
has_form = st.checkbox("フォーム実装あり")
has_tracking = st.checkbox("トラッキングタグの実装あり")
has_animation = st.checkbox("アニメーション・動きあり")
design_quality = st.selectbox("デザインのクオリティ", ["シンプル", "標準", "リッチ"], index=2)
assets_provided = st.checkbox("素材支給あり（画像・テキスト等）")
seo_required = st.checkbox("SEOを考慮した構成")

# --- 参考情報 ---
st.header("3. 参考情報")
reference_url = st.text_input("参考LPのURL（任意）")
st.caption("※ 参考URLの解析には時間がかかります。出力までしばらくお待ちください")
notes = st.text_area("その他の補足・特記事項")

# --- プロンプト生成と出力 ---
if st.button("💡 Geminiに見積もりを依頼"):
    with st.spinner("AIが見積もりを作成中です..."):

        site_summary = ""
        if reference_url:
            try:
                response = requests.get(reference_url, timeout=10)
                soup = BeautifulSoup(response.content, "html.parser")
                texts = soup.get_text(separator='\n')
                site_summary = f"\n【参考LPの特徴（HTMLからの自動抽出）】\n{texts[:1000]}..."
            except Exception as e:
                site_summary = f"\n【参考LPの取得に失敗しました】：{e}"

        base_conditions = f"""
【基本情報】
- 案件名：{project_name or "（未入力）"}
- クライアント名：{client_name or "（未入力）"}
- 納品希望日：{delivery_date}
- 想定ページ構成：{page_structure or "（未入力）"}
- 目的・ゴール：{goal or "（未入力）"}
- ターゲット：{target or "（未入力）"}
- 参考予算：{budget_hint or "（未入力）"}

【制作仕様】
- レスポンシブ対応：{'あり' if responsive else 'なし'}
- フォーム実装：{'あり' if has_form else 'なし'}
- トラッキングタグ実装：{'あり' if has_tracking else 'なし'}
- アニメーション：{'あり' if has_animation else 'なし'}
- デザイン品質：{design_quality}
- 素材支給：{'あり' if assets_provided else 'なし'}
- SEO考慮：{'あり' if seo_required else 'なし'}
        """

        site_info = site_summary

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
            "- 表示フォントはArialを想定\n"
            "- 正しいHTML構造で出力してください\n"
            "- **出力が崩れた場合は、再度依頼ボタンを押して試してください。**\n"
            "- 納品希望日が短い（急ぎの案件）の場合、作業の圧縮や追加工数が必要になるため、費用は通常よりも高くなる傾向があります。\n"
            "# 見積もり出力における注意点\n"
            "- 各項目の「単価 × 数量 = 金額」を正確に計算してください。\n"
            "- 最後に全項目の金額を合算し、正確な合計金額（税抜）を表示してください。\n"
            "- 合計金額には端数処理（円未満切り捨て／四捨五入）は行わず、正確に足し算してください。\n"
            "- 金額は必ず日本円（円単位）で表示してください。\n"
            "- 合計金額は見やすく太字または色付きで強調してください。\n"
        )

        model = genai.GenerativeModel("gemini-2.5-pro-exp-03-25")
        response = model.generate_content(prompt)
        html_output = response.text

        st.success("✅ Geminiによる見積もり結果（※崩れる場合は再実行してください）")
        st.components.v1.html(f"""
        <div style='font-family: "Arial", sans-serif; font-size: 15px; line-height: 1.7; padding: 10px;'>
        {html_output}
        </div>
        """, height=1200, scrolling=True)
