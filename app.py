import hashlib
import os
import sqlite3
import sys
from datetime import datetime

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from api_credentials import read_api_key, save_windows_key
from device_diary import cloud_diary
from meals import (
    SG_TIME, allocate_grams, get_profile, list_meals, load_foods, match_text, portion_items, save_meal, total_nutrients,
)
from plan_ui import calendar_for_view, day_summary, profile_form, settings, training_plan
from planning import calorie_balance, day_plan


EXAMPLE = "白饭、水煮鸡"


def photo_api_key(*, use_qwen):
    if use_qwen:
        key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
        if not key:
            try:
                key = st.secrets.get("DASHSCOPE_API_KEY", "").strip()
            except StreamlitSecretNotFoundError:
                pass
        if not key:
            st.info("照片识别尚未启用。现在可以选「按菜名查表」试用记餐。")
        return key
    try:
        api_key = read_api_key()
    except (OSError, UnicodeError):
        st.error("暂时无法读取 Windows 凭据。也可以在电脑上设置 OPENAI_API_KEY 后重新启动服务。")
        return ""

    # Use the server's bind address, independent of any browser-supplied headers.
    local_windows = sys.platform == "win32" and st.get_option("server.address") in {
        "127.0.0.1", "::1", "localhost",
    }
    if local_windows and not os.environ.get("OPENAI_API_KEY", "").strip():
        with st.expander("配置 OpenAI API Key", expanded=not api_key):
            st.caption("保存在这台电脑的 Windows 凭据管理器。"
                       " [打开 OpenAI 密钥管理页](https://platform.openai.com/api-keys)")
            with st.form("local_openai_key", clear_on_submit=True):
                value = st.text_input("OpenAI API Key", type="password", autocomplete="off")
                save = st.form_submit_button("保存密钥")
            if save:
                try:
                    save_windows_key(value)
                except (OSError, ValueError) as exc:
                    st.error(str(exc))
                else:
                    api_key = value.strip()
                    st.success("密钥已保存在本机。在 iPhone 上刷新页面即可上传照片。")
    elif not api_key:
        if sys.platform == "win32":
            st.info("先在电脑本机页面打开「照片识别」，保存 OpenAI API Key，然后刷新手机页面。")
        else:
            st.info("请在服务器设置 OPENAI_API_KEY 后重新启动应用。")
    return api_key


def input_draft(public_demo=False):
    mode = st.radio("录入方式", ["照片识别", "按菜名查表"], index=0 if public_demo else 1, horizontal=True)
    current = st.session_state.draft
    if mode == "按菜名查表":
        text = st.text_input("这餐吃了什么？", value=EXAMPLE, max_chars=400,
                             help="用顿号分隔。例如「半份白饭、蒸鱼、水煮蛋」或「白饭 90g、水煮鸡」。")
        if st.button("查找食物", disabled=not text.strip()):
            current = match_text(text.strip(), load_foods())
            st.session_state.draft = current
        if current["input"]["method"] == "text" and current["input"]["description"] == text.strip():
            return current
        st.caption("修改描述后，点击「查找食物」更新待确认的项目。")
        return None

    use_qwen = public_demo or bool(os.environ.get("DASHSCOPE_API_KEY", "").strip())
    provider = "Qwen4-Max" if use_qwen else "OpenAI"
    api_key = photo_api_key(use_qwen=use_qwen)
    if not api_key:
        return None
    if use_qwen:
        st.caption("点击识别时，这张照片会发送给阿里云百炼北京区的 Qwen4-Max。")
    if st.toggle("直接用相机拍", key="use_camera"):
        upload = st.camera_input("拍下这餐", help="请允许相机权限，也可以关闭上方开关，改从相册选择。")
    else:
        upload = st.file_uploader("选择餐食照片", type=["jpg", "jpeg", "png"], max_upload_size=8)
    if upload is None:
        return None
    from recognition import identify_photo, prepare_photo

    raw = upload.getvalue()
    photo_hash = hashlib.sha256(raw).hexdigest()
    try:
        preview = prepare_photo(raw)
    except ValueError as exc:
        st.error(str(exc))
        return None
    st.image(preview, width=235)
    with st.expander("补充份量线索（选填）"):
        hint = st.text_input("秤重、碗盘直径或包装净重", max_chars=150,
                             placeholder="例如：碗口约 15 cm，或这盒净重 400 g", key=f"scale-{photo_hash}")
    if st.button(f"发送照片给 {provider} 识别"):
        from openai import AuthenticationError, OpenAIError, PermissionDeniedError, RateLimitError

        try:
            with st.spinner("正在匹配照片与食物表…"):
                current = identify_photo(preview, upload.name, load_foods(), api_key=api_key, use_qwen=use_qwen,
                                         portion_hint=hint)
            current["photo_hash"] = photo_hash
            st.session_state.draft = current
        except ValueError:
            st.error("识别结果格式有误，请重试或按菜名查表。")
            return None
        except AuthenticationError:
            st.error(f"{provider} 未接受这个密钥。请由应用维护者核对 API Key 和接入地域。")
            return None
        except PermissionDeniedError:
            st.error(f"请由应用维护者检查这个 Key 对 {provider} 的模型访问权限和账户计费状态。")
            return None
        except RateLimitError as exc:
            if exc.code == "insufficient_quota":
                st.error(f"{provider} 的可用 API 额度不足，请由应用维护者检查计费设置。")
            else:
                st.error(f"已达到 {provider} 的请求限制，请稍后再试。")
            return None
        except OpenAIError:
            st.error("模型请求失败，请检查网络、模型权限和 API 额度，或按菜名查表。")
            return None
    if current.get("photo_hash") == photo_hash:
        show_token_usage(current["input"])
        return current
    return None


