import streamlit as st

from meals import allocate_grams, load_foods, portion_items, total_nutrients


EATEN_SHARES = {4: "全吃", 3: "¾", 2: "一半", 1: "¼", 0: "没吃"}


def _missing_items(original, foods):
    if "missing_items" in original:
        return original["missing_items"]
    names = original.get("unmatched_foods")
    if names is None:
        # Older photo drafts mixed unmatched names and size notes in a single
        # field. Treat ambiguous entries as unresolved. Known scale notes are
        # still shown with the photo information.
        notes = original.get("uncertain_items", [])
        names = [s for s in original.get("unmatched", []) if s not in notes and not any(
            word in s for word in ("比例尺", "标尺", "份量范围较宽", "分量范围较宽", "缺少尺寸参照"))]
    rows = []
    for i, name in enumerate(names):
        match = foods.photo_match("", name)
        alternatives = [match] if match else foods.photo_suggestions("", name)
        rows.append({"key": f"legacy-{i}", "name": name, "alternatives": alternatives})
    return rows


def _resolve_food(view, row, candidate, foods):
    choices = dict(st.session_state.get(f"{view}-decisions", {}))
    if candidate is not None:
        selected = list(st.session_state[f"{view}-foods"])
        if candidate not in selected:
            selected.append(candidate)
            low, high = row.get("low_g", 0), row.get("high_g", 0)
            weight = round((low + high) / 2) if 0 < low <= high <= 3000 else foods[candidate].serving_g
            st.session_state[f"{view}-grams-{candidate}"] = weight
        st.session_state[f"{view}-foods"] = selected
    choices[row["key"]] = candidate
    st.session_state[f"{view}-decisions"] = choices


def _restore_omitted(view, key):
    decisions = dict(st.session_state.get(f"{view}-decisions", {}))
    decisions.pop(key, None)
    st.session_state[f"{view}-decisions"] = decisions


def _repair_controls(panel, view, rows, foods, selected):
    decisions = st.session_state.get(f"{view}-decisions", {})
    decisions = {k: v for k, v in decisions.items() if v is None or v in selected}
    st.session_state[f"{view}-decisions"] = decisions
    pending = [row for row in rows if row["key"] not in decisions]
    repair = panel.expander("补选未匹配的食物" if pending else "已核对的食物", expanded=bool(pending))
    with repair:
        if pending:
            names = {r["key"]: r["name"] for r in pending}
            focus = (st.selectbox("先补哪一样？", list(names), format_func=names.get,
                                  key=f"{view}-focus") if len(pending) > 1 else pending[0]["key"])
            row = next(r for r in pending if r["key"] == focus)
            controls = f"{view}-{focus}"
            st.write(f"补记「{row['name']}」")
            low, high = row.get("low_g", 0), row.get("high_g", 0)
            if 0 < low <= high <= 3000:
                st.caption(f"照片估计 {low}–{high} 克，补选后可调整。")
            quick = [k for k in dict.fromkeys(row.get("alternatives", [])) if k in foods][:3]
            with st.container(horizontal=True):
                for k in quick:
                    label = f"对应已选的{foods[k].name}" if k in selected else f"＋ {foods[k].name}"
                    st.button(label, key=f"{controls}-add-{k}", help=foods[k].source_label,
                              on_click=_resolve_food, args=(view, row, k, foods))
            with st.expander("查找其他食物"):
                query = st.text_input("搜索合适的菜名或食材", key=f"{controls}-lookup")
                if query.strip():
                    matches = foods.search(query)
                    if matches:
                        k = st.selectbox("选择对应项", matches, format_func=lambda k: f"{foods[k].name} · {foods[k].source_label}",
                                         key=f"{controls}-replacement")
                        st.button("用这项补记", key=f"{controls}-use", on_click=_resolve_food,
                                  args=(view, row, k, foods))
                    else:
                        st.caption("暂未搜到，可换个菜名或食材名。")
            st.button("这项没吃或不在餐盘里", key=f"{controls}-omit", on_click=_resolve_food,
                      args=(view, row, None, foods))
        omitted = [r for r in rows if r["key"] in decisions and decisions[r["key"]] is None]
        for row in rows:
            key = decisions.get(row["key"])
            if key:
                st.caption(f"{row['name']} 已按「{foods[key].name}」计入。")
        if omitted:
            with st.expander("已略过：" + "、".join(r["name"] for r in omitted)):
                for row in omitted:
                    st.button(f"恢复「{row['name']}」", key=f"{view}-{row['key']}-undo",
                              on_click=_restore_omitted, args=(view, row["key"]))
    return pending, decisions


