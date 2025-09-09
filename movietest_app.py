# movie_app.py — Gemini 2.5 Flash 専用・構造化出力＆SAFETY診断つき検証版
import os, re, json, ast
from io import BytesIO
from datetime import date
from typing import Any, Dict, List, Optional

import streamlit as st
import pandas as pd
import google.generativeai as genai
from dateutil.relativedelta import relativedelta

# ================= 基本設定 =================
st.set_page_config(page_title="映像制作概算見積（Gemini 2.5 Flash 検証版）", layout="centered")

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
APP_PASSWORD   = st.secrets.get("APP_PASSWORD", "")

if not GEMINI_API_KEY:
    st.error("GEMINI_API_KEY が未設定です。")
    st.stop()

genai.configure(api_key=GEMINI_API_KEY)
MODEL_ID = "gemini-2.5-flash"

TAX_RATE = 0.10
MGMT_FEE_CAP_RATE = 0.15
RUSH_K = 0.75

for k in ["df","meta","final_html","debug_runs"]:
    if k not in st.session_state: st.session_state[k] = None

# ================= 認証 =================
st.title("映像制作概算見積（2.5 Flash / 構造化出力・SAFETY診断）")
if APP_PASSWORD:
    if st.text_input("パスワード", type="password") != APP_PASSWORD:
        st.warning("🔒 認証が必要です")
        st.stop()

# ================= 入力 =================
st.header("制作条件の入力")
video_duration = st.selectbox("尺の長さ", ["15秒","30秒","60秒","その他"])
final_duration = st.text_input("尺（自由記入）") if video_duration=="その他" else video_duration
num_versions = st.number_input("納品本数", 1, 10, 1)
shoot_days   = st.number_input("撮影日数", 1, 10, 2)
edit_days    = st.number_input("編集日数", 1, 10, 3)
delivery_date= st.date_input("納品希望日", value=date.today()+relativedelta(months=1))

cast_main  = st.number_input("メインキャスト人数", 0, 10, 1)
cast_extra = st.number_input("エキストラ人数", 0, 30, 0)
talent_use = st.checkbox("タレント起用あり")

default_roles = ["制作プロデューサー","制作PM","ディレクター","カメラマン","照明","スタイリスト","ヘアメイク"]
selected_roles = st.multiselect("必要スタッフ", default_roles, default=default_roles)
custom_roles = [s.strip() for s in st.text_input("その他スタッフ（カンマ区切り）").split(",") if s.strip()]
staff_roles = selected_roles + custom_roles

shoot_location = st.text_input("撮影場所（例：都内スタジオ＋ロケ）")
kizai = st.multiselect("撮影機材", ["4Kカメラ","照明","ドローン","グリーンバック"], default=["4Kカメラ","照明"])
set_design_quality = st.selectbox("セット/美術規模", ["なし","小（簡易）","中（通常）","大（本格）"])
use_cg = st.checkbox("CG・VFXあり"); use_narration = st.checkbox("ナレーションあり")
use_music = st.selectbox("音楽素材", ["既存ライセンス","オリジナル制作","未定"])
ma_needed = st.checkbox("MAあり")
deliverables = st.multiselect("納品形式", ["mp4（16:9）","mp4（1:1）","mp4（9:16）","ProRes"])
subtitle_langs = st.multiselect("字幕言語", ["日本語","英語","その他"])
usage_region = st.selectbox("使用地域", ["日本国内","グローバル","未定"])
usage_period = st.selectbox("使用期間", ["3ヶ月","6ヶ月","1年","2年","無期限","未定"])
budget_hint = st.text_input("参考予算（税抜・任意）")
extra_notes = st.text_area("備考")

do_infer_from_notes = st.checkbox("備考から付随項目を補完（推奨）", value=True)

# ================= ユーティリティ =================
def join_or(v, empty="なし", sep=", "): return sep.join(map(str,v)) if v else empty