def set_grams(key, weight):
    st.session_state[key] = weight


def set_photo_size(view, ranges, suggested):
    choice = st.session_state.get(f"size-{view}")
    for food_id, bounds in ranges.items():
        if bounds:
            values = {"偏小": bounds[0], "按照片估计": suggested[food_id], "偏大": bounds[1]}
            st.session_state[f"grams-{view}-{food_id}"] = values.get(choice, suggested[food_id])


def apply_net_weight(view, selected, suggested):
    foods = load_foods()
    served = {k: st.session_state.get(f"grams-{view}-{k}", suggested.get(k, foods[k].serving_g))
              for k in selected}
    for k, g in allocate_grams(served, st.session_state[f"net-{view}"], minimum=1).items():
        st.session_state[f"grams-{view}-{k}"] = g


def show_token_usage(original):
    usage = original.get("token_usage")
    if usage:
        st.caption(f"本次照片识别 · {original['model']} · 输入 {usage['input_tokens']:,} "
                   f"＋ 输出 {usage['output_tokens']:,} ＝ {usage['total_tokens']:,} tokens")


def edit_meal(draft, db_path=None):
    foods = load_foods()
    original = dict(draft["input"])
    view = draft["id"]
    if variants := draft.get("variants"):
        choice = st.segmented_control("这份餐怎么记？", list(variants), default="整道菜",
                                      key=f"variant-{view}") or "整道菜"
        original.update(variants[choice], portion_mode=choice)
        view += "-" + choice
        st.caption("整道菜已包含碗内配料，另点的小食可以另外记录。")
    suggested = original["suggested_grams"]
    photo = original["method"] == "photo"
    if photo:
        st.caption(original.get("portion_note") or "照片份量为估计，可按实际重量调整。")
    unknown = original["unmatched"]
    acknowledged = True
    if unknown:
        st.warning("请核对：" + "、".join(unknown))
        acknowledged = st.checkbox("我已核对，只将下方选中的项目计入这餐。", key=f"ack-{view}")
    search = st.text_input("搜索或补充食物", placeholder=f"{len(foods):,} 条 · 试试黑豆、falafel、sushi",
                           help=f"查找 {len(foods):,} 条食物与餐品参考记录。", key=f"lookup-{view}")
    select_key = f"foods-{view}"
    options = [*st.session_state.get(select_key, []), *suggested]
    if search.strip():
        matches = foods.search(search)
        options.extend(matches)
        if not matches:
            st.caption("暂未找到，试试英文菜名或单独搜索配料。")
    else:
        options.extend(original.get("alternatives", ()))
        for word in unknown[:3]:
            options.extend(foods.search(word, 4))
        options.extend(["white-rice", "boiled-chicken", "boiled-egg", "fdc-2708555", "fdc-2707359",
                        "fdc-2709307", "fdc-2709738", "fdc-2708202"])
    selected = st.multiselect(
        "核对食物，可补选或移除", options=list(dict.fromkeys(options)), default=list(suggested),
        format_func=lambda k: f"{foods[k].name} · {foods[k].source_label}", key=select_key,
    )
    if not selected:
        st.info("请从食物表中选择至少一项。")
        return
    if "chicken-rice-plate" in selected:
        st.caption("「鸡饭（整盘）」的克数包含鸡肉和油饭。半份整盘与单独减少米饭是两种份量。")

    ranges = original.get("portion_ranges", {})
    if photo and any(ranges.get(k) for k in selected):
        st.segmented_control("照片里的份量", ["偏小", "按照片估计", "偏大"], default="按照片估计",
                             key=f"size-{view}", on_change=set_photo_size, args=(view, ranges, suggested),
                             help="偏小和偏大分别取估算范围的两端。知道克数时可以直接修改。")
    if photo:
        with st.expander("我知道整份净重"):
            measured = st.number_input("食物净重（克，不含容器）", min_value=len(selected), max_value=3000,
                                       value=None, step=1, key=f"net-{view}", placeholder="例如 420")
            st.button("按当前比例分配净重", key=f"apply-net-{view}", on_click=apply_net_weight,
                      args=(view, selected, suggested), disabled=measured is None)
    weights = {}
    for food_id in selected:
        food = foods[food_id]
        quantity_key = f"grams-{view}-{food_id}"
        if quantity_key not in st.session_state:
            st.session_state[quantity_key] = suggested.get(food_id, food.serving_g)
        with st.container(key=f"portion_row_{food_id}"):
            name, amount, shortcut = st.columns([1.5, 1, 0.7], gap="small", vertical_alignment="center")
            name.markdown(f"**{food.name}**")
            bounds = original.get("portion_ranges", {}).get(food_id)
            if photo and bounds:
                name.caption(f"照片估计 {bounds[0]}–{bounds[1]} g")
            elif photo and food_id in suggested:
                name.caption(f"缺少尺度，暂用参考量 {food.serving_g} g")
            elif food.portion_label:
                name.caption(f"{'参考份量' if photo else food.portion_label} {food.serving_g} g")
            else:
                name.caption("按 100 g 查表，请调整实际份量")
            weights[food_id] = amount.number_input(f"{food.name}重量（克）", min_value=1,
                                                   max_value=3000, key=quantity_key)
            shortcut.button("半份", key=f"half-{view}-{food_id}", on_click=set_grams,
                            args=(quantity_key, max(1, round(suggested.get(food_id, food.serving_g) / 2))))
    shares = {1.0: "全部", 0.75: "约 ¾", 0.5: "一半", 0.25: "约 ¼"}
    share = st.segmented_control("这份餐实际吃了多少？", list(shares), format_func=shares.get,
                                 default=1.0, key=f"eaten-{view}") or 1.0
    total_eaten = max(1, round(sum(weights.values()) * share))
    actual = {k: g for k, g in allocate_grams(weights, total_eaten).items() if g}
    items = portion_items(foods, actual)
    st.caption(f"盘中合计 {sum(weights.values())} g · 本次计入 {sum(actual.values())} g")
    totals = total_nutrients([item["nutrients"] for item in items])
    with st.container(key="meal_totals"):
        kcal, protein = st.columns(2)
        kcal.metric("这餐热量", f"{totals['kcal']:.0f} kcal")
        protein.metric("这餐蛋白质", f"{totals['protein_g']:.1f} g")
    if st.button("确认并记入今天", type="primary", width="stretch", disabled=not acknowledged):
        original.update(served_grams=weights, eaten_fraction=share)
        save_meal({**draft, "input": original}, items, db_path=db_path)
        st.session_state.saved = datetime.now(SG_TIME).date()
        st.rerun()
    with st.expander("查看食物数值与来源"):
        st.write(f"这餐还含碳水 {totals['carb_g']:.1f} g、脂肪 {totals['fat_g']:.1f} g。")
        st.caption("按参考份量折算。摊位用油、酱料和实际重量会影响结果。")
        for item in items:
            ref = item["reference_nutrients"]
            st.markdown(
                f"**{item['name']}** · 每 {item['reference_g']} g 含 {ref['kcal']:g} kcal，"
                f"蛋白质 {ref['protein_g']:g} g，碳水 {ref['carb_g']:g} g，脂肪 {ref['fat_g']:g} g。"
                f" [{item['source_label']} · {item['source_code']}]({item['source_url']})"
            )


