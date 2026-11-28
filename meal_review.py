import streamlit as st

from i18n import food_name, source_name, tr
from recognition import reviewable_photo
from meals import allocate_grams, load_foods, portion_items, total_nutrients, update_pending_portion


EATEN_SHARES = {4: ("全吃", "All"), 3: ("¾", "¾"), 2: ("一半", "Half"), 1: ("¼", "¼"), 0: ("没吃", "None")}


def _share_label(value):
    return tr(*EATEN_SHARES[value])


def _persist_choice(widget_key, draft_id, method, db_path, variant, scope=None, food_id=None):
    value = st.session_state[widget_key]
    if food_id is None:
        update_pending_portion(draft_id, method, value, db_path=db_path)
    else:
        update_pending_portion(draft_id, method, variant, food_id=food_id, scope=scope, quarters=value, db_path=db_path)


def _review_choice(label, options, labels, default, key, *, save_args=None):
    # Streamlit serializes selection labels. Carry stable values across UI languages.
    widget_key = key + tr("", "-en")
    previous = key + "-value"
    if save_args is not None and st.session_state.get(widget_key) != default:
        st.session_state[widget_key] = default
    elif widget_key not in st.session_state:
        st.session_state[widget_key] = st.session_state.get(previous, default)
    chosen = st.segmented_control(label, options, format_func=labels.__getitem__,
                                  required=True, key=widget_key, on_change=_persist_choice if save_args else None,
                                  args=(widget_key, *save_args) if save_args else ())
    st.session_state[previous] = chosen
    return chosen


def _row_name(row):
    return tr(row["name"], row.get("name_en") or row["name"])


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
        widget_key = _selection_key(view)
        selected = list(st.session_state[widget_key])
        if candidate not in selected:
            selected.append(candidate)
            low, high = row.get("low_g", 0), row.get("high_g", 0)
            weight = round((low + high) / 2) if 0 < low <= high <= 3000 else foods[candidate].serving_g
            st.session_state[f"{view}-grams-{candidate}"] = weight
        st.session_state[widget_key] = selected
        st.session_state[f"{view}-selected-ids"] = selected
    choices[row["key"]] = candidate
    st.session_state[f"{view}-decisions"] = choices


def _restore_omitted(view, key):
    decisions = dict(st.session_state.get(f"{view}-decisions", {}))
    decisions.pop(key, None)
    st.session_state[f"{view}-decisions"] = decisions


def _set_main(view, group, candidate):
    choices = st.session_state.setdefault(f"{view}-main-choices", {})
    if candidate is None:
        choices.pop(group, None)
    else:
        choices[group] = candidate