def rush_coeff(base_days:int, target_days:int)->float:
    if target_days >= base_days or base_days<=0: return 1.0
    r = (base_days-target_days)/base_days
    return round(1 + RUSH_K*r, 2)

def parse_budget_hint_jpy(s:str)->Optional[int]:
    if not s: return None
    t = str(s).strip().replace(",","").replace(" ","").replace("円","")
    try:
        if "億" in t: return int(float(t.replace("億","") or "0") * 100_000_000)
        if "万" in t: return int(float(t.replace("万円","").replace("万","") or "0") * 10_000)
        return int(float(t))
    except: return None

def _strip_code_fences(s:str)->str:
    s=s.strip()
    if s.startswith("```"):
        s=re.sub(r"^```(json)?\s*","",s,flags=re.I); s=re.sub(r"\s*```$","",s)
    return s.strip()

def robust_parse_items_json(raw:str)->str:
    s=_strip_code_fences(raw)
    try: obj=json.loads(s)
    except:
        try:
            first=s.find("{"); last=s.rfind("}")
            if first!=-1 and last!=-1 and last>first:
                frag = s[first:last+1]
                frag = re.sub(r",\s*([}\]])", r"\1", frag)
                frag = frag.replace("\r","")
                frag = re.sub(r"\bTrue\b","true",frag); frag=re.sub(r"\bFalse\b","false",frag)
                frag = re.sub(r"\bNone\b","null",frag)
                if "'" in frag and '"' not in frag: frag=frag.replace("'","\"")
                obj=json.loads(frag)
            else: obj={"items":[]}
        except: obj={"items":[]}
    if not isinstance(obj,dict): obj={"items":[]}
    items = obj.get("items") if isinstance(obj.get("items"),list) else []
    return json.dumps({"items":items}, ensure_ascii=False)

# ================= プロンプト =================
STRICT_JSON_HEADER = (
    "この会話の内容は広告や映像制作に関する**一般的な費用項目**のみです。"
    "人物属性・成人向け・暴力・危険行為・誹謗中傷などの機微内容は一切扱いません。"
    "必ず **コードフェンスなし** の **JSON 1オブジェクト**のみを返してください。"
    "説明文は不要。判断に迷う場合は {\"items\": []} を返してください。"
)

def _case_block()->str:
    return f"""【案件条件】
- 尺: {final_duration} ／ 本数: {num_versions}
- 撮影: {shoot_days}日 ／ 編集: {edit_days}日 ／ 納品: {delivery_date.isoformat()}
- キャスト: メイン{cast_main}人 / エキストラ{cast_extra}人 / タレント: {"あり" if talent_use else "なし"}
- スタッフ候補: {join_or(staff_roles,"未指定")}
- 撮影場所: {shoot_location or "未定"} ／ 撮影機材: {join_or(kizai,"未指定")}
- 美術: {set_design_quality} ／ CG: {"あり" if use_cg else "なし"} ／ ナレーション: {"あり" if use_narration else "なし"}
- 音楽: {use_music} ／ MA: {"あり" if ma_needed else "なし"} ／ 納品形式: {join_or(deliverables,"未定")}
- 字幕: {join_or(subtitle_langs,"なし")} ／ 使用地域: {usage_region} ／ 使用期間: {usage_period}
- 参考予算（税抜）: {budget_hint or "未設定"}
- 備考: {extra_notes or "特になし"}"""

def _inference_line()->str:
    return ("\n- 未指定の付随項目は、一般的な広告映像の慣行に基づき妥当な範囲で補ってください。"
            if do_infer_from_notes else "")

def build_prompt()->str:
    return f"""{STRICT_JSON_HEADER}

あなたは広告映像の**概算見積の項目**を作成します。**JSONのみ**を返してください。

{_case_block()}

【出力仕様】
- ルート: items（配列）
- 各要素キー: category / task / qty / unit / unit_price / note
- category は「制作人件費」「企画」「撮影費」「出演関連費」「編集費・MA費」「諸経費」「管理費」
- qty/unit は日・式・人・時間・カット等の妥当な単位
- 単価は一般的な相場レンジで推定
- 管理費は固定1行（task=管理費（固定）, qty=1, unit=式）
{_inference_line()}
"""

