# app.py（AI見積もりくん２ / Neon Splash Theme・安定版）
# - OpenAI GPT系（gpt-4.1）で見積り生成
# - チャット継続 → 再生成で「履歴＋新要件」を反映
# - 追加入力時はプレビューを一旦クリア
# - Excelダウンロード／DD見積テンプレ出力対応
# - CSSは markdown(unsafe_allow_html=True) のみで注入（st.html/iframe不使用）

import os
import json
from io import BytesIO

import pandas as pd
import streamlit as st
from openpyxl import load_workbook
from openpyxl.styles import Font
from openpyxl.utils import column_index_from_string, get_column_letter

from openai import OpenAI
import httpx

# =========================
# ページ設定
# =========================
st.set_page_config(page_title="AI見積もりくん２", layout="wide", page_icon="💥")

# =========================
# OpenAI / Secrets
# =========================
# .streamlit/secrets.toml 例:
# OPENAI_API_KEY="sk-..."
# APP_PASSWORD="your-password"
# OPENAI_ORG_ID="(任意)"
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
APP_PASSWORD   = st.secrets["APP_PASSWORD"]
OPENAI_ORG_ID  = st.secrets.get("OPENAI_ORG_ID", None)

if not OPENAI_API_KEY:
    st.error("OPENAI_API_KEY が設定されていません。")
    st.stop()

os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
if OPENAI_ORG_ID:
    os.environ["OPENAI_ORG_ID"] = OPENAI_ORG_ID

openai_client = OpenAI(http_client=httpx.Client(timeout=60.0))

# =========================
# 税率など
# =========================
TAX_RATE = 0.10

# =========================
# CSS をグローバル注入（markdownのみ）
# =========================
CSS = """
:root{
  --bg:#0D0F16; --panel:#151827; --panel-2:#171b2e; --border:#2a2f4a;
  --ink:#B7FF00; --pink:#FF2EBF; --cyan:#00F0FF; --vio:#7A00FF; --text:#F3F6FF; --muted:#A7B1D6;
}
html, body { background: var(--bg); color: var(--text); }
* { font-family: "Noto Sans JP","Zen Maru Gothic","Bungee", system-ui, -apple-system, Segoe UI, Roboto, sans-serif !important; }
.block-container { padding-top: 0.8rem; }

/* 背景ネオン */
body::before{
  content:""; position:fixed; inset:-10% -10% auto auto; width:1000px; height:700px;
  background:
    radial-gradient(650px 350px at 15% 0%, rgba(39,74,161,.25) 0%, transparent 60%),
    radial-gradient(600px 320px at 90% 5%, rgba(122,0,255,.18) 0%, transparent 60%),
    radial-gradient(600px 320px at 80% 70%, rgba(0,240,255,.12) 0%, transparent 60%);
  filter: blur(14px); pointer-events:none; z-index:-1;
}

/* タイトル */
.header-wrap{ display:flex; align-items:center; gap:.75rem; margin:.4rem 0 1rem 0; }
.logo-dot{ width:14px; height:14px; border-radius:50%; background: conic-gradient(var(--ink), var(--cyan), var(--vio), var(--pink), var(--ink)); box-shadow:0 0 14px rgba(0,240,255,.6); }
.app-title{ font-family:"Bungee","Zen Maru Gothic",sans-serif !important; font-weight:700; letter-spacing:.2px; font-size:1.6rem; }
.badge{
  display:inline-flex; gap:.5rem; align-items:center; padding:.35rem .7rem; border-radius:999px;
  background:linear-gradient(135deg, var(--pink), var(--vio)); color:white; font-weight:700; border:2px solid rgba(255,255,255,.15);
  filter: drop-shadow(0 0 8px rgba(255,46,191,.45));
}

/* カード */
.panel{
  background: linear-gradient(180deg, var(--panel), var(--panel-2));
  border: 1px solid var(--border); border-radius: 18px; padding: 16px 16px;
  box-shadow: 0 12px 28px rgba(0,0,0,.35);
}

/* DataFrameの外枠だけ整える */
div[data-testid="stDataFrame"]{
  background: transparent; border-radius: 14px; border: 1px solid var(--border);
  box-shadow: inset 0 0 0 1px rgba(255,255,255,.03);
}

/* ボタン */
.stButton > button {
  background: radial-gradient(120% 150% at 30% 10%, var(--ink), var(--cyan) 60%, var(--vio) 100%);
  color:#0b1020; font-weight:800; border:none; border-radius:16px; padding:.9rem 1.2rem;
  box-shadow: 0 10px 24px rgba(183,255,0,.25), inset 0 -4px 10px rgba(0,0,0,.25);
  transform: translateY(0); transition:.15s ease-in-out;
}
.stButton > button:hover { transform: translateY(-2px) scale(1.03); filter:saturate(1.2) drop-shadow(0 0 8px rgba(0,240,255,.5)); }
.stButton > button:active { transform: translateY(0); }

/* 入力欄 */
.stTextInput input, .stChatInput input, textarea{
  background:#101329; border:2px solid #2b2f46; color:var(--text); border-radius:14px;
}
.stTextInput input:focus, .stChatInput input:focus, textarea:focus {
  border-color: var(--cyan); box-shadow: 0 0 0 3px rgba(0,240,255,.25);
}

/* サブテキスト／区切り */
.small { color: var(--muted); font-size:.9rem; }
.hr { height:1px; background:linear-gradient(90deg, transparent, #2a2f4a, transparent); margin: 10px 0 16px 0; }
"""