def _apply_net_weight(view, selected):
    weights = {key: st.session_state[f"{view}-grams-{key}"] for key in selected}
    scaled = allocate_grams(weights, st.session_state[f"{view}-net"], minimum=1)
    for key, grams in scaled.items():
        st.session_state[f"{view}-grams-{key}"] = grams


def _set_photo_size(view, ranges, suggested):
    choice = st.session_state[f"{view}-size"]
    for key, bounds in ranges.items():
        if bounds:
            by_size = {"偏小": bounds[0], "按照片估计": suggested[key], "偏大": bounds[1]}
            st.session_state[f"{view}-grams-{key}"] = by_size[choice]


def _correct_foods(panel, foods, original, view):
    suggested = original["suggested_grams"]
    with panel:
        query = st.text_input("搜索食物", placeholder="输入菜名或食材", key=f"{view}-search")
        selection_key = f"{view}-foods"
        if selection_key not in st.session_state:
            st.session_state[selection_key] = [key for key in suggested if key in foods]
        choices = [*suggested, *st.session_state[selection_key]]
        matches = foods.search(query) if query.strip() else original.get("alternatives", [])
        choices.extend(matches)
        options = [key for key in dict.fromkeys(choices) if key in foods]
        selected = st.multiselect(
            "这餐有哪些食物？", options,
            format_func=lambda key: f"{foods[key].name} · {foods[key].source_label}",
            placeholder="选择要记入的食物", key=selection_key,
        )
        if query.strip() and not matches:
            st.caption("没有搜到，可以换个名字或搜一种配料。")
        ranges = original.get("portion_ranges", {})
        if any(ranges.get(key) for key in selected):
            st.segmented_control("照片里的份量", ["偏小", "按照片估计", "偏大"], default="按照片估计",
                                 required=True, key=f"{view}-size", on_change=_set_photo_size,
                                 args=(view, ranges, suggested))
        weights = {}
        for key in selected:
            food = foods[key]
            widget_key = f"{view}-grams-{key}"
            if widget_key not in st.session_state:
                st.session_state[widget_key] = suggested.get(key, food.serving_g)
            bounds = ranges.get(key)
            detail = (f"照片目测约 {bounds[0]}–{bounds[1]} g" if bounds else
                      f"参考份量 {food.serving_g} g")
            weights[key] = st.number_input(
                f"{food.name} · 端上来的克数", min_value=1, max_value=3000, step=1,
                key=widget_key, help=detail,
            )
        if selected:
            net = st.number_input("整份净重（可选）", min_value=len(selected), max_value=3000,
                                  value=None, placeholder="例如 420 克", key=f"{view}-net")
            st.button("按净重校准", key=f"{view}-scale", on_click=_apply_net_weight,
                      args=(view, selected), disabled=net is None)
    return weights


