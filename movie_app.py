import streamlit as st
import google.generativeai as genai
from openai import OpenAI
import re
import pandas as pd
from io import BytesIO


# --- ページ設定 ---
st.set_page_config(page_title="映像制作AIエージェント", layout="centered")

# --- Secrets 読み込み ---
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
APP_PASSWORD   = st.secrets["APP_PASSWORD"]

genai.configure(api_key=GEMINI_API_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# --- セッション状態の初期化 ---
if "resA" not in st.session_state:
    st.session_state["resA"] = None
if "resB" not in st.session_state:
    st.session_state["resB"] = None
if "final_html" not in st.session_state:
    st.session_state["final_html"] = None

# --- 認証 ---
st.title("映像制作AIエージェントβ")
password = st.text_input("パスワードを入力してください", type="password")
if password != APP_PASSWORD:
    st.warning("🔒 認証が必要です")
    st.stop()

# --- ユーザー入力 ---
st.header("制作条件の入力")
video_duration = st.selectbox("尺の長さ", ["15秒", "30秒", "60秒", "その他"])
final_duration = st.text_input("尺の長さ（自由記入）") if video_duration == "その他" else video_duration
num_versions = st.number_input("納品本数", min_value=1, max_value=10, value=1)
shoot_days = st.number_input("撮影日数", min_value=1, max_value=10, value=2)
edit_days = st.number_input("編集日数", min_value=1, max_value=10, value=3)
delivery_date = st.date_input("納品希望日")
cast_main = st.number_input("メインキャスト人数", 0, 10, 1)
cast_extra = st.number_input("エキストラ人数", 0, 20, 0)
talent_use = st.checkbox("タレント起用あり")
default_roles = [
    "制作プロデューサー", "制作プロジェクトマネージャー", "ディレクター", "カメラマン", 
    "照明スタッフ", "スタイリスト", "ヘアメイク"
]
selected_roles = st.multiselect("必要なスタッフ（選択式）", default_roles, default=default_roles)

custom_roles_text = st.text_input("その他のスタッフ（カンマ区切りで自由に追加）")
custom_roles = [role.strip() for role in custom_roles_text.split(",") if role.strip()]

staff_roles = selected_roles + custom_roles

shoot_location = st.text_input("撮影場所（例：都内スタジオ＋ロケ）")
kizai = st.multiselect("撮影機材", ["4Kカメラ", "照明", "ドローン", "グリーンバック"], default=["4Kカメラ", "照明"])
set_design_quality = st.selectbox("セット建て・美術装飾の規模", ["なし", "小（簡易装飾）", "中（通常レベル）", "大（本格セット）"])
use_cg = st.checkbox("CG・VFXあり")
use_narration = st.checkbox("ナレーション収録あり")
use_music = st.selectbox("音楽素材", ["既存ライセンス音源", "オリジナル制作", "未定"])
ma_needed = st.checkbox("MAあり")
deliverables = st.multiselect("納品形式", ["mp4（16:9）", "mp4（1:1）", "mp4（9:16）", "ProRes"])
subtitle_langs = st.multiselect("字幕言語", ["日本語", "英語", "その他"])
usage_region = st.selectbox("使用地域", ["日本国内", "グローバル", "未定"])
usage_period = st.selectbox("使用期間", ["3ヶ月","6ヶ月", "1年", "2年", "無期限", "未定"])
budget_hint = st.text_input("参考予算（任意）※予算を入れるとその金額に近づけて調整します。出力された見積もり金額が相場と異なると感じた場合は、参考予算を入力して再調整をお試しください。")
extra_notes = st.text_area("その他備考（任意）※案件の概要やキャスティング手配の有無など、重視したいポイントなどをご記入いただくと、より精度の高い見積もりが可能になります")
model_choice = st.selectbox("使用するAIモデル　※Gemini、GPT-4o、GPT-4.1、GPT-4o-miniを選べます。", ["Gemini", "GPT-4o", "GPT-4.1", "GPT-4o-mini"])

model = "gpt-4o" if model_choice == "GPT-4o" else "gpt-4o-mini" if model_choice == "GPT-4o-mini" else "gpt-4.1"

# --- プロンプト A ---
promptA = f"""
あなたは広告制作費のプロフェッショナルな見積もりエージェントです。
以下の条件から、必要な制作工程・リソース（人件費・機材・スタジオ・その他オプションなど）を
漏れなくリストアップしてください。
予算、納期、仕様、スタッフ構成、撮影条件などから、実務に即した内容で正確かつ論理的に推論してください。
短納期や複雑な仕様の場合は、工数や費用が増加する点も加味してください。
※ 管理費は「固定金額」で設定してください。パーセンテージ指定は禁止です。
※ また、見算もり全体の量とバランスを見て、過大にならない金額に調整してください。相場としては、全体の5～10%内に範囲に絞りましょう。
項目ごとに「制作人件費」「企画」「撮影費」「出演関連費」「編集費・MA費」「諸経費」といったカテゴリに分類してください。
※「制作プロデューサー」「制作プロジェクトマネージャー」「ディレクター」は「制作人件費」カテゴリの中項目として分類してください
※「カメラマン」「照明スタッフ」「スタイリスト」「ヘアメイク」は「撮影費」カテゴリの中項目として分類してください
※ 「その他のスタッフ」に関しては、どこに入れるべきか推論した上で適当な箇所に分類してください。
※「撮影機材」は「撮影費」カテゴリの中項目として分類してください
※「セット建て・美術装飾」は「撮影費」カテゴリの中項目として分類してください
カテゴリ名ごとに見出しをつけて、見積もりが見やすい構造になるよう整理してください。
参考予算（任意）に金額がある場合は、その金額に近づけるよう全ての項目を調整してください。
その他備考（任意）に入力がある場合は、その内容を鑑みて推論した上で見積もりに反映してください。
【条件】
- 尺：{final_duration}
- 納品本数：{num_versions}本
- 撮影日数：{shoot_days}日
- 編集日数：{edit_days}日
- 納品希望日：{delivery_date}
- メインキャスト人数：{cast_main}人
- エキストラ人数：{cast_extra}人
- タレント：{'あり' if talent_use else 'なし'}
- スタッフ：{', '.join(staff_roles)}
- 撮影場所：{shoot_location or '未定'}
- 撮影機材：{', '.join(kizai)}
- 美術装飾：{set_design_quality}
- CG：{'あり' if use_cg else 'なし'}
- ナレーション：{'あり' if use_narration else 'なし'}
- 音楽：{use_music}
- MA：{'あり' if ma_needed else 'なし'}
- 納品形式：{', '.join(deliverables)}
- 字幕：{', '.join(subtitle_langs)}
- 地域：{usage_region}
- 期間：{usage_period}
- 参考予算：{budget_hint or '未設定'}
- 備考：{extra_notes or '特になし'}
"""

# --- プロンプト B ---
promptB = """
以下の項目について、すべて「単価×数量＝金額（円）」の形式で計算し、
「項目名：金額（円）」で1行ずつ出力してください。
端数処理はせず、すべて整数で出力。管理費は固定金額で。
また、項目ごとに単価・数量も併記してください（例：撮影機材：単価80,000円×数量1日＝80,000円）
さらに、すべての項目の金額を正確に合計し、合計金額の算出に誤りがないかチェックしてください。
誤りがある場合は修正し、最終的に正しい合計金額のみを表示してください。
# 以下に項目を貼ってください
"""

# --- プロンプト C（HTML専用） ---
promptC_template = """
以下の2つの情報をもとに、HTMLの<table>構造で1つの表としてカテゴリごとに区切った見積書を作成してください。
1) 項目出し結果:
{items_a}
2) 計算結果:
{items_b}
出力形式:
- HTML冒頭に以下の説明文を挿入してください：
  『以下は、映像制作にかかる各種費用をカテゴリごとに整理した概算見積書です。』
- 冒頭に続けて、本見積もり要件を説明した説明文を記載してください。
- <table>タグで1つのテーブルとして表示
- カラム：カテゴリ／項目／単価／数量／単位／金額（円）
- 各カテゴリの最初に colspan=6 の見出し行を追加して区切る（例：<tr><td colspan='6'>撮影費</td></tr>）
- 見出しは左寄せで表示してください
- 金額カラムは右寄せ、合計は<b>または<span style='color:red'>で強調
- 管理費は固定金額、合計金額の10%以内に収めてください
- HTMLの最後に「備考」欄を追加し、以下の文言を記載してください：
  『※本見積書は自動生成された概算見積もりです。実際の制作内容・条件により金額が増減する可能性があります。あらかじめご了承ください。』
- 備考には見積もりにあたっての条件や注意事項などを必要に応じて記載してください。
- HTML構造は正確に
"""

# --- 合計金額チェック関数 ---
def extract_and_validate_total(estimate_text):
    lines = estimate_text.strip().split("\n")
    item_lines = [l for l in lines if "＝" in l and "円" in l]
    total_calc = sum(
        int(m.group(1).replace(",", "")) * int(m.group(2))
        for l in item_lines if (m := re.search(r"単価([0-9,]+)円×数量([0-9]+)", l))
    )
    for l in lines:
        if "合計" in l and "円" in l:
            m = re.search(r"合計.*?([0-9,]+)円", l)
            if m:
                total_displayed = int(m.group(1).replace(",", ""))
                return total_displayed, total_calc, total_displayed == total_calc
    return 0, total_calc, False

# --- ボタン処理 ---
if st.button("💡 見積もりを作成"):
    with st.spinner("AIが見積もりを作成中…"):
        resA = genai.GenerativeModel("gemini-2.0-flash").generate_content(promptA).text if model_choice == "Gemini" else openai_client.chat.completions.create(model=model, messages=[{"role": "user", "content": promptA}]).choices[0].message.content
        fullB = promptB + "\n" + resA
        resB = genai.GenerativeModel("gemini-2.0-flash").generate_content(fullB).text if model_choice == "Gemini" else openai_client.chat.completions.create(model=model, messages=[{"role": "user", "content": fullB}]).choices[0].message.content
        shown, calc, ok = extract_and_validate_total(resB)
        promptC = promptC_template.format(items_a=resA, items_b=resB)
        final = genai.GenerativeModel("gemini-2.0-flash").generate_content(promptC).text if model_choice == "Gemini" else openai_client.chat.completions.create(model=model, messages=[{"role": "user", "content": promptC}]).choices[0].message.content

        st.session_state["resA"] = resA
        st.session_state["resB"] = resB
        st.session_state["final_html"] = final

# --- 結果表示 ---
if st.session_state["final_html"]:
    st.success("✅ 見積もり結果")
    if st.session_state["resB"]:
        shown, calc, ok = extract_and_validate_total(st.session_state["resB"])
        if not ok:
            st.error(f"⚠️ 合計金額に不整合があります：表示 = {shown:,}円 / 再計算 = {calc:,}円")

    st.components.v1.html(st.session_state["final_html"].strip().removeprefix("```html").removesuffix("```"), height=900, scrolling=True)

    def convert_to_excel(text):
        data = []
        for line in text.split("\n"):
            m = re.search(r"(.+?)：単価([0-9,]+)円×数量([0-9]+).*＝([0-9,]+)円", line)
            if m:
                data.append([m.group(1), int(m.group(2).replace(",", "")), int(m.group(3)), int(m.group(4).replace(",", ""))])
        return pd.DataFrame(data, columns=["項目", "単価（円）", "数量", "金額（円）"])

    df = convert_to_excel(st.session_state["resB"])
    buf = BytesIO()
    df.to_excel(buf, index=False, sheet_name="見積もり")
    buf.seek(0)
    st.download_button("📥 Excelでダウンロード", buf, "見積もり.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