def inject_global_css(css_text: str):
    """グローバルCSS注入（markdownのみ。st.html/iframeは使わない）"""
    st.markdown(f"<style>{css_text}</style>", unsafe_allow_html=True)

# フォント読み込み + CSS 注入（ページ冒頭で必ず実行）
st.markdown(
    '<link href="https://fonts.googleapis.com/css2?family=Bungee:wght@400;700&family=Zen+Maru+Gothic:wght@400;700&family=Noto+Sans+JP:wght@400;600&display=swap" rel="stylesheet">',
    unsafe_allow_html=True
)
inject_global_css(CSS)

# =========================
# セッション初期化
# =========================
for k in ["chat_history", "items_json_raw", "items_json", "df", "meta"]:
    if k not in st.session_state:
        st.session_state[k] = None

if st.session_state["chat_history"] is None:
    st.session_state["chat_history"] = [
        {"role": "system", "content": "あなたは広告クリエイティブ制作のプロフェッショナルです。相場感に基づき、必要なヒアリングを行い、概算見積もりを作成します。"},
        {"role": "assistant", "content": "ようこそ！こちらは「AI見積もりくん２」です。案件の目的・媒体・納期・参考予算など、まずはわかる範囲で教えてください。"}
    ]

# =========================
# ヘッダー & 認証
# =========================
st.markdown(
    '<div class="header-wrap"><div class="logo-dot"></div>'
    '<div class="app-title">AI見積もりくん２</div>'
    '<span class="badge">NEON SPLASH THEME</span></div>',
    unsafe_allow_html=True
)

with st.expander("🔒 サインイン", expanded=True):
    password = st.text_input("パスワードを入力してください", type="password")
    if password != APP_PASSWORD:
        st.warning("認証が必要です")
        st.stop()

# =========================
# レイアウト
# =========================
col_chat, col_preview = st.columns([1.35, 1.0], gap="large")

# ---------- チャット ----------
with col_chat:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.subheader("💬 チャットでヒアリング", anchor=False)
    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)

    for msg in st.session_state["chat_history"]:
        if msg["role"] == "assistant":
            st.chat_message("assistant").write(msg["content"])
        elif msg["role"] == "user":
            st.chat_message("user").write(msg["content"])

    # 生成後ヒント
    hint_placeholder = st.empty()
    if st.session_state["df"] is not None:
        hint_placeholder.caption(
            "💡 チャットをさらに続けて見積もり精度を上げることができます。\n"
            "追加で要件を入力した後に再度このボタンを押すと、過去のチャット履歴＋新しい要件を反映して見積もりが更新されます。"
        )

    user_input = st.chat_input("要件を入力してください…")
    if user_input:
        # 追加入力 → プレビューを一旦クリア
        st.session_state["df"] = None
        st.session_state["meta"] = None
        st.session_state["items_json"] = None
        st.session_state["items_json_raw"] = None

        st.session_state["chat_history"].append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.write(user_input)

        with st.chat_message("assistant"):
            with st.spinner("AIが考えています…"):
                resp = openai_client.chat.completions.create(
                    model="gpt-4.1",
                    messages=st.session_state["chat_history"],
                    temperature=0.4,
                    max_tokens=1200
                )
                reply = resp.choices[0].message.content
                st.write(reply)
                st.session_state["chat_history"].append({"role": "assistant", "content": reply})

    st.markdown('</div>', unsafe_allow_html=True)

