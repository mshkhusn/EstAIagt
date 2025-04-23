import streamlit as st
import google.generativeai as genai
from openai import OpenAI

# ─── 1. ページ設定 ─────────────────────────────────────────────
st.set_page_config(
    page_title="映像制作AIエージェント",
    layout="centered",
)

# ─── 2. Secrets 読み込み & クライアント初期化 ────────────────────
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
APP_PASSWORD   = st.secrets["APP_PASSWORD"]

genai.configure(api_key=GEMINI_API_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# ─── 3. パスワード認証 ─────────────────────────────────────────
st.title("映像制作AIエージェント（Gemini / GPT 切替対応版）")
password = st.text_input("パスワードを入力してください", type="password")
if password != APP_PASSWORD:
    st.warning("🔒 認証が必要です")
    st.stop()

# ─── 4. ユーザー入力フォーム ────────────────────────────────────
st.header("制作条件の入力")

video_duration = st.selectbox("尺の長さ", ["15秒", "30秒", "60秒", "その他"])
if video_duration == "その他":
    final_duration = st.text_input("尺の長さ（自由記入）")
else:
    final_duration = video_duration

num_versions  = st.number_input("納品本数",    min_value=1, max_value=10, value=1)
shoot_days    = st.number_input("撮影日数",    min_value=1, max_value=10, value=2)
edit_days     = st.number_input("編集日数",    min_value=1, max_value=10, value=3)
delivery_date = st.date_input("納品希望日")
cast_main     = st.number_input("メインキャスト人数", 0, 10, 1)
cast_extra    = st.number_input("エキストラ人数",    0, 20, 0)
talent_use    = st.checkbox("タレント起用あり")
staff_roles   = st.multiselect(
    "必要なスタッフ",
    [
        "制作プロデューサー", "制作プロジェクトマネージャー",
        "ディレクター", "カメラマン", "照明スタッフ",
        "スタイリスト", "ヘアメイク", "アシスタント"
    ]
)
shoot_location     = st.text_input("撮影場所（例：都内スタジオ＋ロケ）")
kizai              = st.multiselect("撮影機材", ["4Kカメラ", "照明", "ドローン", "グリーンバック"])
set_design_quality = st.selectbox(
    "セット建て・美術装飾の規模",
    ["なし", "小（簡易装飾）", "中（通常レベル）", "大（本格セット）"]
)
use_cg        = st.checkbox("CG・VFXあり")
use_narration = st.checkbox("ナレーション収録あり")
use_music     = st.selectbox("音楽素材", ["既存ライセンス音源", "オリジナル制作", "未定"])
ma_needed     = st.checkbox("MAあり")
deliverables  = st.multiselect("納品形式", ["mp4（16:9）", "mp4（1:1）", "mp4（9:16）", "ProRes"])
subtitle_langs = st.multiselect("字幕言語", ["日本語", "英語", "その他"])
usage_region  = st.selectbox("使用地域", ["日本国内", "グローバル", "未定"])
usage_period  = st.selectbox("使用期間", ["6ヶ月", "1年", "2年", "無期限", "未定"])
budget_hint   = st.text_input("参考予算（任意）")
extra_notes   = st.text_area("その他備考（任意）")

model_choice  = st.selectbox("使用するAIモデル", ["Gemini", "GPT-4o", "GPT-4.1"])

# ─── 5. プロンプト生成（第一段階：条件整理）──────────
system_prompt = """\
あなたは広告制作費のプロフェッショナルな見積もりエージェントです。
以下の条件に基づいて、映像制作に必要な費用を詳細に見積もってください。
予算、納期、仕様、スタッフ構成、撮影条件などから、実務に即した内容で正確かつ論理的に推論してください。
短納期である場合や仕様が複雑な場合には、工数や費用が増える点も加味してください。
"""

# ※ ここで全入力値を文字列化して１つのリスト／辞書にまとめてもOK
detail_lines = [
    f"- 尺：{final_duration}",
    f"- 納品本数：{num_versions}本",
    f"- 撮影日数：{shoot_days}日",
    f"- 編集日数：{edit_days}日",
    f"- 納品希望日：{delivery_date}",
    f"- メインキャスト人数：{cast_main}人",
    f"- エキストラ人数：{cast_extra}人",
    f"- タレント：{'あり' if talent_use else 'なし'}",
    f"- 必要スタッフ：{', '.join(staff_roles) or 'なし'}",
    f"- 撮影場所：{shoot_location or 'なし'}",
    f"- 撮影機材：{', '.join(kizai) or 'なし'}",
    f"- セット建て・美術装飾：{set_design_quality}",
    f"- CG・VFX：{'あり' if use_cg else 'なし'}",
    f"- ナレーション：{'あり' if use_narration else 'なし'}",
    f"- 音楽：{use_music}",
    f"- MA：{'あり' if ma_needed else 'なし'}",
    f"- 納品形式：{', '.join(deliverables) or 'なし'}",
    f"- 字幕言語：{', '.join(subtitle_langs) or 'なし'}",
    f"- 使用地域：{usage_region}",
    f"- 使用期間：{usage_period}",
    f"- 参考予算：{budget_hint or 'なし'}",
    f"- その他備考：{extra_notes or 'なし'}",
]
details_block = "\n".join(detail_lines)

# ─── 6. プロンプト組み立て（第二段階：出力要件含む）───
output_requirements = """\
---
# 出力形式要件
- HTML + Markdown形式で読みやすく出力
- 見積もり表は「項目名・詳細・単価・数量・金額（日本円）」のテーブルで出力
- 合計金額は太字または色付きで強調
- 備考や注意点も必ず記載
- フォントはArialを想定
- 正しいHTML構造で出力してください

# 見積もり出力における注意点
- 各項目の「単価 × 数量 = 金額」を正確に計算してください。
- 最後に全項目の金額を合算し、正確な合計金額（税抜）を表示してください。
- 端数処理は行わず、正確に足し算してください。
- 金額は必ず日本円（円単位）で表示してください。
- 合計金額は見やすく太字または色付きで強調してください。
- 出力前に計算と合計を再確認し、整合性が取れていることをチェックしてください。
"""

prompt = f"{system_prompt}\n{details_block}\n\n{output_requirements}"

# ─── 7. モデル呼び出し & 結果表示 ───────────────────────────────
if st.button("💡 見積もりを作成"):
    with st.spinner("AI が見積もりを作成中…"):
        if model_choice == "Gemini":
            resp = genai.GenerativeModel("gemini-2.0-flash") \
                        .generate_content(prompt)
            result = resp.text

        elif model_choice == "GPT-4o":
            resp = openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": prompt},
                ],
                temperature=0.7,
            )
            result = resp.choices[0].message.content

        else:  # GPT-4.1
            resp = openai_client.chat.completions.create(
                model="gpt-4.1",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": prompt},
                ],
                temperature=0.7,
            )
            result = resp.choices[0].message.content

        st.success("✅ 見積もり結果")
        st.components.v1.html(
            f"<div style='font-family:Arial;line-height:1.6;padding:10px'>{result}</div>",
            height=900,
            scrolling=True,
        )