def _main_review(panel, original, view, foods):
    """Allow one dish to replace its matched components, keeping other plates and sides."""
    groups = original.get("main_dishes", [])
    selected = st.session_state.get(f"{view}-main-choices", {})
    grams = dict(original["suggested_grams"])
    ranges = dict(original.get("portion_ranges", {}))
    cleared, decisions = set(), []
    for group in groups:
        name, group_id = _row_name(group), group["key"]
        prefix = f"{view}-{group_id}-main"
        candidate = selected.get(group_id)
        if candidate is None and all(k in st.session_state.get(f"{view}-decisions", {}) for k in group["unresolved"]):
            continue
        if candidate in foods:
            low, high = group.get("low_g", 0), group.get("high_g", 0)
            weight = round((low + high) / 2) if 0 < low <= high <= 3000 else foods[candidate].serving_g
            components = group["component_grams"]
            if grams.get(candidate, 0) - components.get(candidate, 0) + weight <= 3000:
                for key, amount in components.items():
                    grams[key] -= amount
                    if grams[key] == 0:
                        grams.pop(key)
                    ranges.pop(key, None)
                grams[candidate] = grams.get(candidate, 0) + weight
                ranges.pop(candidate, None)
                cleared.update(group["unresolved"])
                decisions.append({"name": group["name"], "name_en": group["name_en"], "scope": "whole_dish",
                                  "food_id": candidate, "group": group_id})
                panel.caption(tr(f"已按整道「{food_name(foods[candidate])}」计入，可在下方调整克数。",
                                 f"Counting {food_name(foods[candidate])} as one dish. You can adjust its weight below."))
                panel.button(tr("改回按配料", "Return to ingredients"), key=prefix + "-undo",
                             on_click=_set_main, args=(view, group_id, None))
                continue
            panel.warning(tr("同一食物累计超过 3,000 g，请换一项或按配料核对。",
                             "That choice exceeds 3,000 g for one food. Choose another or review the ingredients."))
        with panel.expander(tr(f"补上主菜 · {name}", f"Match the main dish · {name}"), expanded=True):
            st.caption(tr("选择整道菜会替换这道菜的配料，其他菜和饮品仍单独计算。",
                          "Choose one whole dish to replace its ingredients. Other dishes and drinks stay separate."))
            if group.get("remembered_id") in foods:
                previous = food_name(foods[group["remembered_id"]])
                st.caption(tr(f"你上次为这道菜选了「{previous}」。", f"You previously chose {previous} for this dish."))
            for key in group.get("alternatives", ()):
                if key in foods:
                    st.button(food_name(foods[key]), key=prefix + "-" + key, help=source_name(foods[key].source_label),
                              on_click=_set_main, args=(view, group_id, key))
            query = st.text_input(tr("搜索整道菜名", "Search for a whole dish"), key=prefix + "-search",
                                  placeholder=tr("例如：福建炒虾面", "e.g. Hokkien mee"))
            if query.strip():
                matches = foods.search(query)
                if matches:
                    labels = {k: f"{food_name(foods[k])} · {source_name(foods[k].source_label)}" for k in matches}
                    key = st.selectbox(tr("食物库中的整道菜", "Whole dish in the database"), matches,
                                       format_func=labels.__getitem__,
                                       key=prefix + "-select")
                    st.button(tr("按这道菜计入", "Use this dish"), key=prefix + "-use", on_click=_set_main,
                              args=(view, group_id, key))
                else:
                    st.caption(tr("没有匹配，可以换个菜名，或在下方分别补选主食和配料。",
                                  "Try another dish name or match the staple and ingredients below."))
    if decisions:
        original.update(suggested_grams=grams, portion_ranges=ranges,
                        missing_items=[row for row in original["missing_items"] if row["key"] not in cleared])
        view += "-whole-" + "-".join(d["group"] + d["food_id"] for d in decisions)
    return view, decisions