def show_history(records):
    st.subheader(f"今日记餐 · {len(records)} 笔")
    if not records:
        st.caption("确认第一餐后，这里会显示实际份量和营养小计。")
        return
    total = total_nutrients([record["totals"] for record in records])
    st.write(f"合计 **{total['kcal']:.0f} kcal** · 蛋白质 {total['protein_g']:.1f} g · "
             f"碳水 {total['carb_g']:.1f} g · 脂肪 {total['fat_g']:.1f} g")
    for record in records:
        items = record["items"]
        names = "、".join(item["name"] for item in items)
        with st.expander(f"{record['at']:%H:%M}　{names}　·　{record['totals']['kcal']:.0f} kcal"):
            original = record["input"]
            st.text(("查表输入" if original["method"] == "text" else "照片文件") + " · " + original["description"])
            show_token_usage(original)
            if original.get("served_grams"):
                st.caption(f"盘中合计 {sum(original['served_grams'].values())} g，"
                           f"实际计入 {original.get('eaten_fraction', 1):.0%}。")
            if original["unmatched"]:
                st.text("原始输入中待核对的项目 · " + "、".join(original["unmatched"]))
            for item in items:
                st.markdown(f"{item['name']} · {item['confirmed_g']} g · "
                            f"{item['nutrients']['kcal']:.0f} kcal　[数据出处]({item['source_url']})")


