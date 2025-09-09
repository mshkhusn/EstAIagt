import streamlit as st
import pandas as pd
from io import BytesIO

# ページ設定
st.set_page_config(page_title="概算見積（柔軟版：Gemini 2.5 Flash）", layout="wide")

st.title("概算見積（柔軟版：Gemini 2.5 Flash）")

# 入力UI
with st.form("input_form"):
    col1, col2, col3 = st.columns(3)

    with col1:
        length = st.selectbox("尺の長さ", ["15秒", "30秒", "60秒"], index=1)
        deliverables = st.number_input("納品本数", 1, 10, 1)

    with col2:
        shoot_days = st.number_input("撮影日数", 0, 10, 2)
        edit_days = st.number_input("編集日数", 0, 10, 3)

    with col3:
        note_input = st.text_area("備考（自由記入）", placeholder="例: インタビューなし、スタジオ撮影、MAあり")

    video_only = st.checkbox("映像ドメインに限定（印刷/媒体/Web を含めない）")

    submitted = st.form_submit_button("▶ 見積アイテムを生成（Gemini 2.5 Flash）")

# ===== セッション初期化 =====
st.session_state.setdefault("df_view", None)

# ====== ダミー生成処理（本来は Gemini 2.5 Flash を呼ぶ） ======
if submitted:
    # ここは AI 出力を受け取る部分に置き換えてください
    items = [
        {"category": "制作費", "task": "企画構成費", "qty": 1, "unit": "式", "unit_price": 50000,
         "note": "構成案作成、絵コンテ、スケジュール調整"},
        {"category": "撮影費", "task": "ディレクター費", "qty": shoot_days, "unit": "日", "unit_price": 70000,
         "note": "撮影現場での演出・進行管理"},
        {"category": "撮影費", "task": "カメラマン費", "qty": shoot_days, "unit": "日", "unit_price": 80000,
         "note": "撮影機材一式（カメラ、レンズ、三脚含む）"},
        {"category": "撮影費", "task": "撮影助手費", "qty": shoot_days, "unit": "日", "unit_price": 40000,
         "note": "機材運搬、セッティング、補助業務"},
        {"category": "編集費・MA費", "task": "編集費", "qty": edit_days, "unit": "日", "unit_price": 70000,
         "note": "オフライン編集、オンライン編集、テロップ作成"},
        {"category": "編集費・MA費", "task": "MA費", "qty": 1, "unit": "式", "unit_price": 30000,
         "note": "BGM・効果音選定、ナレーション収録"},
        {"category": "管理費", "task": "制作進行管理費", "qty": 1, "unit": "式", "unit_price": 50000,
         "note": "プロジェクト全体の進行管理、品質管理"},
    ]

    df = pd.DataFrame(items)
    df["amount"] = df["qty"] * df["unit_price"]

    # セッションに保存
    st.session_state["df_view"] = df

# ====== 表示ブロック ======
if st.session_state["df_view"] is not None:
    df_view = st.session_state["df_view"]

    subtotal = int(df_view["amount"].sum())
    tax = int(subtotal * 0.1)
    total = subtotal + tax

    # データフレーム表示（横幅見切れ防止）
    pd.set_option("display.max_colwidth", 10**6)
    st.dataframe(
        df_view,
        use_container_width=True,
        height=360,
        column_config={
            "category": st.column_config.TextColumn("カテゴリ", width="small"),
            "task": st.column_config.TextColumn("項目", width="medium"),
            "qty": st.column_config.NumberColumn("数量", width="small"),
            "unit": st.column_config.TextColumn("単位", width="small"),
            "unit_price": st.column_config.NumberColumn("単価", width="small"),
            "amount": st.column_config.NumberColumn("金額（円）", width="small"),
            "note": st.column_config.TextColumn("note（内訳）", width="large"),
        },
    )

    st.markdown(
        f"**小計（税抜）:** {subtotal:,} 円 ／ **消費税:** {tax:,} 円 ／ **合計:** {total:,} 円"
    )

    # ====== Excel ダウンロード ======
    buf = BytesIO()
    out = df_view.copy()
    out = out[["category", "task", "qty", "unit", "unit_price", "amount", "note"]]

    try:
        import xlsxwriter
        engine = "xlsxwriter"
    except ModuleNotFoundError:
        engine = "openpyxl"

    with pd.ExcelWriter(buf, engine=engine) as writer:
        out.to_excel(writer, index=False, sheet_name="見積アイテム")
        if engine == "xlsxwriter":
            wb = writer.book
            ws = writer.sheets["見積アイテム"]
            fmt_int = wb.add_format({"num_format": "#,##0"})
            ws.set_column("A:B", 14)
            ws.set_column("C:E", 10, fmt_int)
            ws.set_column("F:F", 14, fmt_int)
            ws.set_column("G:G", 60)
        else:
            ws = writer.book["見積アイテム"]
            ws.column_dimensions["A"].width = 14
            ws.column_dimensions["B"].width = 20
            ws.column_dimensions["C"].width = 8
            ws.column_dimensions["D"].width = 8
            ws.column_dimensions["E"].width = 12
            ws.column_dimensions["F"].width = 14
            ws.column_dimensions["G"].width = 60

    buf.seek(0)
    st.download_button(
        "📥 Excelダウンロード（note入り）",
        data=buf,
        file_name="見積アイテム.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="dl_items_excel",
    )
else:
    st.info("まだ見積アイテムがありません。上部のボタンで生成してください。")