def _repair_controls(panel, view, rows, foods, selected, main_dishes=()):
    decisions = st.session_state.get(f"{view}-decisions", {})
    decisions = {k: v for k, v in decisions.items() if v is None or v in selected}
    st.session_state[f"{view}-decisions"] = decisions
    pending = [row for row in rows if row["key"] not in decisions]
    pending_keys = {r["key"] for r in pending}
    choose_main = any(pending_keys.intersection(g["unresolved"]) for g in main_dishes)
    title = (tr("逐项核对配料", "Review ingredients individually") if choose_main else
             tr("补选未匹配的食物", "Match missing foods") if pending else tr("已核对的食物", "Reviewed foods"))
    repair = panel.expander(title, expanded=bool(pending) and not choose_main)
    with repair:
        if pending:
            names = {r["key"]: _row_name(r) for r in pending}
            focus = (st.selectbox(tr("先补哪一样？", "Which food would you like to match?"), list(names), format_func=names.get,
                                  key=f"{view}-focus") if len(pending) > 1 else pending[0]["key"])
            row = next(r for r in pending if r["key"] == focus)
            controls = f"{view}-{focus}"
            st.write(tr(f"补记「{_row_name(row)}」", f"Match: {_row_name(row)}"))
            low, high = row.get("low_g", 0), row.get("high_g", 0)
            if 0 < low <= high <= 3000:
                st.caption(tr(f"照片估计 {low}–{high} 克，补选后可调整。", f"Estimated {low}–{high} g. You can adjust this after matching."))
            if row.get("remembered_id") in foods:
                previous = food_name(foods[row["remembered_id"]])
                st.caption(tr(f"你曾为这项选过「{previous}」。", f"You previously chose {previous} for this item."))
            quick = [k for k in dict.fromkeys(row.get("alternatives", [])) if k in foods][:3]
            with st.container(horizontal=True):
                for k in quick:
                    label = tr(f"对应已选的{food_name(foods[k])}", f"Use selected {food_name(foods[k])}") if k in selected else f"＋ {food_name(foods[k])}"
                    st.button(label, key=f"{controls}-add-{k}", help=source_name(foods[k].source_label),
                              on_click=_resolve_food, args=(view, row, k, foods))
            with st.expander(tr("查找其他食物", "Look up another food"), expanded=not quick):
                query = st.text_input(tr("搜索合适的菜名或食材", "Search for a dish or ingredient"), key=f"{controls}-lookup")
                if query.strip():
                    matches = foods.search(query)
                    if matches:
                        labels = {k: f"{food_name(foods[k])} · {source_name(foods[k].source_label)}" for k in matches}
                        k = st.selectbox(tr("选择对应项", "Choose a matching food"), matches, format_func=labels.__getitem__,
                                         key=f"{controls}-replacement")
                        st.button(tr("用这项补记", "Use this food"), key=f"{controls}-use", on_click=_resolve_food,
                                  args=(view, row, k, foods))
                    else:
                        st.caption(tr("暂未搜到，可换个菜名或食材名。", "No matches. Try another dish or ingredient."))
            st.button(tr("这项没吃或不在餐盘里", "I didn't eat this / it wasn't on the plate"), key=f"{controls}-omit", on_click=_resolve_food,
                      args=(view, row, None, foods))
        omitted = [r for r in rows if r["key"] in decisions and decisions[r["key"]] is None]
        for row in rows:
            key = decisions.get(row["key"])
            if key:
                st.caption(tr(f"{_row_name(row)} 已按「{food_name(foods[key])}」计入。", f"{_row_name(row)} is counted as {food_name(foods[key])}."))
        if omitted:
            with st.expander(tr("已略过：", "Skipped: ") + "、".join(_row_name(r) for r in omitted)):
                for row in omitted:
                    st.button(tr(f"恢复「{_row_name(row)}」", f"Restore {_row_name(row)}"), key=f"{view}-{row['key']}-undo",
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


def _selection_key(view):
    return f"{view}-foods" + tr("", "-en")


def _correct_foods(panel, foods, original, view):
    suggested = original["suggested_grams"]
    with panel:
        query = st.text_input(tr("搜索食物", "Search foods"), placeholder=tr("输入菜名或食材", "Enter a dish or ingredient"), key=f"{view}-search")
        selection_key = _selection_key(view)
        stable = f"{view}-selected-ids"
        if selection_key not in st.session_state:
            st.session_state[selection_key] = st.session_state.get(stable, [key for key in suggested if key in foods])
        choices = [*suggested, *st.session_state[selection_key]]
        matches = foods.search(query) if query.strip() else original.get("alternatives", [])
        choices.extend(matches)
        options = [key for key in dict.fromkeys(choices) if key in foods]
        labels = {k: f"{food_name(foods[k])} · {source_name(foods[k].source_label)}" for k in options}
        selected = st.multiselect(
            tr("这餐有哪些食物？", "Foods in this meal"), options,
            format_func=labels.__getitem__,
            placeholder=tr("选择要记入的食物", "Select foods to include"), key=selection_key,
        )
        st.session_state[stable] = list(selected)
        if query.strip() and not matches:
            st.caption(tr("没有搜到，可以换个名字或搜一种配料。", "No matches. Try a different name or ingredient."))
        ranges = original.get("portion_ranges", {})
        if any(ranges.get(key) for key in selected):
            sizes = {k: tr(k, v) for k, v in (("偏小", "Smaller"), ("按照片估计", "Estimate"), ("偏大", "Larger"))}
            st.segmented_control(tr("照片里的份量", "Photo portion estimate"), list(sizes), default="按照片估计",
                                 format_func=sizes.__getitem__,
                                 required=True, key=f"{view}-size", on_change=_set_photo_size,
                                 args=(view, ranges, suggested))
        weights = {}
        for key in selected:
            food = foods[key]
            widget_key = f"{view}-grams-{key}"
            if widget_key not in st.session_state:
                st.session_state[widget_key] = suggested.get(key, food.serving_g)
            bounds = ranges.get(key)
            detail = (tr(f"照片目测约 {bounds[0]}–{bounds[1]} g", f"Estimated {bounds[0]}–{bounds[1]} g from photo") if bounds else
                      tr(f"参考份量 {food.serving_g} g", f"Reference serving: {food.serving_g} g"))
            weights[key] = st.number_input(
                tr(f"{food_name(food)} · 端上来的克数", f"{food_name(food)} · grams served"), min_value=1, max_value=3000, step=1,
                key=widget_key, help=detail,
            )
        if selected:
            net = st.number_input(tr("整份净重（可选）", "Total food weight in grams (optional)"), min_value=len(selected), max_value=3000,
                                  value=None, placeholder=tr("例如 420 克", "e.g. 420"), key=f"{view}-net")
            st.button(tr("按净重校准", "Apply total weight"), key=f"{view}-scale", on_click=_apply_net_weight,
                      args=(view, selected), disabled=net is None)
    return weights


def review_meal(draft, db_path=None):
    """Render an editable meal and return (draft, items) only on confirmation."""
    foods = load_foods()
    draft = reviewable_photo(draft)
    original = dict(draft["input"])
    prefix = f"meal-{draft['id']}"
    if version := draft["input"].get("photo_resolution_version"):
        prefix += f"-v{version}"
    summary = st.container()
    repair_area = st.container()
    leftovers = st.expander(tr("有哪样没吃完？", "Any leftovers?"))
    action = st.container()
    view = prefix
    saved = draft.get("portion_review") or {}
    save_args = (draft["id"], original["method"], db_path) if "captured_at" in draft else None
    mode = "default"
    variants = draft.get("variants") or {}
    if variants:
        modes = list(variants)
        legacy_partial = "main_dishes" not in original and any(
            v.get("missing_items") for v in variants.values())
        with (repair_area if legacy_partial else leftovers):
            labels = {m: tr(m, {"整道菜": "Whole dish", "按配料": "Ingredients", "推荐": "Suggested"}.get(m, m)) for m in modes}
            previous_mode = saved.get("variant")
            mode = _review_choice(tr("要调整哪一部分？", "Adjust portions by"), modes, labels,
                                  previous_mode if previous_mode in modes else modes[0], f"{prefix}-mode",
                                  save_args=(*save_args, None) if save_args else None)
            st.caption(tr("只剩了碗里的米饭或配菜？点「按配料」单独调整。", "Choose Ingredients to adjust the rice or a topping separately."))
        original.update(variants[mode], portion_mode=mode)
        view = f"{prefix}-{mode}"

    base_view = view
    view, main_decisions = _main_review(repair_area, original, base_view, foods)
    rows = _missing_items(original, foods)
    corrections = st.expander(tr("改菜名或餐盘份量", "Edit foods and serving sizes"), expanded=not rows and not bool(original["suggested_grams"]))
    weights = _correct_foods(corrections, foods, original, view)
    # Deselecting a whole-dish replacement reopens that group for review.
    dropped = [d for d in main_decisions if d["food_id"] not in weights]
    if dropped:
        for decision in dropped:
            _set_main(base_view, decision["group"], None)
        st.rerun()
    pending, decisions = [], {}
    if rows:
        pending, decisions = _repair_controls(repair_area, view, rows, foods, weights, original.get("main_dishes", []))
    with leftovers:
        fractions = {}
        for key in weights:
            label = tr(f"{food_name(foods[key])}吃了多少？", f"How much {food_name(foods[key])} did you eat?")
            labels = {value: _share_label(value) for value in EATEN_SHARES}
            # An identical side served in both views keeps the same choice. A food
            # with a different weight in the other view has its own portion there.
            weights_by_mode = [v["suggested_grams"].get(key) for v in variants.values()]
            shared = weights_by_mode and None not in weights_by_mode and len(set(weights_by_mode)) == 1
            scope = "shared" if shared else mode
            stored = saved.get("shares", {}).get(scope, {}).get(key, 4)
            scope_prefix = prefix if scope in ("shared", "default") else f"{prefix}-{scope}"
            share = _review_choice(label, list(EATEN_SHARES), labels, stored if stored in EATEN_SHARES else 4,
                                   f"{scope_prefix}-eaten-{key}",
                                   save_args=(*save_args, mode, scope, key) if save_args else None)
            fractions[key] = share / 4

    consumed = {key: max(1, round(grams * fractions[key])) if fractions[key] else 0
                for key, grams in weights.items()}
    items = portion_items(foods, {key: grams for key, grams in consumed.items() if grams > 0})
    totals = total_nutrients([item["nutrients"] for item in items])
    names = [row["name"] for row in pending]
    display_names = tr("、", ", ").join(_row_name(row) for row in pending)
    with summary:
        if pending:
            unresolved = {r["key"] for r in pending}
            if any(unresolved.intersection(g["unresolved"]) for g in original.get("main_dishes", [])):
                st.warning(tr("主菜还没记全。先选整道菜，或补齐主食和配料。", "The main dish is incomplete. Choose a whole dish or match its staple and ingredients."))
            else:
                st.warning(tr(f"还有 {len(pending)} 项未计入 · ", f"Foods still missing ({len(pending)}) · ") + display_names)
        if weights:
            st.write(tr("、", ", ").join(food_name(foods[key]) for key in weights))
            changed = [f"{food_name(foods[key])} · {_share_label(int(share * 4))}"
                       for key, share in fractions.items() if share < 1]
            if changed:
                st.caption("　".join(changed))
            label = tr("已选食物小计约", "Selected subtotal: about") if pending else tr("约", "About")
            st.markdown(tr(f"{label} **{totals['kcal']:.0f} kcal**　·　蛋白质 **{totals['protein_g']:.1f} g**",
                           f"{label} **{totals['kcal']:.0f} kcal** · Protein **{totals['protein_g']:.1f} g**"))
        else:
            st.info(tr("还没有匹配到食物，选好菜名后就能记下这餐。", "No foods matched yet. Choose a food to log this meal."))
    row_names = {r["name"] for r in rows}
    notes = original.get("uncertain_items", [s for s in original.get("unmatched", []) if s not in row_names])
    with corrections:
        if notes:
            st.caption(tr("识别备注 · ", "Photo notes · ") + tr("、".join(notes), ", ".join(original.get("uncertain_items_en") or notes)))
        if original.get("portion_note"):
            st.caption(tr(original["portion_note"], original.get("portion_note_en") or original["portion_note"]))
    with action:
        if weights and not items:
            st.caption(tr("各项实吃量合计为 0 克，这餐仍可保留为草稿。", "Total eaten is 0 g. You can keep this meal as a draft."))
        if pending:
            with st.expander(tr("只保存已选的食物", "Save selected foods only")):
                st.caption(tr("本次只计入上方小计。未计入：", "Only the subtotal above will be recorded. Excluded: ") + display_names)
                confirm = st.button(tr(f"仅记录已选的 {len(items)} 项", f"Log selected items only ({len(items)})"), key=f"{prefix}-partial-confirm",
                                    width="stretch", disabled=not items)
        else:
            ate_all = all(x == 1 for x in fractions.values()) and None not in decisions.values()
            label = tr("全部吃完，确认记餐", "Ate it all · Log meal") if items and ate_all else tr("按实际份量确认记餐", "Confirm portions and log")
            confirm = st.button(label, key=f"{prefix}-confirm", type="primary", width="stretch",
                                disabled=not items)

    if items:
        with corrections:
            st.caption(tr(f"盘中 {sum(weights.values())} g · 实吃 {sum(consumed.values())} g",
                          f"Served {sum(weights.values())} g · Eaten {sum(consumed.values())} g"))
            st.write(tr(f"碳水 {totals['carb_g']:.1f} g · 脂肪 {totals['fat_g']:.1f} g", f"Carbs {totals['carb_g']:.1f} g · Fat {totals['fat_g']:.1f} g"))
            for item in items:
                st.markdown(f"{food_name(foods[item['food_id']])} · {item['confirmed_g']} g　"
                            f"[{source_name(item['source_label'])}]({item['source_url']})")
            if usage := original.get("token_usage"):
                st.caption(tr(f"本次识别 · {original.get('model', '')} · 输入 {usage['input_tokens']:,} ＋ "
                              f"输出 {usage['output_tokens']:,} ＝ {usage['total_tokens']:,} tokens",
                              f"{original.get('model', '')} · Input {usage['input_tokens']:,} + "
                              f"output {usage['output_tokens']:,} = {usage['total_tokens']:,} tokens"))
    if confirm and items:
        original["unmatched_foods_en"] = [r.get("name_en") or r["name"] for r in pending]
        original.update(served_grams=weights, eaten_fractions=fractions,
                        eaten_fraction=sum(consumed.values()) / sum(weights.values()),
                        partial_record=bool(pending), missing_items=pending, unmatched_foods=names,
                        unmatched=list(dict.fromkeys([*names, *notes])),
                        coverage_decisions=main_decisions + [
                            {"name": r["name"], "name_en": r.get("name_en"), "food_id": decisions[r["key"]]}
                            for r in rows if r["key"] in decisions])
        return {**draft, "input": original}, items
    return None
