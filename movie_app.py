import streamlit as st
from openai import OpenAI
import json

# ① Secrets 読み込み
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
openai_client   = OpenAI(api_key=OPENAI_API_KEY)

# ② フォーム入力
st.header("制作条件の入力")
duration    = st.text_input("尺（例：15分）")
versions    = st.number_input("納品本数", 1, 10, 1)
shoot_days  = st.number_input("撮影日数", 1, 10, 1)
edit_days   = st.number_input("編集日数", 1, 10, 3)
# …残りの入力も同様に…

if st.button("▶ 1: 条件を整理"):
    # --- フェーズ①：条件収集フェーズ ---
    phase1_system = "あなたは見積もりアシスタントです。ユーザー条件をJSONで返してください。"
    phase1_user = {
        "尺":         duration,
        "納品本数":    versions,
        "撮影日数":    shoot_days,
        "編集日数":    edit_days,
        # … ほかのフィールドも揃える …
    }
    resp1 = openai_client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role":"system", "content":phase1_system},
            {"role":"user",   "content": json.dumps(phase1_user, ensure_ascii=False)}
        ],
        temperature=0,
    )
    # モデル応答を JSON パース
    structured = json.loads(resp1.choices[0].message.content)
    st.json(structured)

    # --- フェーズ②：見積もり出力フェーズ ---
    phase2_system = """
    上記 JSON の内容に基づいて、HTML+Markdown形式の見積もり表を作成してください。
    - 列: 項目名 / 詳細 / 単価 / 数量 / 金額
    - 合計金額は太字で強調
    - 最後に「計算を再確認してください」という注意文を追加
    """
    resp2 = openai_client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role":"system", "content":phase2_system},
            {"role":"user",   "content": json.dumps(structured, ensure_ascii=False)}
        ],
        temperature=0,
    )

    st.markdown("✅ **見積もり結果**")
    st.components.v1.html(
        resp2.choices[0].message.content,
        height=600, scrolling=True
    )