# ---------- 見積もり ----------
with col_preview:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.subheader("📑 見積もり", anchor=False)
    st.markdown('<div class="small">好きなタイミングで生成できます（AIが不足を推測します）</div>', unsafe_allow_html=True)
    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)

    def build_prompt_for_estimation(chat_history):
        return f"""
必ず有効な JSON のみを返してください。説明文・文章・Markdown・テーブルは禁止です。

あなたは広告制作の見積もり作成エキスパートです。
以下の会話履歴をもとに、見積もりの内訳を作成してください。

【会話履歴】
{json.dumps(chat_history, ensure_ascii=False, indent=2)}

【カテゴリ例】（案件に応じて最適化・追加可）
- 企画・戦略関連（企画費、リサーチ費、コピーライティング、ディレクション など）
- デザイン・クリエイティブ制作（デザイン費、アートディレクション、イラスト制作 など）
- 撮影・映像関連（撮影費、スタッフ費、出演費、撮影機材費 など）
- 編集・仕上げ（編集費、CG/VFX、MA、字幕制作 など）
- Web関連（コーディング、CMS実装、テスト・QA、サーバー費 など）
- 配信・媒体関連（媒体出稿費、配信管理費、広告審査費 など）
- プロモーション・イベント関連（イベント運営費、会場費、施工費、スタッフ派遣 など）
- 諸経費・共通項目（交通費、宿泊費、消耗品費、雑費 など）
- 管理費（固定・一式）

【ルール】
- items 配列には1行以上の見積もり項目を返すこと（空配列は禁止）。
- 各要素キー: category / task / qty / unit / unit_price / note
- 欠損がある場合は補完すること。
- 「管理費」は必ず含める（task=管理費（固定）, qty=1, unit=式）。
- 合計や税は含めない。
- もし情報不足で正しい見積もりが作れない場合は、items に1行だけ
  {{"category":"質問","task":"追加で必要な情報を教えてください","qty":0,"unit":"","unit_price":0,"note":"不足情報あり"}}
  を返すこと。
"""

    has_user_input = any(m["role"] == "user" for m in st.session_state["chat_history"])
    if has_user_input and st.button("📝 AI見積もりくんで見積もりを生成する", use_container_width=True):
        with st.spinner("AIが見積もりを生成中…"):
            prompt = build_prompt_for_estimation(st.session_state["chat_history"])
            resp = openai_client.chat.completions.create(
                model="gpt-4.1",
                messages=[
                    {"role":"system","content":"You MUST return only valid JSON."},
                    {"role":"user","content":prompt}
                ],
                response_format={"type":"json_object"},
                temperature=0.2,
                max_tokens=4000
            )
            raw = resp.choices[0].message.content or '{"items":[]}'
            st.session_state["items_json_raw"] = raw

            # JSONロバストパース
            def robust_parse_items_json(raw_text: str) -> str:
                try:
                    obj = json.loads(raw_text)
                except Exception:
                    return json.dumps({
                        "items":[
                            {"category":"質問","task":"要件を詳しく教えてください","qty":0,"unit":"","unit_price":0,"note":"AIがテキストを返しました"}
                        ]
                    }, ensure_ascii=False)
                if not isinstance(obj, dict):
                    obj = {"items":[]}
                if "items" not in obj or not obj["items"]:
                    obj["items"] = [{
                        "category":"質問","task":"追加で要件を教えてください","qty":0,"unit":"","unit_price":0,"note":"不足情報あり"
                    }]
                return json.dumps(obj, ensure_ascii=False)

            items_json = robust_parse_items_json(raw)

            # DataFrame化
            def df_from_items_json(items_json_str: str) -> pd.DataFrame:
                try:
                    data = json.loads(items_json_str) if items_json_str else {}
                except Exception:
                    data = {}
                items = data.get("items", []) or []
                norm = []
                for x in items:
                    norm.append({
                        "category": str((x or {}).get("category", "")),
                        "task": str((x or {}).get("task", "")),
                        "qty": (x or {}).get("qty", 0) or 0,
                        "unit": str((x or {}).get("unit", "")),
                        "unit_price": (x or {}).get("unit_price", 0) or 0,
                        "note": str((x or {}).get("note", "")),
                    })
                df_local = pd.DataFrame(norm)
                for col in ["category", "task", "qty", "unit", "unit_price", "note"]:
                    if col not in df_local.columns:
                        df_local[col] = "" if col in ["category","task","unit","note"] else 0
                df_local["qty"] = pd.to_numeric(df_local["qty"], errors="coerce").fillna(0).astype(float)
                df_local["unit_price"] = pd.to_numeric(df_local["unit_price"], errors="coerce").fillna(0).astype(int)
                df_local["小計"] = (df_local["qty"] * df_local["unit_price"]).astype(int)
                return df_local

            df = df_from_items_json(items_json)

            if df.empty:
                st.warning("見積もりを出せませんでした。追加で要件を教えてください。")
            else:
                def compute_totals(df_items: pd.DataFrame):
                    taxable = int(df_items["小計"].sum())
                    tax = int(round(taxable * TAX_RATE))
                    total = taxable + tax
                    return {"taxable": taxable, "tax": tax, "total": total}

                meta = compute_totals(df)
                st.session_state["items_json"] = items_json
                st.session_state["df"] = df
                st.session_state["meta"] = meta

                # 生成直後にもヒントを表示
                hint_placeholder.caption(
                    "💡 チャットをさらに続けて見積もり精度を上げることができます。\n"
                    "追加で要件を入力した後に再度このボタンを押すと、過去のチャット履歴＋新しい要件を反映して見積もりが更新されます。"
                )

    # プレビュー & ダウンロード
    if st.session_state["df"] is not None:
        st.success("✅ 見積もり結果プレビュー")
        st.dataframe(st.session_state["df"], use_container_width=True)

        st.markdown('<div class="hr"></div>', unsafe_allow_html=True)
        st.write(f"**小計（税抜）:** {st.session_state['meta']['taxable']:,}円")
        st.write(f"**消費税:** {st.session_state['meta']['tax']:,}円")
        st.write(f"**合計:** {st.session_state['meta']['total']:,}円")

        # Excel ダウンロード
        buf = BytesIO()
        with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
            st.session_state["df"].to_excel(writer, index=False, sheet_name="見積もり")
        buf.seek(0)
        st.download_button(
            "📥 Excelでダウンロード", buf, "見積もり.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

        st.markdown('<div class="hr"></div>', unsafe_allow_html=True)

        # ====== DD見積書テンプレ出力 ======
        st.subheader("🧾 DD見積書テンプレで出力", anchor=False)
        st.caption("テンプレートの明細1行目に `{{ITEMS_START}}` を置いてください。")
        tmpl = st.file_uploader("DD見積書テンプレート（.xlsx）をアップロード", type=["xlsx"])

        TOKEN_ITEMS = "{{ITEMS_START}}"
        COLMAP = {"task": "B", "qty": "O", "unit": "Q", "unit_price": "S", "amount": "W"}

        def _find_token(ws, token: str):
            for row in ws.iter_rows(values_only=False):
                for cell in row:
                    if isinstance(cell.value, str) and cell.value.strip() == token:
                        return cell.row, cell.column
            return None, None

        def _ensure_amount_formula(ws, row, qty_col_idx, price_col_idx, amount_col_idx):
            c = ws.cell(row=row, column=amount_col_idx)
            qcol = get_column_letter(qty_col_idx)
            pcol = get_column_letter(price_col_idx)
            c.value = f"={qcol}{row}*{pcol}{row}"
            c.number_format = '#,##0'

        def _write_items_to_template(ws, df_items: pd.DataFrame):
            r0, c0 = _find_token(ws, TOKEN_ITEMS)
            if r0:
                ws.cell(row=r0, column=c0).value = None
            start_row = r0 or 19

            c_task = column_index_from_string(COLMAP["task"])
            c_qty  = column_index_from_string(COLMAP["qty"])
            c_unit = column_index_from_string(COLMAP["unit"])
            c_price= column_index_from_string(COLMAP["unit_price"])
            c_amt  = column_index_from_string(COLMAP["amount"])

            r = start_row
            current_cat = None
            for _, row in df_items.iterrows():
                cat = str(row.get("category", "")) or ""
                if cat != current_cat:
                    ws.cell(row=r, column=c_task).value = cat
                    ws.cell(row=r, column=c_task).font = Font(bold=True)
                    _ensure_amount_formula(ws, r, c_qty, c_price, c_amt)
                    current_cat = cat
                    r += 1
                ws.cell(row=r, column=c_task).value  = str(row.get("task",""))
                ws.cell(row=r, column=c_qty).value   = float(row.get("qty", 0) or 0)
                ws.cell(row=r, column=c_unit).value  = str(row.get("unit",""))
                ws.cell(row=r, column=c_price).value = int(float(row.get("unit_price", 0) or 0))
                _ensure_amount_formula(ws, r, c_qty, c_price, c_amt)
                r += 1

        def export_with_template(template_bytes: bytes, df_items: pd.DataFrame):
            wb = load_workbook(filename=BytesIO(template_bytes))
            ws = wb.active
            _write_items_to_template(ws, df_items)
            out = BytesIO()
            wb.save(out)
            out.seek(0)
            return out

        if tmpl is not None:
            out = export_with_template(tmpl.read(), st.session_state["df"])
            st.download_button("📥 DD見積書テンプレで出力", out, "見積もり_DDテンプレ.xlsx",
                               use_container_width=True)

    st.markdown('</div>', unsafe_allow_html=True)
