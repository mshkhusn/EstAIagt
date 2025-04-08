import streamlit as st

st.set_page_config(page_title="見積もり制作AIエージェントメニュー", layout="centered")

st.title("見積もり制作AIエージェント")

st.markdown("以下から見積もりアプリを選択してください")

# 各ページへのリンク
st.markdown("---")

st.markdown("### WebCM 見積もりAIエージェント")
st.markdown("[WebCMエージェントを開く](https://estaiagt-webcm.streamlit.app/)")

st.markdown("### バナー広告 見積もりAIエージェント")
st.markdown("[バナーエージェントを開く](https://estalagt-banner.streamlit.app/)")

st.markdown("### LP制作 見積もりAIエージェント（準備中）")
st.markdown("[LPエージェントを開く](https://estalagt-lp.streamlit.app/)")

st.markdown("---")
st.caption("※ 上記リンクはデプロイ名・構成に応じて調整してください")
