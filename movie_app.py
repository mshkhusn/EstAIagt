```python
# movie_app.py

import streamlit as st
import json
import google.generativeai as genai
from openai import OpenAI

# ─── 1. ページ設定 ─────────────────────────────────────────────
st.set_page_config(
    page_title="映像制作AIエージェント（二段階プロンプト化対応版）",
    layout="centered"
)

# ─── 2. Secrets 読み込み & クライアント初期化 ────────────────────
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
APP_PASSWORD   = st.secrets["APP_PASSWORD"]

genai.configure(api_key=GEMINI_API_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# ─── 3. パスワード認証 ─────────────────────────────────────────
st.title("映像制作AIエージェント（二段階プロンプト化対応版）")
password = st.text_input("パスワードを入力してください", type="password")
if password != APP_PASSWORD:
    st.warning("🔒 認証が必要です")
    st.stop()

# ─── 4. フォーム入力 ──────────────────────────────────────────
st.header("制作条件の入力")

video_duration = st.selectbox("尺の長さ", ["15秒", "30秒", "60秒", "15分", "その他"])
if video_duration == "その他":
    final_duration = st.text_input("尺の長さ（自由記入）を入力してください")
else:
    final_duration = video_duration

num_versions   = st.number_input("納品本数", min_value=1, max_value=10, value=1)
shoot_days     = st.number_input("撮影日数", min_value=1, max_value=10, value=1)
edit_days      = st.number_input("編集日数", min_value=1, max_value=10, value=3)
delivery_date  = st.date_input("納品希望日")
cast_main      = st.number_input("メインキャスト人数", 0, 10, 3)
cast_extra     = st.number_input("エキストラ人数", 0, 20, 0)
talent_use     = st.checkbox("タレント起用あり")
staff_roles    = st.multiselect(
    "必要なスタッフ",
    [
        "制作プロデューサー","制作プロジェクトマネージャー",
        "ディレクター","カメラマン","照明スタッフ",
        "スタイリスト","ヘアメイク","アシスタント"
    ]
)
shoot_location     = st.text_input("撮影場所（例：都内スタジオ＋ロケ）")
kizai              = st.multiselect("撮影機材", ["4Kカメラ","照明","ドローン","グリーンバック"])
set_design_quality = st.selectbox(
    "セット建て・美術装飾の規模",
    ["なし","小（簡易装飾）","中（通常レベル）","大（本格セット)"]
)
use_cg        = st.checkbox("CG・VFXあり")
use_narration = st.checkbox("ナレーション収録あり")
use_music     = st.selectbox("音楽素材", ["既存ライセンス音源","オリジナル制作","未定"])
ma_needed     = st.checkbox("MAあり")
deliverables  = st.multiselect("納品形式", ["mp4（16:9）","mp4（1:1）","mp4（9:16）","ProRes"])
subtitle_langs= st.multiselect("字幕言語", ["日本語","英語","その他"])
usage_region  = st.selectbox("使用地域", ["日本国内","グローバル","未定"])
usage_period  = st.selectbox("使用期間", ["6ヶ月","1年","2年","無期限","未定"])
budget_hint   = st.text_input("参考予算（任意）")
extra_notes   = st.text_area("その他備考（任意）")
model_choice  = st.selectbox("使用するAIモデル", ["Gemini","GPT-4o","GPT-4.1"])

# ─── 共通プロンプト (単一フェーズ参考) ───────────────────────────
common_prompt = f"""
あなたは広告制作費のプロフェッショナルな見積もりエージェントです。
以下の条件に基づいて、映像制作に必要な費用を詳細に見積もってください。
予算、納期、仕様、スタッフ構成、撮影条件などから、実務に即した内容で正確かつ論理的に推論してください。
短納期である場合や仕様が複雑な場合には、工数や費用が増える点も加味してください。

---
# 出力形式要件
- HTML + Markdown形式で読みやすく出力
- 見積もり表は「項目名・詳細・単価・数量・金額（日本円）」のテーブルで出力
- 合計金額は太字または色付きで強調
- 備考や注意点も記載
- フォントはArialを想定
- 正しいHTML構造で出力してください

# 見積もり出力における注意点
- 各項目の「単価 × 数量 = 金額」を正確に計算してください。
- 最後に全項目の金額を合算し、正確な合計金額（税抜）を表示してください。
- 合計金額には端数処理（円未満切り捨て／四捨五入）は行わず、正確に足し算してください。
- 金額は必ず日本円（円単位）で表示してください。
- 合計金額は見やすく太字または色付きで強調してください。
- 各項目の計算と合計の再確認を行い、金額の整合性が取れていることをチェックした上で出力してください。

# 条件:
{{json}}
"""

# ─── 5. 二段階プロンプト化フロー ─────────────────────────────────

# フェーズ①: 条件整理
if st.button("▶ 1: 条件を整理（JSON化）"):
    phase1_system = (
        "あなたは見積もりアシスタントです。ユーザーが指定した制作条件を"
        "JSON形式で返してください。キーは英語のキャメルケースで統一してください。"
    )
    phase1_user = {
        "duration": final_duration,
        "versions": num_versions,
        "shootDays": shoot_days,
        "editDays": edit_days,
        "dueDate": delivery_date.isoformat(),
        "castMain": cast_main,
        "castExtra": cast_extra,
        "talent": talent_use,
        "staff": staff_roles,
        "location": shoot_location,
        "equipment": kizai,
        "setLevel": set_design_quality,
        "cgVfx": use_cg,
        "narration": use_narration,
        "music": use_music,
        "ma": ma_needed,
        "formats": deliverables,
        "subtitles": subtitle_langs,
        "region": usage_region,
        "period": usage_period,
        "budget": budget_hint,
        "notes": extra_notes
    }
    resp1 = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role":"system","content":phase1_system},
            {"role":"user","content":json.dumps(phase1_user, ensure_ascii=False)}
        ],
        temperature=0
    )
    try:
        structured = json.loads(resp1.choices[0].message.content)
    except json.JSONDecodeError:
        st.error("JSONのパースに失敗しました。応答を確認してください。")
        st.write(resp1.choices[0].message.content)
        st.stop()
    st.subheader("✅ 整理された条件 (JSON)")
    st.json(structured)
    st.session_state.structured = structured

# フェーズ②: 見積もり生成
if "structured" in st.session_state and st.button("▶ 2: 見積もりを生成（HTML/MD）"):
    phase2_user = json.dumps(st.session_state.structured, ensure_ascii=False)
    # 結合プロンプト
    full_prompt = common_prompt.replace("{json}", phase2_user)
    if model_choice == "Gemini":
        resp2 = genai.GenerativeModel("gemini-2.0-flash").generate_content(full_prompt)
        result = resp2.text
    else:
        model_id = "gpt-4o" if model_choice=="GPT-4o" else "gpt-4.1"
        resp2 = openai_client.chat.completions.create(
            model=model_id,
            messages=[
                {"role":"system","content":"あなたは広告映像の見積もりアシスタントです。"},
                {"role":"user","content":full_prompt}
            ],
            temperature=0
        )
        result = resp2.choices[0].message.content

    st.subheader("✅ 見積もり結果")
    st.components.v1.html(
        result,
        height=800,
        scrolling=True
    )
```