# ================= Gemini 呼び出し（多段試行＋記録） =================
RESPONSE_SCHEMA = {
  "type": "object",
  "properties": {
    "items": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "category": {"type": "string"},
          "task": {"type": "string"},
          "qty": {"type": "number"},
          "unit": {"type": "string"},
          "unit_price": {"type": "number"},
          "note": {"type": "string"}
        },
        "required": ["category","task","qty","unit","unit_price"]
      }
    }
  },
  "required": ["items"]
}

def _safety(permissive: bool):
    if not permissive: return None
    try:
        from google.generativeai.types import HarmCategory, HarmBlockThreshold
        return {
            HarmCategory.HARM_CATEGORY_SEXUAL: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }
    except: return None

def _finish_reason_name(d: Dict[str,Any])->str:
    try:
        cand = (d.get("candidates") or [{}])[0]
        fr = cand.get("finish_reason", 0)
        return {0:"UNSPEC",1:"STOP",2:"SAFETY",3:"RECIT",4:"OTHER"}.get(fr, str(fr))
    except: return "UNKNOWN"

def _extract_text(resp)->str:
    try:
        if getattr(resp,"text",None): return resp.text
    except: pass
    try:
        cands = getattr(resp,"candidates",[]) or []
        parts = getattr(getattr(cands[0],"content",None),"parts",[]) if cands else []
        buf=[]
        for p in parts:
            t=getattr(p,"text",None)
            if t: buf.append(t)
        return "".join(buf)
    except: return ""

def try_generate(prompt: str)->str:
    runs=[]

    # 1) 構造化 + BLOCK_NONE
    m1 = genai.GenerativeModel(
        MODEL_ID,
        generation_config={
            "candidate_count":1,
            "temperature":0.25,
            "top_p":0.9,
            "max_output_tokens":1400,
            "response_mime_type":"application/json",
            "response_schema": RESPONSE_SCHEMA,
        },
        safety_settings=_safety(permissive=True)
    )
    r1 = m1.generate_content(prompt)
    d1 = r1.to_dict()
    runs.append({"step":"structured+permissive","finish":_finish_reason_name(d1)})
    out = _extract_text(r1)
    if out.strip(): 
        st.session_state["debug_runs"]=runs
        return robust_parse_items_json(out)

    # 2) 構造化（既定）
    m2 = genai.GenerativeModel(
        MODEL_ID,
        generation_config={
            "candidate_count":1,
            "temperature":0.25,
            "top_p":0.9,
            "max_output_tokens":1400,
            "response_mime_type":"application/json",
            "response_schema": RESPONSE_SCHEMA,
        }
    )
    r2 = m2.generate_content(prompt)
    d2 = r2.to_dict()
    runs.append({"step":"structured","finish":_finish_reason_name(d2)})
    out = _extract_text(r2)
    if out.strip():
        st.session_state["debug_runs"]=runs
        return robust_parse_items_json(out)

    # 3) プレーンテキスト（既定）
    m3 = genai.GenerativeModel(
        MODEL_ID,
        generation_config={
            "candidate_count":1,
            "temperature":0.25,
            "top_p":0.9,
            "max_output_tokens":1400,
        }
    )
    r3 = m3.generate_content(prompt)
    d3 = r3.to_dict()
    runs.append({"step":"plain","finish":_finish_reason_name(d3)})
    out = _extract_text(r3)

    st.session_state["debug_runs"]=runs
    return robust_parse_items_json(out if out.strip() else "{\"items\": []}")

