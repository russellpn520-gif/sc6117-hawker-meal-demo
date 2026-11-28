import streamlit as st

from meals import allocate_grams, load_foods, portion_items, total_nutrients


EATEN_SHARES = {4: "全吃了", 3: "约 ¾", 2: "一半", 1: "约 ¼", 0: "没吃"}


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
        choices = [*suggested, *st.session_state.get(selection_key, [])]
        matches = foods.search(query) if query.strip() else original.get("alternatives", [])
        choices.extend(matches)
        options = [key for key in dict.fromkeys(choices) if key in foods]
        selected = st.multiselect(
            "这餐有哪些食物？", options, default=[key for key in suggested if key in foods],
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

    corrections = st.expander("改菜名或餐盘份量", expanded=not bool(original["suggested_grams"]))
    weights = _correct_foods(corrections, foods, original, view)
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
    with summary:
        if weights:
            st.write("、".join(foods[key].name for key in weights))
            changed = [f"{foods[key].name} · {EATEN_SHARES[int(share * 4)]}"
                       for key, share in fractions.items() if share < 1]
            if changed:
                st.caption("　".join(changed))
            st.markdown(f"约 **{totals['kcal']:.0f} kcal**　·　蛋白质 **{totals['protein_g']:.1f} g**")
        else:
            st.info("还没有匹配到食物。在「改菜名或餐盘份量」里选好菜名，就能记下这餐。")
        missing = original.get("unmatched_foods", original.get("unmatched", [])
                               if original.get("method") == "text" else [])
        if missing:
            st.caption("待核对：" + "、".join(missing) + "。本次仅计入选中的食物。")
        elif original.get("unmatched"):
            st.caption("部分食物或做法待核对，热量只按已选食物估算。")
    with corrections:
        if original.get("unmatched"):
            st.caption("识别备注 · " + "、".join(original["unmatched"]))
        if original.get("portion_note"):
            st.caption(original["portion_note"])
    with action:
        if weights and not items:
            st.caption("各项实吃量合计为 0 克，这餐仍可保留为草稿。")
        label = "全部吃完，确认记餐" if items and all(x == 1 for x in fractions.values()) else "按实际份量确认记餐"
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
                        eaten_fraction=sum(consumed.values()) / sum(weights.values()))
        return {**draft, "input": original}, items
    return None