def main(*, public_demo=False):
    st.set_page_config(page_title="食阁记餐", page_icon="🍚", layout="centered")
    st.html("""<style>
      @media (max-width: 640px) {
        .stMainBlockContainer {padding-top: 3.4rem;}
        :is(.st-key-body_measurements, .st-key-daily_balance, .st-key-meal_totals, [class*="st-key-portion_row_"]) [data-testid="stHorizontalBlock"] {
          flex-direction: row; flex-wrap: nowrap; gap: .55rem;
        }
        :is(.st-key-body_measurements, .st-key-daily_balance, .st-key-meal_totals, [class*="st-key-portion_row_"]) [data-testid="stColumn"] {
          flex: 1 1 0 !important; min-width: 0 !important; width: auto !important;
        }
        :is(.st-key-body_measurements, [class*="st-key-portion_row_"]) [data-testid^="stNumberInputStep"] {display: none;}
        :is(.st-key-daily_balance, .st-key-meal_totals) [data-testid="stMetricValue"] {font-size: 1.45rem;}
      }
    </style>""")
    st.title("食阁记餐")
    db_path = cloud_diary() if public_demo else None
    today = datetime.now(SG_TIME).date()
    profile = get_profile(db_path=db_path)
    if notice := st.session_state.pop("notice", None):
        st.success(notice)
    if st.session_state.get("edit_profile") or (profile is None and not st.session_state.get("guest")):
        profile_form(profile, today, db_path, public_demo)
        return
    if st.session_state.get("saved") and st.session_state.saved != today:
        st.session_state.pop("saved")
        st.session_state.pop("draft", None)
    if "draft" not in st.session_state:
        st.session_state.draft = match_text(EXAMPLE, load_foods())
    records = list_meals(today, db_path=db_path)
    if profile:
        days = calendar_for_view(profile, today, db_path)
        plan = day_plan(profile, today, days)
        eaten = total_nutrients([r["totals"] for r in records])
        with st.container(border=True):
            day_summary(profile, today, plan, eaten)
    else:
        st.caption("正在体验记餐。建档后，每餐都能看到今天还差多少。")
        if st.button("建立我的个人计划"):
            st.session_state.guest = False
            st.rerun()
    sections = ["记一餐", "训练安排", "今日记录"] if profile else ["记一餐", "今日记录"]
    section = st.segmented_control("打开", sections, default="记一餐", key="section",
                                   label_visibility="collapsed", selection_mode="single") or "记一餐"
    if section == "记一餐":
        st.subheader("记录一餐")
        if st.session_state.get("saved"):
            if profile:
                label, value = calorie_balance(plan.kcal, eaten["kcal"])
                st.success(f"已记入今天。{label} {value}。")
            else:
                st.success("已记入今天的餐食日志。")
            if st.button("再记一餐"):
                st.session_state.saved = False
                st.session_state.draft = match_text(EXAMPLE, load_foods())
                st.rerun()
        else:
            draft = input_draft(public_demo)
            if draft is not None:
                edit_meal(draft, db_path)
    elif section == "训练安排":
        training_plan(profile, today, days, db_path)
    else:
        show_history(records)
    settings(profile, db_path, public_demo)


if __name__ == "__main__":
    try:
        main()
    except sqlite3.Error:
        st.error("无法读写本地记餐文件。请检查数据库所在目录或稍后重试。")