# ================= Python正規化 & 計算 =================
_ALLOWED_CATS = {"制作人件費","企画","撮影費","出演関連費","編集費・MA費","諸経費","管理費"}
def _canon_unit(s:str)->str:
    t=(s or "").strip().lower()
    if t in ("d","day","days"): return "日"
    if t in ("一式","式"): return "式"
    if t in ("名","人"): return "人"
    if t in ("h","hr","hour","hours"): return "時間"
    if "時間" in t: return "時間"
    if t.endswith("日"): return "日"
    return (s or "").strip() or ""

def python_normalize(items_json: str)->str:
    try: data=json.loads(items_json)
    except: data={"items":[]}
    out=[]
    for it in data.get("items") or []:
        if not isinstance(it,dict): continue
        cat=str(it.get("category","")).strip()
        task=str(it.get("task","")).strip()
        qty=it.get("qty",0); unit=_canon_unit(it.get("unit",""))
        try: qty=float(qty)
        except: qty=0.0
        try: price=int(float(it.get("unit_price",0)))
        except: price=0

        if cat not in _ALLOWED_CATS:
            if "編集" in cat or "MA" in cat: cat="編集費・MA費"
            elif "出演" in cat or "キャスト" in cat: cat="出演関連費"
            elif any(w in cat for w in ["撮影","機材","カメラ","ロケ"]): cat="撮影費"
            elif "企画" in cat or "構成" in cat: cat="企画"
            elif "管理" in cat: cat="管理費"
            elif any(w in cat for w in ["人件","スタッフ"]): cat="制作人件費"
            else: cat="諸経費"
        out.append({"category":cat,"task":task,"qty":qty,"unit":unit,"unit_price":price,"note":str(it.get("note",""))})

    if not out:  # 最小補完
        out = [
            {"category":"撮影費","task":"カメラマン費","qty":max(1,int(shoot_days)),"unit":"日","unit_price":80000,"note":"auto"},
            {"category":"編集費・MA費","task":"編集費","qty":max(1,int(edit_days)),"unit":"日","unit_price":70000,"note":"auto"},
            {"category":"管理費","task":"管理費（固定）","qty":1,"unit":"式","unit_price":0,"note":"auto"},
        ]
    if not any(x["category"]=="管理費" for x in out):
        out.append({"category":"管理費","task":"管理費（固定）","qty":1,"unit":"式","unit_price":0,"note":""})
    return json.dumps({"items":out}, ensure_ascii=False)

def df_from_items_json(items_json:str)->pd.DataFrame:
    try: data=json.loads(items_json)
    except: data={}
    items=data.get("items",[]) or []
    df=pd.DataFrame([{
        "category":str(x.get("category","")),
        "task":str(x.get("task","")),
        "qty":x.get("qty",0),
        "unit":str(x.get("unit","")),
        "unit_price":x.get("unit_price",0),
    } for x in items])
    for c in ["category","task","qty","unit","unit_price"]:
        if c not in df.columns: df[c]=0 if c in ["qty","unit_price"] else ""
    df["qty"]=pd.to_numeric(df["qty"], errors="coerce").fillna(0.0)
    df["unit_price"]=pd.to_numeric(df["unit_price"], errors="coerce").fillna(0).astype(int)
    return df

def compute_totals(df_items:pd.DataFrame, base_days:int, target_days:int):
    accel=rush_coeff(base_days,target_days)
    df=df_items.copy()
    df["小計"]=(df["qty"]*df["unit_price"]).round().astype(int)
    is_mgmt=df["category"]=="管理費"
    df.loc[~is_mgmt,"小計"]=(df.loc[~is_mgmt,"小計"]*accel).round().astype(int)

    mgmt_current=int(df.loc[is_mgmt,"小計"].sum()) if is_mgmt.any() else 0
    subtotal_after=int(df.loc[~is_mgmt,"小計"].sum())
    mgmt_cap=int(round(subtotal_after*MGMT_FEE_CAP_RATE))
    mgmt_final=min(mgmt_current, mgmt_cap) if mgmt_current>0 else mgmt_cap

    if is_mgmt.any():
        idx=df[is_mgmt].index[0]
        df.at[idx,"unit_price"]=mgmt_final; df.at[idx,"qty"]=1; df.at[idx,"小計"]=mgmt_final
    else:
        df=pd.concat([df, pd.DataFrame([{"category":"管理費","task":"管理費（固定）","qty":1,"unit":"式","unit_price":mgmt_final,"小計":mgmt_final}])], ignore_index=True)

    taxable=int(df["小計"].sum()); tax=int(round(taxable*TAX_RATE)); total=taxable+tax
    return df, {"rush_coeff":accel,"taxable":taxable,"tax":tax,"total":total}

