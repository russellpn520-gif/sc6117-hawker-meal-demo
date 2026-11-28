# 最终版同图评测 · 2026-11-28

GPT-5 mini 在两条路径看到同一张照片。15 张包装背标均产生了可复算的四项数值，App 的碳水和脂肪平均误差较小，直接问模型的热量和蛋白质平均误差较小。15 张食阁照片中，App 首次识别只给出 1 份完整结果和 1 份小计，另有 13 份需要用户补选。这些样本支持保留人工核对步骤。[逐张结果与标签原始读数](release_results.csv) · [冻结清单与照片来源](release_samples.csv)

## 相同照片上的平均绝对误差

| 照片与计分范围 | 方法 | 样本数 | 热量 kcal | 蛋白质 g | 碳水 g | 脂肪 g |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 包装背标，全部 | 直接问模型 | 15 | 9.71 | 0.44 | 3.07 | 0.18 |
| 同上 | App 读表后按实吃量换算 | 15 | 26.04 | 0.58 | 0.006 | 0.11 |
| 食阁，全部 | 直接问模型 | 15 | 84.73 | 4.92 | 11.50 | 4.63 |
| 食阁，App 给出完整值或小计的同两张 | 直接问模型 | 2 | 234.00 | 9.10 | 28.90 | 7.60 |
| 同上 | App 自动结果 | 2 | 205.06 | 10.39 | 16.11 | 10.71 |
| 食阁，仅 App 标为完整的一张 | 直接问模型 | 1 | 7.00 | 0.20 | 0.80 | 0.20 |
| 同上 | App 自动结果 | 1 | 54.71 | 1.12 | 1.83 | 4.44 |

误差取每张估计值与参考值差的绝对值，再求平均。两种方法均使用同一张 JPEG、同一消费份量。无输出保留为空。部分匹配行用小计对照整份参考量，量化漏记可能有多大。“完整”仅表示产生四个数字且流程未标记缺项。直接模型在两类各 15 张上都返回了数值。

## 四个影响真实使用的例子

| 照片 | 两条路径看到了什么 | 对记餐的影响 |
| --- | --- | --- |
| H10 马来米粉汤 | 直接模型报 820 kcal。App 仅查到 3.60 kcal 的配料。参考份为 359 kcal。 | 把小计作为整餐会少计 355.40 kcal。App 提示补主菜，可保留独立的配菜和饮品。 |
| H05 墨鱼馅油条 | App 查到普通油条 21 g，报 115.71 kcal。图文参考为有馅的 18 g、61 kcal。 | 即便流程显示完整，馅料、做法和份量仍需核对。 |
| P07 酸奶 | 标签为 1020 kJ／份。App 识别为 1020 kcal／份，半份得 510 kcal；参考值为 121.89 kcal。直接模型给出 122 kcal。 | 这一项使包装组总绝对热量误差增加 388.11 kcal。评测后加入单位复核提示。 |
| P11 全麦面包 | App 给出 2.84 g 蛋白质，标签按实吃 86 g 折算为 11.5 g。P06 的另一款面包则是直接模型把热量高估 139.5 kcal。 | 同类商品和形似数字都可能误读。用户可对照照片修正每个字段。 |

## 来源、份量与研究边界

- 食阁组从 SingHealth HealthXchange 与 KKH 营养团队的三篇文章中，按可取得原图和克数的条件筛选，每篇以固定的照片 URL 哈希排序选取五张。每行复核原文的份重、热量、蛋白质、碳水和脂肪。照片与参考代表文章刊载的标准份，真实摊位逐盘称重仍需单独验证。[中式菜与点心](https://www.healthxchange.sg/food-nutrition/food-tips/best-worst-singapore-hawker-chinese-food-dim-sum-char-kway-teow) · [马来菜](https://www.healthxchange.sg/food-nutrition/food-tips/best-worst-singapore-hawker-malay-breakfast-foods-nasi-lemak-mee-siam-soto) · [印度菜](https://www.healthxchange.sg/food-nutrition/food-tips/best-worst-singapore-hawker-indian-breads-prata-mutton-murtabak)
- 包装组使用 Open Food Facts 上另外 15 个商品的营养标签照片。参考值由人工读取包装印刷的同列数值，按事先指定的半份、一份或一份半换算。包含克、毫升、仅列 kJ 的能量、零值与冲调食品。若同一标签分别四舍五入了每份和每百克读数，换列可产生小差异。原图链接、实吃量、参考值与实际送入模型的图像哈希均在清单中。[图片字段和版本说明](https://openfoodfacts.github.io/openfoodfacts-server/api/how-to-download-images/)
- 上一轮的 30 张图用于发现问题。本轮换了 30 张照片，包装组输入改为营养成分表。两轮不可用来宣称同一包装场景的准确率提高了多少。测量范围为已知份量下、人工修正前的自动结果。食阁组自动处理接收用户提供的克数提示，包装组直接模型也收到食用量，App 把食用量交给确定性换算。评测没有测量仅凭照片估重、人工修正后的误差或真实用户留存。[首轮正面包装／餐盘评测](paired_report.md)
- 发现 P07 后加入了确认前的本地检查。当热量和用三大营养素粗估的能量呈现近似 kJ／kcal 的倍数差时，页面请用户核实印刷单位和列，再允许记账。离线重放 15 个原始读数时有 1 个触发。此提示不修改任何营养值，表内分数保留原始结果。

## 用量与复查

每张每组一次，采用同一模型别名 `gpt-5-mini`。60 次调用共 56,332 输入和 8,884 输出 token。按每百万输入 US$0.25、输出 US$2 的标准价估算为 **US$0.03185**。两轮同图评测共 120 次，合计约 **US$0.07244**，约占课程 US$16 额度的 0.45%。实际团队账单、功能演示和其他组员使用量另计。[模型定价](https://developers.openai.com/api/docs/models/gpt-5-mini)

在项目的 Python 3.12 环境执行下列命令。第一步核验每张图的 SHA-256。第二步使用 API，给本轮单独的 ledger 目录。第三步从已保存的调用结果重新计算，不调用模型。

```sh
uv run python -m evaluation.paired_images IMAGE_DIR --release
uv run python -m evaluation.paired_run IMAGE_DIR NEW_RELEASE_LEDGER --release
uv run python -m evaluation.paired_score NEW_RELEASE_LEDGER --release
```

训练与餐单另有离线验证。运行 `uv run python -m evaluation.plan_constraints` 可检查 3,048 个训练日程配置、144 个训练轨迹、480 个餐单约束组合。后者有 209 个可行餐单，271 个应暂缓推荐。这些是模拟用例。[检查代码](plan_constraints.py)
