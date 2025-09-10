# app.py （AI見積もりくん２ - Dela Gothic One & スプラ風テーマ版）
# GPT系のみ対応 / JSON強制 & 質問カテゴリフォールバック
# 追加要件込み再生成対応 / 追加質問時にプレビュー消去
# 見積もり生成後に「チャット入力欄の直上」にヒント文を必ず表示（st.emptyでプレースホルダ制御）

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
st.set_page_config(page_title="AI見積もりくん２", layout="centered")

# =========================
# スプラ風テーマCSS + Dela Gothic One 全体適用
# =========================
def splat_theme():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Dela+Gothic+One&display=swap');

    /* 全体をDela Gothic Oneで統一 */
    html, body, [class*="css"], .stApp, .stMarkdown, .stTextInput, .stButton, .stChatMessage {
        font-family: 'Dela Gothic One', sans-serif !important;
        letter-spacing: .02em;
        color: #fff !important;
    }

    :root{
      --pink:#FF2DFC; --green:#39FF14; --cyan:#00FAFF;
      --bg:#000; --panel:#101010; --panel2:#161616; --text:#fff;
    }

    .stApp{background:var(--bg);}
    .block-container{max-width: 920px; position:relative; z-index:1; padding-top:12px;}

    /* 見出しは文字そのものをグラデ塗り */
    h1,h2,h3{
      font-weight:900; line-height:1.15; margin:8px 0 12px;
      background:linear-gradient(90deg,var(--pink),var(--green),var(--cyan));
      -webkit-background-clip:text; -webkit-text-fill-color:transparent;
    }

    /* セクション見出しパネル（グラデ枠） */
    .splat-frame{
      border:3px solid transparent; border-radius:18px;
      padding:.7rem .95rem; margin:10px 0 14px;
      background:linear-gradient(var(--panel),var(--panel)) padding-box,
                 linear-gradient(90deg,var(--green),var(--cyan)) border-box;
    }

    /* ボタン（発光グラデ） */
    .stButton>button{
      background:linear-gradient(90deg,var(--pink),var(--green));
      border:none; border-radius:14px; color:#fff; font-weight:900;
      padding:.72rem 1.1rem;
      box-shadow:0 12px 28px rgba(0,255,170,.22), inset 0 0 14px rgba(255,255,255,.18);
      transition:transform .12s ease, box-shadow .2s ease, background .2s ease;
    }
    .stButton>button:hover{
      transform:translateY(-1px) scale(1.02);
      background:linear-gradient(90deg,var(--green),var(--cyan));
      box-shadow:0 16px 40px rgba(0,255,170,.3), inset 0 0 20px rgba(255,255,255,.22);
    }

    /* テキスト入力・アップローダ・チャット入力欄 */
    .stTextInput>div>div>input, .stFileUploader>div, .stChatInput textarea{
      background:var(--panel2);
      border:2px solid transparent; border-radius:12px;
      background:linear-gradient(var(--panel2),var(--panel2)) padding-box,
                 linear-gradient(90deg,var(--green),var(--cyan)) border-box;
      color:#fff;
    }
    .stChatInput [data-baseweb="button"]{
      background:linear-gradient(90deg,var(--pink),var(--green)); color:#fff; border:none; border-radius:12px;
    }

    /* チャット気泡 */
    [data-testid="stChatMessage"]{
      background:var(--panel2);
      border:2px solid transparent; border-radius:16px; padding:.6rem .8rem;
      background:linear-gradient(var(--panel2),var(--panel2)) padding-box,
                 linear-gradient(90deg,var(--pink),var(--green)) border-box;
      color:#fff !important;
    }

    /* DataFrame容器（グラデ枠） */
    [data-testid="stDataFrameResizable"]{
      border:2px solid transparent; border-radius:12px;
      background:linear-gradient(#0b0b0b,#0b0b0b) padding-box,
                 linear-gradient(90deg,var(--pink),var(--green)) border-box;
    }

    /* ロゴ風ヒーロー */
    .logo-pill{
      display:inline-flex; align-items:center; gap:.6rem;
      border:4px solid transparent; border-radius:26px; padding:.3rem .9rem; margin:4px 0 10px;
      background:linear-gradient(var(--bg),var(--bg)) padding-box,
                 linear-gradient(90deg,var(--pink),var(--cyan)) border-box;
    }
    .logo-ai{ font:900 1.7rem 'Dela Gothic One'; background:linear-gradient(90deg,var(--pink),var(--green));
              -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
    .logo-text{ font:900 1.25rem 'Dela Gothic One'; color:#fff; }

    /* ===== インク画像（/static/ink/*.png を使用） ===== */
    .ink-stage{ position:fixed; inset:0; pointer-events:none; z-index:0; }
    .ink{ position:absolute; width:360px; height:auto; opacity:.95; filter: drop-shadow(0 10px 28px rgba(0,255,170,.18)); }
    .ink-pink{  top:-60px; left:-80px; transform:rotate(-12deg); }
    .ink-green{ right:-80px; top:38%; transform:rotate(16deg) scale(.9); }
    .ink-cyan{  left:12%; bottom:-10px; transform:rotate(-18deg); }

    @media (max-width: 840px){ .ink{width:240px} .ink-green{top:46%} .ink-cyan{left:6%; bottom:-40px}}
    @media (max-width: 520px){ .ink{width:200px} .ink-pink{left:-110px} .ink-green{right:-70px; top:56%} .ink-cyan{left:2%;bottom:-60px}}
    </style>
    <div class="ink-stage">
      <img src="/static/ink/ink_pink.png"  class="ink ink-pink"/>
      <img src="/static/ink/ink_green.png" class="ink ink-green"/>
      <img src="/static/ink/ink_cyan.png"  class="ink ink-cyan"/>
    </div>
    """, unsafe_allow_html=True)

splat_theme()

# =========================
# Secrets
# =========================
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
APP_PASSWORD   = st.secrets["APP_PASSWORD"]
OPENAI_ORG_ID  = st.secrets.get("OPENAI_ORG_ID", None)

if not OPENAI_API_KEY:
    st.error("OPENAI_API_KEY が設定されていません。st.secrets を確認してください。")
    st.stop()

os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
if OPENAI_ORG_ID:
    os.environ["OPENAI_ORG_ID"] = OPENAI_ORG_ID

openai_client = OpenAI(http_client=httpx.Client(timeout=60.0))

# =========================
# 定数
# =========================
TAX_RATE = 0.10

# =========================
# セッション管理
# =========================
for k in ["chat_history", "items_json_raw", "items_json", "df", "meta"]:
    if k not in st.session_state:
        st.session_state[k] = None

if st.session_state["chat_history"] is None:
    st.session_state["chat_history"] = [
        {"role": "system", "content": "あなたは広告クリエイティブ制作のプロフェッショナルです。相場感をもとに見積もりを作成するため、ユーザーにヒアリングを行います。"},
        {"role": "assistant", "content": "こんにちは！こちらは「AI見積もりくん２」です。見積もり作成のために、まず案件概要を教えてください。"}
    ]

# =========================
# ヘッダー
# =========================
st.markdown('<div class="logo-pill"><span class="logo-ai">AI</span><span class="logo-text">見積もりくん２</span></div>', unsafe_allow_html=True)

# =========================
# 認証
# =========================
st.markdown('<div class="splat-frame"><h2>ログイン</h2></div>', unsafe_allow_html=True)
password = st.text_input("パスワードを入力してください", type="password")
if password != APP_PASSWORD:
    st.warning("🔒 認証が必要です")
    st.stop()

# =========================
# チャットUI
# =========================
st.markdown('<div class="splat-frame"><h2>チャットでヒアリング</h2></div>', unsafe_allow_html=True)

for msg in st.session_state["chat_history"]:
    if msg["role"] == "assistant":
        st.chat_message("assistant").write(msg["content"])
    elif msg["role"] == "user":
        st.chat_message("user").write(msg["content"])

# --- ヒント文プレースホルダ（チャット入力直前） ---
hint_placeholder = st.empty()
if st.session_state["df"] is not None:
    hint_placeholder.caption(
        "💡 チャットを続けると見積もり精度が上がります。追加要件を入力後に再生成してください。"
    )

# 入力欄
if user_input := st.chat_input("要件を入力してください..."):
    # 新しい入力があればプレビューを一度消す
    st.session_state["df"] = None
    st.session_state["meta"] = None
    st.session_state["items_json"] = None
    st.session_state["items_json_raw"] = None

    st.session_state["chat_history"].append({"role": "user", "content": user_input})

    with st.chat_message("user"):
        st.write(user_input)

    with st.chat_message("assistant"):
        with st.spinner("AIが考えています..."):
            resp = openai_client.chat.completions.create(
                model="gpt-4.1",
                messages=st.session_state["chat_history"],
                temperature=0.4,
                max_tokens=1200
            )
            reply = resp.choices[0].message.content
            st.write(reply)
            st.session_state["chat_history"].append({"role": "assistant", "content": reply})

# =========================
# 見積もり生成用プロンプト
# =========================
def build_prompt_for_estimation(chat_history):
    return f"""
必ず有効な JSON のみを返してください。説明文・文章・Markdown・テーブルは禁止です。

あなたは広告制作の見積もり作成エキスパートです。
以下の会話履歴をもとに、見積もりの内訳を作成してください。

【会話履歴】
{json.dumps(chat_history, ensure_ascii=False, indent=2)}

【カテゴリ例】
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
- 必ず items 配列には1行以上の見積もり項目を返してください（空配列は禁止）。
- 各要素キー: category / task / qty / unit / unit_price / note
- 欠損がある場合は補完してください。
- 「管理費」は必ず含める（task=管理費（固定）, qty=1, unit=式）。
- 合計や税は含めない。
- もし情報不足で正しい見積もりが作れない場合は、items に1行だけ
  {{"category":"質問","task":"追加で必要な情報を教えてください","qty":0,"unit":"","unit_price":0,"note":"不足情報あり"}}
  を返してください。
"""

# =========================
# JSONパース & フォールバック
# =========================
def robust_parse_items_json(raw: str) -> str:
    try:
        obj = json.loads(raw)
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

# =========================
# DataFrame生成
# =========================
def df_from_items_json(items_json: str) -> pd.DataFrame:
    try:
        data = json.loads(items_json) if items_json else {}
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
    df = pd.DataFrame(norm)
    for col in ["category", "task", "qty", "unit", "unit_price", "note"]:
        if col not in df.columns:
            df[col] = "" if col in ["category","task","unit","note"] else 0
    if not df.empty:
        df["qty"] = pd.to_numeric(df["qty"], errors="coerce").fillna(0).astype(float)
        df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce").fillna(0).astype(int)
        df["小計"] = (df["qty"] * df["unit_price"]).astype(int)
    return df

# =========================
# 合計計算
# =========================
def compute_totals(df: pd.DataFrame):
    taxable = int(df["小計"].sum())
    tax = int(round(taxable * TAX_RATE))
    total = taxable + tax
    return {"taxable": taxable, "tax": tax, "total": total}

# =========================
# DDテンプレ出力
# =========================
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

# =========================
# 実行
# =========================
has_user_input = any(msg["role"]=="user" for msg in st.session_state["chat_history"])

if has_user_input:
    st.markdown('<div class="splat-frame"><h2>AI見積もりを生成</h2></div>', unsafe_allow_html=True)
    if st.button("📝 AI見積もりくんで見積もりを生成する"):
        with st.spinner("AIが見積もりを生成中…"):
            prompt = build_prompt_for_estimation(st.session_state["chat_history"])
            resp = openai_client.chat.completions.create(
                model="gpt-4.1",
                messages=[{"role":"system","content":"You MUST return only valid JSON."},
                          {"role":"user","content":prompt}],
                response_format={"type":"json_object"},
                temperature=0.2,
                max_tokens=4000
            )
            raw = resp.choices[0].message.content or '{"items":[]}'
            items_json = robust_parse_items_json(raw)
            df = df_from_items_json(items_json)

            if df.empty:
                st.warning("見積もりを出せませんでした。追加で要件を教えてください。")
            else:
                meta = compute_totals(df)
                st.session_state["items_json_raw"] = raw
                st.session_state["items_json"] = items_json
                st.session_state["df"] = df
                st.session_state["meta"] = meta

                # 生成直後にヒント文を表示
                hint_placeholder.caption(
                    "💡 チャットを続けて見積もり精度を上げられます。追加要件を入力後に再生成してください。"
                )

# =========================
# 表示 & ダウンロード
# =========================
if st.session_state["df"] is not None:
    st.markdown('<div class="splat-frame"><h2>見積もり結果プレビュー</h2></div>', unsafe_allow_html=True)
    st.success("✅ 見積もり結果プレビュー")
    st.dataframe(st.session_state["df"])
    st.write(f"**小計（税抜）:** {st.session_state['meta']['taxable']:,}円")
    st.write(f"**消費税:** {st.session_state['meta']['tax']:,}円")
    st.write(f"**合計:** {st.session_state['meta']['total']:,}円")

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        st.session_state["df"].to_excel(writer, index=False, sheet_name="見積もり")
    buf.seek(0)
    st.download_button("📥 Excelでダウンロード", buf, "見積もり.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.markdown('<div class="splat-frame"><h2>DD見積書テンプレート出力</h2></div>', unsafe_allow_html=True)
    tmpl = st.file_uploader("DD見積書テンプレートをアップロード（.xlsx）", type=["xlsx"])
    if tmpl is not None:
        out = export_with_template(tmpl.read(), st.session_state["df"])
        st.download_button("📥 DD見積書テンプレで出力", out, "見積もり_DDテンプレ.xlsx")
