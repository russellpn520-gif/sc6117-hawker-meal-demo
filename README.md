# 食阁记餐 · SC6117 Track 3 Demo

拍照或输入菜名，查询多地区食材和菜品，再按实际吃下的重量记餐。首次填写年龄、身高、体重和运动习惯即可建立个人计划。首页会更新今日热量和蛋白质余量，训练改期会重新计算相应日期的目标。

[打开食阁记餐](https://sc6117-hawker-meal.streamlit.app/) · [保存可转发的手机二维码](https://raw.githubusercontent.com/russellpn520-gif/sc6117-hawker-meal-demo/main/assets/demo-qr.png)

## 两类数据来源

1. **每餐营养**来自 USDA、英国 CoFID、台湾食药署、FAO/INFOODS 西非食物表、新加坡官方与实测数据，以及注明市场的厂商菜单。共 19,115 条，按实际吃下的克数换算。[来源、数量与原表](data/SOURCES.md)
2. **一天需要多少。** Mifflin–St Jeor 成人静息能量消耗公式（1990）根据年龄、身高、体重和性别系数估算静息代谢。Demo 再结合活动量和训练日程设置每日热量目标。[公式原文](https://pubmed.ncbi.nlm.nih.gov/2305711/) · [项目计算代码](planning.py)

运动档位另参考 Cronometer 和 Polar，蛋白质与活动建议参考新加坡 HealthHub。各项依据和演示用的热量分配比例见下方「个人计划怎么算」。Qwen4-Max 从照片中识别菜品，并根据可见的容器、食物面积、厚度或数量给出粗略克数范围。营养值由程序查表计算。

## 手机访问与协作

用 iPhone 相机扫码，或点上方「打开食阁记餐」。如 Safari 提示「此连接非私人连接」，先返回。核对网址和「设置 → 通用 → 日期与时间 → 自动设置」，再用蜂窝数据打开同一网址。若仍有警告，请将警告标题和域名发给维护者，截图时可遮住个人信息。[Apple 的连接安全说明](https://support.apple.com/zh-cn/102279) · [Apple 的网络排查步骤](https://support.apple.com/zh-cn/102456)

这个公共仓库可匿名浏览。组员登录 GitHub 后可点文件页右上角的铅笔，在个人副本中编辑，再通过 Pull Request 把改动提交给项目。直接推送至主分支需要仓库写权限。[编辑项目说明](https://github.com/russellpn520-gif/sc6117-hawker-meal-demo/edit/main/README.md) · [GitHub 网页编辑说明](https://docs.github.com/en/repositories/working-with-files/managing-files/editing-files)

## 启动

在本目录用 Python 3.12 和 uv 运行。

```sh
uv sync --locked
uv run streamlit run app.py --server.address 127.0.0.1 --server.port 8617
```

打开 [本地应用](http://127.0.0.1:8617)。菜名查表、营养换算、记餐和训练改期均可离线运行。单用户日志按新加坡日期存入本机 `.local/meals.sqlite3`，重新打开页面仍能看到当天记录。测试可通过 `TRACK3_DB` 指向独立的 SQLite 文件。

**照片识别**使用阿里云百炼北京区的 `qwen4-max`。在 iPhone 上打开公开版，选「照片识别」，从相册上传不超过 8 MB 的 JPG 或 PNG，或打开「直接用相机拍」，然后点「发送照片给 Qwen4-Max 识别」。页面会显示候选食物、需要核对的项目，以及这次 API 回传的输入、输出和总 token。核对食物与克数后，点「确认并记入今天」。[Qwen4-Max 模型说明](https://www.alibabacloud.com/help/en/model-studio/qwen4-max)

本机启动前可在环境中设置北京区的 `DASHSCOPE_API_KEY`，使用与公开版相同的识别流程。菜名查表、改份量、记餐和训练改期均消耗 0 个 API token。

本机没有配置百炼时，可继续使用 OpenAI。设置 `OPENAI_API_KEY`，或在 Windows 本机页面的「照片识别 → 配置 OpenAI API Key」中保存密钥至当前用户的 Windows 凭据管理器。此模式默认使用 `gpt-5.4-mini`，可用 `TRACK3_MODEL` 另选兼容的 OpenAI 模型。

## Streamlit Community Cloud

部署使用 `main` 分支、入口 `cloud_app.py` 和 Python 3.12。iPhone 用相机扫描原二维码，点弹出的链接即可在 Safari 使用。默认每个浏览器会话有独立日志。勾选「在这台设备记住我的记录」后，同一浏览器可凭本地随机标识跨会话找回个人档案和餐食；清除浏览器数据会失去入口，Community Cloud 重置临时磁盘也会清空记录。可从「个人设置与估算依据」清除自己的全部数据。二维码只包含公开应用网址。识别请求包含餐食图片、可选份量线索和识别指令。

维护者在应用的 **Settings → Secrets** 设置顶层 `DASHSCOPE_API_KEY`。每次点击发送照片，服务器会调用百炼北京区。访客共用服务端密钥，调用按对应百炼工作空间的额度和价格结算。更换密钥只需更新 Secrets。维护者把代码推送至已部署的分支后，同一网址会自动更新。[百炼地域与接入地址](https://www.alibabacloud.com/help/en/model-studio/base-url) · [Streamlit 更新说明](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app)

## 一分钟试用

1. 扫码后填写个人资料，选择近三个月的运动习惯，点「生成我的计划」。昵称和代谢公式系数都可以跳过。默认目标是维持体重，也可选「先试试记餐」直接体验。
2. 选一张餐食照片，点识别，核对食物和克数后点「确认并记入今天」。也可切换到「按菜名查表」试默认的白饭 180 g、水煮鸡 90 g，共 413 kcal；点白饭的「半份」后为 289 kcal。首页用今天的目标减去所有已确认餐食，给出剩余热量和蛋白质。
3. 点「训练安排 → 把今天的训练移到明天」，可以看到两天的目标同时变化。也可展开两周安排选择其他日期。「今日记录」可以复查餐食、份量和来源。

### 个人计划怎么算

成人静息代谢使用 Mifflin–St Jeor 的静息能量消耗公式，单位为 kcal/天。年龄使用周岁，身高使用厘米，体重使用公斤。选择公式系数后显示一个估值；跳过就同时保留两种系数的上下界，首页显示距离下限的热量，达到区间后提示已达标。未满 18 岁可单独使用记餐功能。[原始研究](https://pubmed.ncbi.nlm.nih.gov/2305711/)

| 近三个月的运动习惯 | 活动系数 | 初始每周建议 |
| --- | ---: | --- |
| 没有运动习惯，通常每周 0 天 | 1.20 | 从 1 次轻松步行开始 |
| 偶尔活动，通常每周 1–2 天 | 1.375 | 2 天活动 |
| 经常活动，通常每周至少 3 天 | 1.50 | 3 天活动，交替有氧和力量 |
| 专业运动员，系统备赛，通常每周训练超过 12 小时 | 1.90 | 6 个可改期的训练日，具体内容跟随教练安排 |

四档将主流应用的活动系数、训练频率和运动员训练量简化为一道选择题。初始日期从建档日算起并每七天重复。休息与训练的具体日期可以调整。[Cronometer 活动系数](https://support.cronometer.com/hc/en-us/articles/31974307318420-Energy-Expenditure) · [Polar 训练背景](https://support.polar.com/uk-en/support/what_is_my_training_background) · [新加坡身体活动指南](https://ch-api.healthhub.sg/api/public/content/05d4db1555854bd28def9106daf34a8d?v=5fc26500)

平均每日维持热量约为静息代谢乘以活动系数。可在个人设置选择温和减脂或增重，演示目标在均值基础上调整约 5%。专业运动员维持原估值，BMI 低于 18.5 时也不会下调。建档日起每七天保持同一热量预算，训练日和休息日的目标相差约均值的 8%。这个比例是为了示范日程联动，具体目标应结合实际情况校准。跨周改期时两周分别平衡。餐食记录始终按实际用餐日期统计。

蛋白质的起始系数依次为每公斤体重 0.8、1.0、1.2、1.5 g；50 岁及以上取至少 1.2 g。演示中的训练日再增加每公斤 0.1 g。孕哺期、康复期或有特殊需求的用户可与专业人员商定个人目标。[成人蛋白质参考](https://www.healthhub.sg/well-being-and-lifestyle/food-diet-and-nutrition/why_protein_is_important) · [运动营养参考](https://www.healthhub.sg/well-being-and-lifestyle/food-diet-and-nutrition/power_up_sports_nutrition)

## 数据从哪里来

数据随应用发布，可离线按中英文检索如寿司、墨西哥饭碗、鹰嘴豆泥、鹰嘴豆咖喱或西班牙海鲜饭。相同菜名的不同做法保留各自出处。相机识别混合餐时可切换「整道菜」和「按配料」，在两种方式间切换会替换对应项目。可选填餐盘直径或包装净重，按照片范围选择偏小或偏大，也可以手动修改盘中克数，再选全部、四分之三、一半或四分之一。最终只计入吃下的重量，缺少尺度时会标出暂用参考量。[完整数据来源](data/SOURCES.md) · [MyFitnessPal 拍照记餐流程](https://support.myfitnesspal.com/hc/en-us/articles/360045761612-How-to-use-the-Meal-Scanner) · [Cronometer 拍照记餐流程](https://support.cronometer.com/hc/en-us/articles/39013533811092-Mobile-Photo-Logging)

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
| 食物参考项 | 稳定条目标识、原名和别名、营养基准重量、建议份重、四项营养值、来源代码和链接。 |
| 餐食草稿 | UUID、原始输入、建议条目、未匹配项。照片还带视觉份量范围、可选参照和整道菜或配料的核对方式。确认时保留盘中克数与实际吃下的比例。 |
| 已确认餐食 | 新加坡日期与确认时间、输入快照、`items[]`、`totals`。每项带 `food_id`、`confirmed_g`、参考份量及参考营养、来源 URL 和折算值。 |
| 个人资料 | 昵称、年龄、身高、体重、活动档位、可选公式系数、目标、建档日期。 |
| 训练日期 | 每周模板加按日训练或休息的改动。改期在一个 SQLite 事务中完成，首页实时计算目标及余量。 |

## 做到课程提交还差什么

- **模型与数据。** 用团队有权限的视觉模型跑真实照片，覆盖油饭、混合菜、酱料及包装标签。扩充带来源和单位的食品表。
- **公平比较。** 先留出至少 30 份标注餐食，记录 `meal_id`、输入、类别、参考份量、参考值和来源。用相同输入和用户提示比较裸模型与完整流程，按包装／食阁分别报告热量和三种宏量营养素的绝对误差。可加一列用户纠正前结果，量化确认步骤的贡献。开发样本另放；保留至少 10 个实际失败案例并逐例分析。
- **训练与餐单。** 从一位组员收集器械、可训练日、目标、历史训练、预算、过敏和忌口。加入动作安排及每组实际完成值，检查超出可用天数、器械不匹配、休息不足、负荷突增、过敏原和超预算。再做漏练调整、餐单和购物清单。
