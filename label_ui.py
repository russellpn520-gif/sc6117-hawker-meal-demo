"""Review the printed basis once, then change how much was actually consumed."""
import streamlit as st

from i18n import tr
from label_scan import check_energy_unit, empty_label, intake_units, label_item
from meals import update_pending


def _unit_text(unit):
    return {"g": "g", "ml": "mL", "serving": tr("份", "servings"), "package": tr("包", "packs")}.get(unit, "")


def _basis_text(basis):
    return {None: tr("请选择", "Choose basis"), "100g": tr("每 100 g", "Per 100 g"),
            "100ml": tr("每 100 mL", "Per 100 mL"), "serving": tr("每份", "Per serving"),
            "package": tr("每包", "Per pack")}[basis]


def _complete(label):
    try:
        label_item(label, 1, next(iter(intake_units(label)), None))
        return True
    except ValueError:
        return False


def review_label(draft, db_path):
    source = draft["input"]
    label = {**empty_label(), **(source.get("label") or {})}
    prefix = "label-" + draft["id"]
    st.subheader(tr("核对包装标签", "Review the nutrition label"))
    if _complete(label):
        heading = label.get("product_name") or tr("包装食品", "Packaged food")
        st.text(heading)
        st.caption(f"{_basis_text(label['basis'])} · {label['energy']:g} {label['energy_unit']} · "
                   + tr(f"蛋白质 {label['protein_g']:g} g · 碳水 {label['carb_g']:g} g · 脂肪 {label['fat_g']:g} g",
                        f"Protein {label['protein_g']:g} g · Carbs {label['carb_g']:g} g · Fat {label['fat_g']:g} g"))
    else:
        st.info(tr("请对照包装补齐同一列的热量和三大营养素。读不清的数值可以留空，稍后再确认。",
                   "Fill in energy and all three macros from the same printed column. Leave unreadable values blank and return later."))
    if label.get("preparation") == "prepared":
        st.caption(tr("标签这一列按冲调或烹调后的食品计算，请填写相应的食用量。",
                      "This label column is for the prepared product. Enter the amount consumed after preparation."))
    with st.expander(tr("修改标签数值", "Edit label values"), expanded=not _complete(label)):
        label["product_name"] = st.text_input(tr("食品名称（选填）", "Food name (optional)"),
                                              value=label.get("product_name") or "", max_chars=100, key=prefix+"-name")
        options = [None, "100g", "100ml", "serving", "package"]
        basis_labels = {key: _basis_text(key) for key in options}
        label["basis"] = st.selectbox(tr("标签数值对应", "Label values apply to"), options,
                                      index=options.index(label.get("basis")), format_func=basis_labels.__getitem__, key=prefix+"-basis")
        col1, col2 = st.columns(2)
        label["energy"] = col1.number_input(tr("热量", "Energy"), value=label.get("energy"), min_value=0.0,
                                           step=0.1, key=prefix+"-energy")
        units = [None, "kcal", "kJ"]
        label["energy_unit"] = col2.selectbox(tr("热量单位", "Energy unit"), units, format_func=lambda x: x or "—",
                                               index=units.index(label.get("energy_unit")), key=prefix+"-energy-unit")
        cols = st.columns(3)
        for col, field, name in zip(cols, ("protein_g", "carb_g", "fat_g"),
                                    (tr("蛋白质 (g)", "Protein (g)"), tr("碳水 (g)", "Carbs (g)"), tr("脂肪 (g)", "Fat (g)"))):
            label[field] = col.number_input(name, value=label.get(field), min_value=0.0, step=0.1,
                                            key=prefix+"-"+field)
        size_name = (tr("整包净含量（选填）", "Net amount per pack (optional)") if label["basis"] == "package"
                     else tr("每份含量（选填）", "Amount per serving (optional)"))
        col1, col2 = st.columns(2)
        label["portion_size"] = col1.number_input(size_name, value=label.get("portion_size"),
                                                  min_value=0.0, step=0.1, key=prefix+"-size")
        units = [None, "g", "ml"]
        label["portion_unit"] = col2.selectbox(tr("含量单位", "Amount unit"), units, format_func=lambda x: _unit_text(x) or "—",
                                              index=units.index(label.get("portion_unit")), key=prefix+"-size-unit")
    units = intake_units(label)
    chosen, amount = None, None
    if units:
        chosen = source.get("eaten_unit") if source.get("eaten_unit") in units else units[0]
        if len(units) > 1:
            labels = {key: _unit_text(key) for key in units}
            chosen = st.radio(tr("食用量单位", "Unit consumed"), units, index=units.index(chosen),
                              key=prefix+"-unit-"+label["basis"], format_func=labels.__getitem__, horizontal=True)
        amount = st.number_input(tr(f"实际吃了多少（{_unit_text(chosen)}）", f"Amount consumed ({_unit_text(chosen)})"),
                                 value=source.get("eaten_amount") if source.get("eaten_unit")==chosen else None,
                                 min_value=0.0, step=0.25 if chosen in ("serving","package") else 1.0,
                                 key=prefix+"-amount-"+chosen)
    payload = {**draft, "input": {**source, "label": label, "eaten_amount": amount, "eaten_unit": chosen}}
    # Persist edits before confirmation, so closing the browser keeps the corrected draft.
    if payload["input"] != source:
        update_pending(payload, db_path=db_path)
    item = None
    if amount and _complete(label):
        item = label_item(label, amount, chosen)
        t = item["nutrients"]
        st.write(tr(f"这次摄入约 {t['kcal']:.0f} kcal，蛋白质 {t['protein_g']:.1f} g、碳水 {t['carb_g']:.1f} g、脂肪 {t['fat_g']:.1f} g。",
                    f"This portion has about {t['kcal']:.0f} kcal, {t['protein_g']:.1f} g protein, {t['carb_g']:.1f} g carbs and {t['fat_g']:.1f} g fat."))
    unit_verified = True
    if check_energy_unit(label):
        st.warning(tr("热量和三大营养素折算后相差约四倍。请核对原图上的 kJ／kcal，以及这些数字是否来自同一列。",
                      "Energy and macros differ by roughly a factor of four. Check kJ versus kcal and use the same column on the label."))
        reading = tuple(label[field] for field in ("basis", "energy", "energy_unit", "protein_g", "carb_g", "fat_g"))
        unit_verified = st.checkbox(tr("我已对照原图核实这一列和热量单位", "I verified this column and energy unit against the label"),
                                    key=f"{prefix}-verified-{reading}")
    if st.button(tr("按标签确认记餐", "Confirm label entry"), key=prefix+"-confirm", type="primary",
                 disabled=item is None or not unit_verified, width="stretch"):
        return payload, [item]
    if usage := source.get("token_usage"):
        st.caption(tr(f"标签识别 · {source['model']} · {usage['total_tokens']} tokens",
                      f"Label scan · {source['model']} · {usage['total_tokens']} tokens"))
    return None


def label_history(item):
    label = item["label"]
    amount, unit = item["eaten_amount"], _unit_text(item["eaten_unit"])
    st.write(tr(f"实际计入 {amount:g} {unit}", f"Consumed {amount:g} {unit}"))
    st.caption(tr("包装营养标签 · 已由你核对", "Package nutrition label · reviewed by you"))
    st.caption(f"{_basis_text(label['basis'])} · {label['energy']:g} {label['energy_unit']} · "
               + tr(f"蛋白质 {label['protein_g']:g} g · 碳水 {label['carb_g']:g} g · 脂肪 {label['fat_g']:g} g",
                    f"Protein {label['protein_g']:g} g · Carbs {label['carb_g']:g} g · Fat {label['fat_g']:g} g"))
