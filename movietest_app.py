def llm_generate_items_json(prompt: str) -> str:
    """
    Gemini 2.5 Flash 用の堅牢な items JSON 生成。
    - ①構造化っぽい通常プロンプト
    - ②空/失敗なら最小JSON指示
    - ③それでも空なら seed 付きの極小プロンプト
    各段階でパースし、items>=1 を確認して返す。
    """
    def _structured_prompt(p: str) -> str:
        return f"""{STRICT_JSON_HEADER}
あなたは広告映像の概算見積り項目のエキスパートです。**JSONだけ**を1個返してください。
JSONは次の仕様です:
- ルートに "items": [] を1つだけ持つこと
- 各要素は {{ "category","task","qty","unit","unit_price","note" }} をすべて持つ
- 数量/単価は数値として返す
- 最低3行以上
- 可能なら "note" に簡潔な内訳(役割・範囲)を書く

【案件条件】
{_common_case_block()}
{_inference_block()}
"""

    def _minimal_prompt() -> str:
        return f"""{STRICT_JSON_HEADER}
次の仕様でJSON(1オブジェクト)のみを返してください。コードフェンス禁止。
- ルート: items 配列
- 各要素: category, task, qty, unit, unit_price, note
- 最低3行以上、数値は数値で
- 管理費は1行（task=管理費（固定）, qty=1, unit=式）
"""

    def _seed_prompt() -> str:
        # “映像”を強く思い出させつつ、最低限のシードを与える
        seed = {
            "items": [
                {"category":"制作費","task":"企画構成費","qty":1,"unit":"式","unit_price":50000,"note":"構成案・進行"},
                {"category":"撮影費","task":"カメラマン費","qty":2,"unit":"日","unit_price":80000,"note":"撮影一式"},
                {"category":"編集費・MA費","task":"編集","qty":3,"unit":"日","unit_price":70000,"note":"オフライン/オンライン"}
            ]
        }
        import json as _json
        return f"""{STRICT_JSON_HEADER}
以下のシードに沿って**映像制作の見積り**として整形し、最低3行以上の items を返してください。
- ルート: items 配列
- 各要素: category, task, qty, unit, unit_price, note
- 管理費（固定）を必ず含める（qty=1, unit=式）
- 返答はJSONのみ、コードフェンス禁止、説明文不要

シード例:
{_json.dumps(seed, ensure_ascii=False, indent=2)}
"""

    def _call_gemini(text_prompt: str):
        model_id = _gemini_model_id_from_choice(model_choice)
        model = genai.GenerativeModel(
            model_id,
            generation_config={
                # 構造化とplainの両方に効く安全圧
                "temperature": 0.2,
                "top_p": 0.9,
                "max_output_tokens": 2500,
            },
        )
        resp = model.generate_content(text_prompt)
        # UI用メタ保存
        try:
            st.session_state["gemini_raw_dict"] = resp.to_dict()
        except Exception:
            pass
        # “text”が空でも parts→text を拾う
        txt = ""
        try:
            if getattr(resp, "text", None):
                txt = resp.text or ""
        except Exception:
            txt = ""

        if not txt:
            try:
                cands = getattr(resp, "candidates", []) or []
                buf = []
                for c in cands:
                    parts = getattr(c, "content", None)
                    parts = getattr(parts, "parts", None) or []
                    for p in parts:
                        t = getattr(p, "text", None)
                        if t:
                            buf.append(t)
                if buf:
                    txt = "\n".join(buf)
            except Exception:
                pass
        return txt, getattr(resp, "finish_reason", None)

    # ① 構造化寄り
    st.session_state["used_fallback"] = False
    text1, finish1 = _call_gemini(_structured_prompt(prompt))
    st.session_state["gen_finish_reason"] = finish1 or "(unknown)"
    raw1 = text1.strip()

    # デバッグ表示用に保存
    st.session_state["items_json_raw"] = raw1

    parsed1 = robust_parse_items_json(raw1) if raw1 else None
    if parsed1:
        try:
            if len(json.loads(parsed1).get("items") or []) >= 1:
                st.session_state["model_used"] = _gemini_model_id_from_choice(model_choice)
                return parsed1
        except Exception:
            pass

    # ② 最小JSONプロンプトで再実行
    st.session_state["used_fallback"] = True
    text2, finish2 = _call_gemini(_minimal_prompt())
    st.session_state["gen_finish_reason"] = finish2 or "(unknown)"
    raw2 = text2.strip()
    st.session_state["items_json_raw"] = raw2 or raw1  # デバッグ保全

    parsed2 = robust_parse_items_json(raw2) if raw2 else None
    if parsed2:
        try:
            if len(json.loads(parsed2).get("items") or []) >= 1:
                st.session_state["model_used"] = _gemini_model_id_from_choice(model_choice)
                return parsed2
        except Exception:
            pass

    # ③ seed 付き極小プロンプト
    text3, finish3 = _call_gemini(_seed_prompt())
    st.session_state["gen_finish_reason"] = finish3 or "(unknown)"
    raw3 = (text3 or "").strip()
    st.session_state["items_json_raw"] = raw3 or raw2 or raw1

    parsed3 = robust_parse_items_json(raw3) if raw3 else None
    if parsed3:
        try:
            if len(json.loads(parsed3).get("items") or []) >= 1:
                st.session_state["model_used"] = _gemini_model_id_from_choice(model_choice)
                return parsed3
        except Exception:
            pass

    # それでもダメなら、最後に安全な固定fallback
    st.session_state["fallback_reason"] = "Gemini returned empty/invalid JSON in 3 attempts."
    st.warning("⚠️ モデルから有効なJSONが得られなかったため、安全な固定値で継続します。")
    fallback = {
        "items": [
            {"category": "制作費",      "task": "企画構成費", "qty": 1, "unit": "式", "unit_price": 50000, "note": "構成案・進行"},
            {"category": "撮影費",      "task": "カメラマン費", "qty": 2, "unit": "日", "unit_price": 80000, "note": "撮影一式"},
            {"category": "編集費・MA費","task": "編集",      "qty": 3, "unit": "日", "unit_price": 70000, "note": "編集一式"},
            {"category": "管理費",      "task": "管理費（固定）","qty": 1, "unit": "式", "unit_price": 60000, "note": "進行管理"}
        ]
    }
    st.session_state["items_json_raw"] = json.dumps(fallback, ensure_ascii=False)
    return json.dumps(fallback, ensure_ascii=False)
