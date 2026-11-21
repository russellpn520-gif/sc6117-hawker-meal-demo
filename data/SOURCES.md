# 食物成分表与份量来源

公开版离线加载 19,115 条带来源的营养记录。计数按来源条目统计，同名食品可能对应不同配方、烹调方式或市场。每条均有参考重量、能量、蛋白质、碳水和脂肪。查询时可用中英文常用名、来源原名，以及部分法文名。

| 来源与下载文件 | 条目 | 取值与单位 |
| --- | ---: | --- |
| 美国农业部 FoodData Central，Survey/FNDDS，2024-10-31 发布包。[官方 CSV](https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_survey_food_csv_2024-10-31.zip) | 5,431 | 每 100 g 的营养素编号 208、203、205、204。提供份量的食物保留首个具名量具或单件重量；FDC ID 可回查原条目。 |
| 美国农业部 FoodData Central，SR Legacy。[官方 CSV](https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_sr_legacy_food_csv_2018-04.zip) | 7,793 | 每 100 g 的营养素 ID 1008、1003、1005、1004，保留 FDC ID。含生熟食材、加工食品和部分品牌产品。 |
| 英国 Public Health England，McCance and Widdowson’s CoFID 2021。[发布页与工作簿](https://www.gov.uk/government/publications/composition-of-foods-integrated-dataset-cofid) | 2,636 | Proximates 工作表，每 100 g；保留 Food Code。含欧洲、南亚、中东等饮食中的食物。 |
| 台湾食品药物管理署，食品营养成分资料集，2026-11-21 下载。[开放资料与授权](https://data.gov.tw/dataset/8543) · [官方 CSV 压缩档](https://data.fda.gov.tw/data/opendata/export/20/csv) | 2,160 | 以整合编号合并热量、粗蛋白、总碳水化合物和粗脂肪，采用每 100 g 数值。保留来源提供的名称、俗名和英文名，增加简体字检索。 |
| FAO/INFOODS，Food Composition Table for Western Africa (2019)，© FAO 2020。[来源](https://www.fao.org/infoods/infoods/tables-and-databases/faoinfoods-databases/en) · [工作簿](https://www.fao.org/fileadmin/user_upload/faoweb/2020/WAFCT_2019.xlsx) | 1,027 | 表 03，每 100 g 可食部。保留英法名称及食物代码。采用来源的可利用碳水；方括号内的来源估值按数值读取。 |
| Energy Content and Nutrient Profiles of Frequently Consumed Meals in Singapore，Foods 2021，表 1–3。[论文和原表](https://doi.org/10.3390/foods10071659) | 45 | 实测中式、马来和印度餐食。以 4.184 kJ/kcal 转换表中能量均值，保留宏量营养素均值和样本份重。 |
| 新加坡 HPB–MOH，2016 年临床指南附表 A。[第 101–102 页](https://isomer-user-content.by.gov.sg/484/d2884b81-4dfc-4a9e-b153-1487969794d5/obesity-cpg_main_for-online-30-aug.pdf#page=108) | 9 | 沿用项目原始标识符及原表每标准份的数值。 |
| Guzman y Gomez 澳大利亚，2026-10-29 营养指南。[品牌资料](https://www.guzmanygomez.com.au/nutrition/) · [菜单表，第 17、31 页](https://www.guzmanygomez.com.au/wp-content/uploads/2026/11/261029_NUTRITION_ALLERGEN_GUIDE_420X297MM.pdf#page=17) | 14 | 常规碗及迷你碗各 7 款 mild 配方，均按厂家标示的每份克数。其他市场或配方不明时可选 USDA 通用碗，亦可按配料记录。 |

各来源的碳水定义略有差异，跨表比较时应保留该来源的口径。数值为 0 的记录可以入库，缺少四项中任意一项或仅标作微量的记录跳过。没有具名份量的项目以 100 g 作为可编辑的计算起点。秤重、实际包装和当地菜单能提供更具体的份量。

USDA 食物成分数据为公共领域。CoFID 含按 Open Government Licence v3.0 提供的公共部门信息。台湾食药署资料适用政府资料开放授权条款第 1 版。西非资料在本非商业课程项目中使用，其版权及其他用途条件见原工作簿首页。各来源保留相应权利。[USDA 数据许可](https://fdc.nal.usda.gov/) · [英国 OGL](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/) · [台湾资料授权](https://data.gov.tw/license) · [FAO 原工作簿](https://www.fao.org/fileadmin/user_upload/faoweb/2020/WAFCT_2019.xlsx)

## 重建

将上述下载分别命名为 `fndds.zip`、`sr.zip`、`uk.xlsx`、`tw.csv`（保留 ZIP 文件内容）、`wa.xlsx`、`hawker.xml` 和 `261029.pdf`。论文 XML 来自 [Europe PMC](https://www.ebi.ac.uk/europepmc/webservices/rest/PMC8304763/fullTextXML)。原 HPB 行独立保存在 [foods.csv](../foods.csv)。导入工具使用 openpyxl、opencc-python-reimplemented 和 PyMuPDF，应用运行只需已有的项目依赖。

```sh
python tools/build_catalog.py /path/to/downloads data/catalog.csv
```

[catalog.csv](catalog.csv) 保留原名、来源代码、营养基准和份量。[aliases.csv](aliases.csv) 将常用中文译名、英文简称连接到已有条目。