def render_html(df:pd.DataFrame, meta:dict)->str:
    td=lambda x:f"<td style='text-align:right'>{x}</td>"
    h=[]
    h.append("<p>以下はカテゴリ別に整理した概算見積です。</p>")
    h.append(f"<p>短納期係数：{meta['rush_coeff']} ／ 管理費上限：{int(MGMT_FEE_CAP_RATE*100)}% ／ 消費税率：{int(TAX_RATE*100)}%</p>")
    h.append("<table border='1' cellspacing='0' cellpadding='6' style='border-collapse:collapse;width:100%'>")
    h.append("<thead><tr><th>カテゴリ</th><th>項目</th><th style='text-align:right'>単価</th><th>数量</th><th>単位</th><th style='text-align:right'>金額（円）</th></tr></thead><tbody>")
    cur=None
    for _,r in df.iterrows():
        cat=r["category"]
        if cat!=cur:
            h.append(f"<tr><td colspan='6' style='background:#f6f6f6;font-weight:bold'>{cat}</td></tr>")
            cur=cat
        h.append("<tr>"
                 f"<td>{cat}</td><td>{r['task']}</td>"
                 f"{td(f'{int(r['unit_price']):,}')}"
                 f"<td>{r['qty']}</td><td>{r['unit']}</td>"
                 f"{td(f'{int(r['小計']):,}')}</tr>")
    h.append("</tbody></table>")
    h.append(f"<p><b>小計（税抜）</b>：{meta['taxable']:,}円 ／ <b>消費税</b>：{meta['tax']:,}円 ／ <b>合計</b>：<span style='color:#d00'>{meta['total']:,}円</span></p>")
    return "\n".join(h)

# ================= 実行 =================
def run_estimate():
    prompt = build_prompt()
    items_json = try_generate(prompt)
    items_json = python_normalize(items_json)

    df = df_from_items_json(items_json)
    base_days = int(shoot_days + edit_days + 5)
    target_days = (delivery_date - date.today()).days
    df_calc, meta = compute_totals(df, base_days, target_days)

    st.session_state["df"]=df_calc
    st.session_state["meta"]=meta
    st.session_state["final_html"]=render_html(df_calc, meta)

# ボタン
col1, col2 = st.columns(2)
with col1:
    if st.button("💡 見積もりを作成"):
        with st.spinner("2.5 Flash で生成中…"):
            run_estimate()
with col2:
    if st.button("🧪 プローブ（ping→pong）"):
        # 2.5 flash に最小JSONを返させる。ここで SAFETY なら環境/アカウント側制限の可能性高
        model = genai.GenerativeModel(
            MODEL_ID,
            generation_config={"response_mime_type":"application/json","max_output_tokens":16},
            safety_settings=_safety(permissive=True)
        )
        r = model.generate_content('必ず{"ping":"pong"}だけを返してください。')
        st.code(json.dumps(r.to_dict(), ensure_ascii=False, indent=2), language="json")

# 表示
if st.session_state["final_html"]:
    st.success("✅ 見積もり結果（計算済み）")
    st.components.v1.html(st.session_state["final_html"], height=900, scrolling=True)

    st.markdown("---")
    st.subheader("デバッグ")
    st.write({"gen_runs": st.session_state.get("debug_runs")})
