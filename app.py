import streamlit as st

st.set_page_config(page_title="見積もり制作AIエージェントメニュー", layout="centered")

st.title("見積もり制作AIエージェント")

# 注意書き
st.markdown("""
プロトタイプ公開中　  
※テスト中のためそのまま実際の見積もりには使用しないでください  
※Geminiが計算に弱いので合計金額の計算が間違っている場合があります。  
※プロンプトで金額再チェックしてから出力するよう指示を入れてますが、要注意。  
※GPT-4oか4.1に変更で解消されます。（近日予定）  
※GPT-4oか4.1に変更することで、2024年東京圏・広告業界想定相場で価格を出せそうです。
""")

# 各ページへのリンク
st.markdown("---")

st.markdown("### WebCM 見積もりAIエージェント")
st.markdown("[WebCMエージェントを開く](https://estaiagt-webcm.streamlit.app/)")

st.markdown("### バナー広告 見積もりAIエージェント")
st.markdown("[バナーエージェントを開く](https://estalagt-banner.streamlit.app/)")

st.markdown("### LP制作 見積もりAIエージェント（※使用回数制限あり）")
st.markdown("[LPエージェントを開く](https://estaiagt-lp.streamlit.app/)")

st.markdown("---")
st.caption("※ 上記はプロトタイプです。実際の見積もりには使用しないでください。")