def review_meal(draft):
    """Render an editable meal and return (draft, items) only on confirmation."""
    foods = load_foods()
    original = dict(draft["input"])
    prefix = f"meal-{draft['id']}"
    summary = st.container()
    repair_area = st.container()
    leftovers = st.expander("有哪样没吃完？")
    action = st.container()
    view = prefix
    if variants := draft.get("variants"):
        modes = list(variants)
        with leftovers:
            mode = st.segmented_control("要调整哪一部分？", modes, default=modes[0],
                                        required=True, key=f"{prefix}-mode")
            st.caption("只剩了碗里的米饭或配菜？点「按配料」单独调整。")
        original.update(variants[mode], portion_mode=mode)
        view = f"{prefix}-{mode}"

    rows = _missing_items(original, foods)
    corrections = st.expander("改菜名或餐盘份量", expanded=not rows and not bool(original["suggested_grams"]))
    weights = _correct_foods(corrections, foods, original, view)
    pending, decisions = [], {}
    if rows:
        pending, decisions = _repair_controls(repair_area, view, rows, foods, weights)
    with leftovers:
        fractions = {}
        for key in weights:
            share = st.segmented_control(f"{foods[key].name}吃了多少？", list(EATEN_SHARES),
                                         format_func=EATEN_SHARES.get, default=4, required=True,
                                         key=f"{prefix}-eaten-{key}")
            fractions[key] = share / 4

    consumed = {key: max(1, round(grams * fractions[key])) if fractions[key] else 0
                for key, grams in weights.items()}
    items = portion_items(foods, {key: grams for key, grams in consumed.items() if grams > 0})
    totals = total_nutrients([item["nutrients"] for item in items])
    names = [row["name"] for row in pending]
    with summary:
        if pending:
            st.warning(f"还有 {len(pending)} 项未计入 · " + "、".join(names))
        if weights:
            st.write("、".join(foods[key].name for key in weights))
            changed = [f"{foods[key].name} · {EATEN_SHARES[int(share * 4)]}"
                       for key, share in fractions.items() if share < 1]
            if changed:
                st.caption("　".join(changed))
            label = "已选食物小计约" if pending else "约"
            st.markdown(f"{label} **{totals['kcal']:.0f} kcal**　·　蛋白质 **{totals['protein_g']:.1f} g**")
        else:
            st.info("还没有匹配到食物，选好菜名后就能记下这餐。")
    row_names = {r["name"] for r in rows}
    notes = original.get("uncertain_items", [s for s in original.get("unmatched", []) if s not in row_names])
    with corrections:
        if notes:
            st.caption("识别备注 · " + "、".join(notes))
        if original.get("portion_note"):
            st.caption(original["portion_note"])
    with action:
        if weights and not items:
            st.caption("各项实吃量合计为 0 克，这餐仍可保留为草稿。")
        if pending:
            with st.expander("只保存已选的食物"):
                st.caption("本次只计入上方小计。未计入：" + "、".join(names))
                confirm = st.button(f"仅记录已选的 {len(items)} 项", key=f"{prefix}-partial-confirm",
                                    width="stretch", disabled=not items)
        else:
            ate_all = all(x == 1 for x in fractions.values()) and None not in decisions.values()
            label = "全部吃完，确认记餐" if items and ate_all else "按实际份量确认记餐"
            confirm = st.button(label, key=f"{prefix}-confirm", type="primary", width="stretch",
                                disabled=not items)

    if items:
        with corrections:
            st.caption(f"盘中 {sum(weights.values())} g · 实吃 {sum(consumed.values())} g")
            st.write(f"碳水 {totals['carb_g']:.1f} g · 脂肪 {totals['fat_g']:.1f} g")
            for item in items:
                st.markdown(f"{item['name']} · {item['confirmed_g']} g　"
                            f"[{item['source_label']}]({item['source_url']})")
            if usage := original.get("token_usage"):
                st.caption(f"本次识别 · {original.get('model', '')} · 输入 {usage['input_tokens']:,} ＋ "
                           f"输出 {usage['output_tokens']:,} ＝ {usage['total_tokens']:,} tokens")
    if confirm and items:
        original.update(served_grams=weights, eaten_fractions=fractions,
                        eaten_fraction=sum(consumed.values()) / sum(weights.values()),
                        partial_record=bool(pending), missing_items=pending, unmatched_foods=names,
                        unmatched=list(dict.fromkeys([*names, *notes])),
                        coverage_decisions=[{"name": r["name"], "food_id": decisions[r["key"]]}
                                            for r in rows if r["key"] in decisions])
        return {**draft, "input": original}, items
    return None
