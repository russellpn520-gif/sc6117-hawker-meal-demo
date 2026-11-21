# 食阁记餐 · SC6117 Track 3 Demo

这版给经常在食阁吃饭、也有训练安排的组员试用。它处理一件日常小事：记录实际吃下的一餐，核对份量，并在训练改期时更新今天和明天的示例目标。

[打开公开体验版](https://sc6117-hawker-meal.streamlit.app/) · [保存手机二维码](assets/demo-qr.png)

## 启动

在本目录用 Python 3.12 和 uv 运行。

```sh
uv sync --locked
uv run streamlit run app.py --server.address 127.0.0.1 --server.port 8617
```

打开 [本地应用](http://127.0.0.1:8617)。菜名查表、营养换算、记餐和训练改期均可离线运行。单用户日志按新加坡日期存入本机 `.local/meals.sqlite3`，重新打开页面仍能看到当天记录。测试可通过 `TRACK3_DB` 指向独立的 SQLite 文件。

**照片识别。** 在 Windows 电脑的本机页面选「照片识别」，在「配置 OpenAI API Key」中粘贴个人密钥，点「保存密钥」。密钥保存在当前 Windows 用户的凭据管理器中，凭据名为 `SC6117/track3-demo/OpenAI`。在同一台电脑运行的手机入口刷新后即可使用。已有密钥副本可以直接使用；新建时请选对项目并当场复制完整密钥。[OpenAI 密钥管理页](https://platform.openai.com/api-keys) · [官方密钥说明](https://help.openai.com/en/articles/4936850-where-do-i-find-my-openai-api-key)

在 iPhone 上选「照片识别」，选择一张不超过 8 MB 的 JPG 或 PNG，再点「发送照片给 OpenAI 识别」。调用从运行应用的服务器发出，按密钥所属 API 项目计费。照片识别成功后，页面显示该次 API 回传的输入、输出和总 token 数。模型给出菜名候选和疑点，确认份量后才会记餐。菜名查表、改份量、记餐和训练改期均消耗 0 个 API token。

各平台也可在启动服务的终端设置 `OPENAI_API_KEY`，该环境变量优先。默认模型为 `gpt-5.4-mini`；可用 `TRACK3_MODEL` 指定支持图片输入和结构化输出的模型。

## Streamlit Community Cloud

部署时选择 `main` 分支、入口 `cloud_app.py` 和 Python 3.12。公开体验版为每个浏览器会话单独保存餐食和训练安排。重新载入页面会开始新会话。iPhone 用相机扫描应用网址的二维码，点弹出的链接，即可在 Safari 使用。

需要启用照片时，由维护者在应用的 **Settings → Secrets** 添加顶层 `OPENAI_API_KEY`。持有链接的访客均可发起付费识别，费用归这把密钥所属的 API 项目。未配置密钥时，访客可以使用完整的菜名查表流程。维护者把代码提交并推送至已部署的分支后，同一网址会自动更新。[Streamlit 更新说明](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app)

## 一分钟试用

1. 打开默认的「白饭、水煮鸡」。白饭 180 g、水煮鸡 90 g，按表折算共 413 kcal。点白饭一行的「半份」，热量变为 289 kcal。展开「查看食物数值与来源」可核对每行出处。
2. 点「确认并记入今天」。右侧点「今天安排一次训练」，再点「把今天的训练移到明天」。观察今日和明日的热量、蛋白质目标，以及已记的一餐。这里采用两组虚构目标演示联动。
3. 点「再记一餐」，试「半份白饭、蒸鱼、水煮蛋」或「半份白饭、榴莲」。第二个输入包含库外食物，页面会点明缺项，用户核对后才可保存所选部分。

## 数据从哪里来

`foods.csv` 收录 9 条新加坡 HPB–MOH 2016 年附表 A 的参考食物。表中保留英文原名、原始标准份克数、该份热量和三种宏量营养素，并记录印刷页码 101 或 102。数值用于演示估算，真实摊位的烹调和份量会有差异。默认例子是白饭配水煮鸡；「鸡饭（整盘）」有独立条目，改它的克数会按比例缩放整道菜。扩大菜品覆盖时，可使用 HPB 当前提供的 SG FoodID 工具逐条核对，也可为包装食品加入标签来源。[附表 A 原文](https://isomer-user-content.by.gov.sg/484/d2884b81-4dfc-4a9e-b153-1487969794d5/obesity-cpg_main_for-online-30-aug.pdf#page=108) · [SG FoodID](https://www.hpb.gov.sg/healthy-living/food-and-beverage/sgfoodid/)

## 数据结构与课堂、GitHub 参考

| 参考 | 在本项目里的取舍 |
| --- | --- |
| 本班 Session 2 的选课助手用 `ask_user` 暂停，请用户补足信息。见课堂教程包 `Session2_Tutorial(1).zip` 中的 `deepagent/app.py`。 | 记餐也有可见的确认步骤。照片模式通过 LangChain 获取结构化候选，用户核对种类和份量，Python 查表换算，然后写入日志。固定的记餐步骤用普通函数串联。 |
| 同课往届 **HirePrep** 用 `SavedInput` 表示输入，用 `SavedHistory` 关联当时的输入、输出、ID 和时间。[源码](https://github.com/chris-cc-eth/HirePrep/blob/3c2a08b12264ae9ee0fe4883164ef842a31f563b/lib/storage.ts) | 餐食草稿有稳定 ID；确认时将原始描述、建议份量、最终克数和营养快照一起存入 SQLite。可以复盘用户改了什么，重复提交同一草稿只写一笔。 |
| 同课往届 **Synapse** 把难例建模为 `HardSample`，保留原始内容和候选归属。[类型定义](https://github.com/CongxiangZhou/Synapse_AI-Powered-Knowledge-Base/blob/bcc3faeea8188879259108110f020a2c0e2f79af/types.ts) | 库外食物和模型疑点保留在 `input.unmatched`。后续可以筛出「漏酱料」「油饭与白饭混淆」等真实失败，回查输入。 |
| 课堂 Git 教程链接的 **tianhuat** 账号另有食品分类项目，以 `item_id` 关联图片、元数据和多个食物类别。[预测代码](https://github.com/tianhuat/food_image_classification/blob/ec600ab4ff24f5915b51521ae04eb97da091b508/food_prediction_test.py) | 参考它以标识符连接识别结果与食品条目的做法。该项目的标签描述食物类别，营养值由本项目自己的参考表提供。 |
| **Nutrition5k** 的餐盘记录包含食材 ID、每种食材的克数和全餐总量，同一餐盘的多次采样进同一个数据划分。[元数据与划分说明](https://github.com/google-research-datasets/Nutrition5k#dish-metadata) | `items[]` 按食物保存重量和营养。评测可按整餐拆分开发和测试样本，同一盘菜的多张图进同一组；新加坡食阁餐另行采集。 |
| **wger** 分开记实际次数和目标次数、实际重量和目标重量，单组记录关联训练场次和动作。[WorkoutLog](https://github.com/wger-project/wger/blob/aebe882a87c2236be896dde085b1d02b185999b9/wger/manager/models/log.py) | 后续可按「场次 → 动作 → 每组计划值及完成值」扩展训练记录。当前 demo 的训练表仅存日期，用来验证改期和目标联动。 |

往届仓库用于比较设计。本届交付和评测要求见课程资料中的 `Capstone_Project_Spec_v2.pdf` 和 `Capstone_Project_Tracks_v2.pdf`。

### 已实现的字段

| 对象 | 主要字段及用途 |
| --- | --- |
| 食物参考项 | `food_id`、原文名称、`serving_g`、该份的 `kcal/protein_g/carb_g/fat_g`、出处页码。 |
| 餐食草稿 | UUID、输入方式、原始描述或文件名、建议的食物与克数、未匹配项。建议克数来自菜名中明确提供的重量、半份标记或表内标准份。 |
| 已确认餐食 | 新加坡日期与确认时间、输入快照、`items[]`、`totals`。每项带 `food_id`、`confirmed_g`、参考份量及参考营养、来源 URL 和折算值。 |
| 训练日期 | 同一天最多一条。改期后按日类型选用热量及蛋白质目标，再减去已确认餐食。 |

## 做到课程提交还差什么

- **模型与数据。** 用团队有权限的视觉模型跑真实照片，覆盖油饭、混合菜、酱料及包装标签。扩充带来源和单位的食品表。
- **公平比较。** 先留出至少 30 份标注餐食，记录 `meal_id`、输入、类别、参考份量、参考值和来源。用相同输入和用户提示比较裸模型与完整流程，按包装／食阁分别报告热量和三种宏量营养素的绝对误差。可加一列用户纠正前结果，量化确认步骤的贡献。开发样本另放；保留至少 10 个实际失败案例并逐例分析。
- **训练与餐单。** 从一位组员收集器械、可训练日、目标、历史训练、预算、过敏和忌口。加入动作安排及每组实际完成值，检查超出可用天数、器械不匹配、休息不足、负荷突增、过敏原和超预算。再做漏练调整、餐单和购物清单。
