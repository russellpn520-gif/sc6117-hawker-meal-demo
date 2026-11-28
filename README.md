# 食阁记餐 · SC6117 Track 3 Demo

吃饭前拍一张，吃完再确认。第一次打开就能记餐，拍下的餐会先出现在待确认列表。饭后可以分别调整米饭、配菜或饮品实际吃了多少。想看每日热量和蛋白质目标时，再填写个人资料与运动习惯。训练改期后，相应日期的目标会一起更新。

[打开食阁记餐](https://sc6117-hawker-meal.streamlit.app/) · [保存可转发的手机二维码](https://raw.githubusercontent.com/russellpn520-gif/sc6117-hawker-meal-demo/main/assets/demo-qr.png)

## 两类数据来源

1. **每餐营养**来自 USDA、英国 CoFID、台湾食药署、FAO/INFOODS 西非食物表、新加坡官方与实测数据，以及注明市场的厂商菜单。共 19,115 条，按实际吃下的克数换算。[来源、数量与原表](data/SOURCES.md)
2. **一天需要多少。** Mifflin–St Jeor 成人静息能量消耗公式（1990）根据年龄、身高、体重和性别系数估算静息代谢。Demo 再结合活动量和训练日程设置每日热量目标。[公式原文](https://pubmed.ncbi.nlm.nih.gov/2305711/) · [项目计算代码](planning.py)

运动档位另参考 Cronometer 和 Polar，蛋白质与活动建议参考新加坡 HealthHub。各项依据和演示用的热量分配比例见下方「个人计划怎么算」。OpenAI GPT-5 mini 根据餐食、容器和可见参照物估计食物种类及份量范围。营养值由程序查表计算。

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

**照片识别**使用 OpenAI Responses API 和 `gpt-5-mini`。在手机上点「拍下这餐」或「从相册选」，浏览器会压缩照片并保存草稿。首次在公共站点使用识别时，输入组内私下分发的拍照码。服务端向 OpenAI 提交餐食照片和识别指令，关闭响应存储和自动重试。饭后再确认实际吃下的份量，才会计入日记。每餐识别详情显示 API 返回的实际输入、输出和合计 token 数。[模型说明与价格](https://developers.openai.com/api/docs/models/gpt-5-mini)

本机可在项目目录未跟踪的 `.env` 中设置 `OPENAI_API_KEY`，也支持环境变量。Windows 回环地址下另支持本机凭据管理器。在局域网部署还需设置随机的 `TEAM_PHOTO_CODE`（至少 12 位）。查表、调整份量、确认记餐、训练改期及切换语言均消耗 0 个 API token。

## Streamlit Community Cloud

部署使用 `main` 分支、入口 `cloud_app.py` 和 Python 3.12。原二维码只含公开应用网址。每个浏览器通过本地随机标识找回自己的待确认餐、档案和日记。在共享手机上，同一浏览器的使用者也能打开这份日记。清除浏览器数据会失去原入口；浏览器限制本地存储时，按页面提示在当前会话完成确认。

待确认餐在云端临时 SQLite 中保留压缩照片与识别结果，应用也尝试在本机浏览器备份这些草稿。确认记餐或舍弃草稿后，应用移除对应照片并同步设备备份。已确认的日记保存食物、份量、来源和营养快照。Community Cloud 临时磁盘重置后，已备份的草稿可在原浏览器恢复；已确认日记和个人档案依赖云端临时存储。可在个人设置中清除自己的记录。

维护者在 **Settings → Secrets** 设置顶层 `OPENAI_API_KEY` 和随机的 `TEAM_PHOTO_CODE`。照片识别使用组内共享的课程额度。拍照码验证通过后，同一浏览器在应用存储保留期间可继续识别；更换拍照码会撤销旧授权。公开二维码只用于打开应用。把更新推送至部署分支后，原网址和二维码会自动载入新版本。[Streamlit Secrets](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management)

## 一分钟试用

页顶可随时切换「中文 / English」。语言偏好保存在当前浏览器，两种语言共用草稿、日记和训练计划。[English interface](https://sc6117-hawker-meal.streamlit.app/?lang=en)

如果照片只匹配到部分食物，页面会标出已选小计和漏掉的菜名。可以补选匹配项、搜索替代或标明没吃；也可明确选择只记录已有项目。这类记录在日记和当天的余量提示里会标为部分记录。

1. **餐前**用 iPhone 扫原二维码，点「拍下这餐」。也可以从相册选一张餐食照，或按菜名查表。第一次使用就能拍照。
2. **餐后**用同一浏览器打开待确认的餐。如果都吃完了，点「全部吃完，确认记餐」。如果只剩了半份米饭，展开「有哪样没吃完？」，把米饭调到一半，鸡肉和配菜照原量计入。混合餐识别出了配料时，可以选「按配料」分别调整。菜名或估量有出入时，到「改菜名或餐盘份量」更正。
3. **看当天安排**时建立个人计划，填写年龄、身高、体重和运动习惯。首页按已确认餐食更新热量和蛋白质进度。训练挪到明天时，可以看到两天的目标同时变化；也可展开两周安排选择其他日期。日记可以复查已确认餐食的份量和来源。

### 个人计划怎么算

成人静息代谢使用 Mifflin–St Jeor 的静息能量消耗公式，单位为 kcal/天。年龄使用周岁，身高使用厘米，体重使用公斤。选择公式系数后显示一个估值；跳过就同时保留两种系数的上下界，以区间表示当天的热量参考量。未满 18 岁可单独使用记餐功能。[原始研究](https://pubmed.ncbi.nlm.nih.gov/2305711/)

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

数据随应用发布，可离线按中英文检索寿司、墨西哥饭碗、鹰嘴豆泥、鹰嘴豆咖喱或西班牙海鲜饭等食物。相同菜名的不同做法保留各自出处。混合餐可按整道菜或识别出的配料记录，两种方式会替换对应项目。知道包装净重或实称克数时，可以在份量调整中校准。饭后独立选择每项实际吃下的比例，营养小计随各项实吃克数更新。[完整数据来源](data/SOURCES.md) · [MyFitnessPal 拍照记餐流程](https://support.myfitnesspal.com/hc/en-us/articles/360045761612-How-to-use-the-Meal-Scanner) · [Cronometer 拍照记餐流程](https://support.cronometer.com/hc/en-us/articles/39013533811092-Mobile-Photo-Logging)

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
| 餐食草稿 | UUID、拍摄或选图时间、识别状态、压缩照片、建议条目、未匹配项、视觉份量范围。 |
| 已确认餐食 | 日期、确认时间、输入快照、各项盘中克数与实吃比例、`items[]`、`totals`。照片餐按拍摄或选图时的新加坡日期入账。每项保存 `food_id`、`confirmed_g`、参考营养、来源 URL 和折算值。 |
| 个人资料 | 昵称、年龄、身高、体重、活动档位、可选公式系数、目标、建档日期。 |
| 训练日期 | 每周模板加按日训练或休息的改动。改期在一个 SQLite 事务中完成，首页实时计算目标及余量。 |

## 做到课程提交还差什么

- **模型与数据。** 用团队有权限的视觉模型跑真实照片，覆盖油饭、混合菜、酱料及包装标签。扩充带来源和单位的食品表。
- **公平比较。** 先留出至少 30 份标注餐食，记录 `meal_id`、输入、类别、参考份量、参考值和来源。用相同输入和用户提示比较裸模型与完整流程，按包装／食阁分别报告热量和三种宏量营养素的绝对误差。可加一列用户纠正前结果，量化确认步骤的贡献。开发样本另放；保留至少 10 个实际失败案例并逐例分析。
- **训练与餐单。** 从一位组员收集器械、可训练日、目标、历史训练、预算、过敏和忌口。加入动作安排及每组实际完成值，检查超出可用天数、器械不匹配、休息不足、负荷突增、过敏原和超预算。再做漏练调整、餐单和购物清单。
