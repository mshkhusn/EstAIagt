import streamlit as st
import google.generativeai as genai
from openai import OpenAI

# ① Secrets の読み込み
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
APP_PASSWORD   = st.secrets["APP_PASSWORD"]

# ② 各種クライアント初期化
genai.configure(api_key=GEMINI_API_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

st.set_page_config(page_title="映像制作AIエージェント", layout="centered")

# —🔧（任意）デバッグ用: キーが正しく読めているか確認—
# st.write("OpenAI Key Prefix:", OPENAI_API_KEY[:8])

# ③ パスワード認証
password = st.text_input("パスワードを入力してください", type="password")
if password != APP_PASSWORD:
    st.warning("認証が必要です")
    st.stop()

st.title("映像制作AIエージェント（Gemini / GPT 切替）")

# ④ フォーム入力（あなたの既存のコードを流用してください）
model_choice = st.selectbox("使用するAIモデル", ["Gemini", "GPT-4o"])
# （その他の入力欄…）

# ⑤ プロンプト組み立て（あなたの既存プロンプトをここで `prompt` という変数にセット）
# prompt = f"""…"""

# ⑥ モデル呼び出し
if st.button("見積もりを作成"):
    with st.spinner("AIが見積もりを作成中…"):
        if model_choice == "Gemini":
            resp = genai.GenerativeModel("gemini-2.0-flash") \
                         .generate_content(prompt)
            result = resp.text
        else:
            resp = openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role":"system", "content":"あなたは広告映像の見積もりアシスタントです。"},
                    {"role":"user",   "content": prompt}
                ],
                temperature=0.7,
            )
            result = resp.choices[0].message.content

        st.markdown("✅ **見積もり結果**")
        st.components.v1.html(
            f"<div style='font-family:Arial;line-height:1.6'>{result}</div>",
            height=800
        )
