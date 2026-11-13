# 言屿 · 语料分布校对室

冻结参考分箱，把候选语料的变化读到具体切片，再形成有依据的补采说明。

言屿字幕语料组有20位数据研究与采集人员。现有流程把训练与新增采集的元特征粘到表格，分别重画直方图、逐项看p值，再凭总体均值讨论补采；三个痛点是候选重分箱使两边无法比较、多重检验产生误报、分布变化被直接写成模型质量下降。这里承接“匿名片段元特征→冻结参考箱/差异与FDR核对→补采计划→负责人审稿→CSV交付”。不处理字幕正文，也不直接评估下游模型质量。

## 快速启动

```sh
cp .env.example .env
docker compose config --quiet
docker compose up -d --build --wait
docker compose exec -T backend python -m scripts.seed_demo
```

访问 [校对室](http://localhost:18215)，[后端文档](http://localhost:19215/docs)，MySQL映射17715。首次API启动自动seed；失败记录日志而不阻塞API，可单独运行脚本。初始2个快照各900片段，共1800；另有1个12行的待校验批次（第5行类型错误、第12行编号重复，各隔离1条）；5个特征、1份Python真算比较、5个持久化发现、1份补采草案。固定种子113，参考与候选分别为 `yy-corpus-202611-reference.csv` 和 `yy-corpus-202611-candidate.csv`。

| 账号 | 密码 | 权限 |
|---|---|---|
| admin@yanyu.demo | Yanyu2026! | admin语料负责人：阅读、导入、比较、建立计划、审核；仅获批计划可导出 |
| analyst@yanyu.demo | Yanyu2026! | analyst分布研究员：阅读、导入、比较、建立计划；审核返回403；仅获批计划可导出 |
| viewer@yanyu.demo | Yanyu2026! | viewer采集观察员：只读、获批CSV下载；写入均403 |

## 一天的校对剧本

1. 09:00 梁栩以analyst登录，检查参考/候选各900条元特征。
2. 导入新采集片段时先建立“待校验批次”：一行一个JSON对象，逐行保存原文、编号、解析/取值错误和处置状态（合格或隔离）。坏行只隔离自己，不再整批退回；坏行与好行的数量可对账（合格+隔离=总行数）。
3. 修正隔离行时提交该行新原文，服务只重新解析这一行并检查同编号冲突；其他行原文不会重新解析。若该行改号，仅旧编号组的派生冲突标记会重算（可解除因它产生的隔离）；不会把未编辑的合格行新改判为隔离。每次修正保留前次原文、错误与状态。同编号会明确拦截：内容不一致记为“编号冲突”，内容完全相同也记为“编号重复”，两者都隔离且都不能发布。
4. 在语料快照中读前100条样本，看到duration/noise/token_rate和language/device；null明确显示为缺失。
5. 建立“十一月采集分布复校”，选择五特征，参考分位箱6、每桶平滑伪计数0.5、FDR α=.05。
6. 先做全量比较，再可按语言zh/设备mobile过滤两边；任一切片不足5条会明确failed，不静默当无漂移。
7. worker只用参考非缺失值拟合分位边界与参考类别字典，再将候选投影到冻结箱。
8. 看PSI/JS效应量、连续KS原p/BH q及FDR拒绝；打开language看到__NEW__和__MISSING__独立计数。
9. 从当前发现建立“来源结构补采说明”，填写切片、目标200片段和采集理由。
10. 叶砚以admin审稿，说明先核对来源再补采，后续质量变化须独立评测。
11. 唐禾以viewer导出获批CSV，保留发现指标、校正q与审稿说明；不将漂移直接表述为质量劣化。
12. 批次隔离清零后由研究员发布：一次事务生成完整快照，重试或并发发布只保留一份；发布后行原文和快照内容冻结。待校验批次在发布前不进入比较，发布结果在快照页可查。

## 待校验批次与发布口径

导入有两种入口：`POST /import-batches` 建立待校验批次（`content` 按行或 `lines` 数组），`POST /snapshots` 保留原有JSON数组整批导入。批次表保存 `total/valid/quarantined` 三个计数，服务保证 `total=valid+quarantined`；存在隔离行时 `POST /import-batches/{id}/publish` 返回409并说明数量，不生成任何快照。

逐行校验复用原有五特征规则：reference必填且1–80字符；features必须恰好五项；数值须有限或null（布尔不算数字）；类别须1–40字符非空字符串且不得为`__NEW__`/`__MISSING__`；额外字段、缺字段、非法JSON均为隔离原因。原文按行原样保存（最多20000字符/行，整批原文最多5,000,000字符；MySQL使用MEDIUMTEXT），空行也单独成行并隔离。编号冲突按解析成功的行分组判定：同编号行号最小者保留，其余隔离；修正导致编号变化时会重算旧编号组的派生冲突标记，但不会重新解析其他行原文。修正后的行若与同编号既有行冲突，隔离的是被修正行，既有的合格行不被静默改判。

发布使用数据库行锁串行化：`import_batches`行加`FOR UPDATE`，`corpus_snapshots.import_batch_id`唯一约束作为最终保险。重复发布直接返回首次结果（`created:false`与同一`snapshot_id`）；并发发布的一方提交后另一方回退并返回该结果，不会出现两份快照或半份快照。发布要求隔离数为0、合格行非空、编号唯一；快照名沿用批次名，与既有快照或批次重名会被409拦截。发布后`PATCH /import-batches/{id}/rows/{row_id}`返回409，内容和修正记录均只读可见。修正历史在`import_row_revisions`中保存前次/本次原文、错误、状态和操作者。

## 数据、分箱与统计口径

五个核心实体CorpusSnapshot、Utterance、ComparisonRun、DriftFinding、ResamplingPlan，均贯穿表/model/schema/service/route/API/store/UI。待校验批次另设ImportBatch、ImportBatchRow、ImportRowRevision。六页为校对首页、语料快照、比较配置、漂移发现、补采审稿、校对留痕；语料快照页同时展示待校验批次、逐行校验/修正/发布与已发布快照。HistogramBins、FindingSummary、RunTable跨页复用，同时共享Table/Badge/Notice/Empty。

数值特征：duration（秒）、noise（dB）、token_rate（token/s）；类别：language、device。API导入20–5000条JSON数组，每项reference唯一、五特征完整，值可null；数值必须有限，类别必须非空字符串，保留名__NEW__/__MISSING__禁止作为真实类别。没有CSV解析器或真实采集接口。

`services/binning.py`：只对参考快照在当前切片的非缺失连续值拟合等频分位内边界，`np.quantile`内点去重，尾箱延伸±∞。重复边界会减少实际箱数。`searchsorted(side='right')`使区间左闭右开，正好等于边界进入右箱；候选极值只进入尾箱，绝不改变边界。null单列__MISSING__。参考数值少于2有效值或常量明确失败，不伪造分箱。参考类别字典冻结为排序后的非缺失类别，候选未见类别合入__NEW__，null另入__MISSING__；参考全缺失类别失败。候选常量数值允许比较，候选连续有效值不足2则无法KS而失败。

`services/distributions.py`：设每桶计数a_i/b_i、总量N/M、桶数K，伪计数α>0：p_i=(a_i+α)/(N+Kα)，q_i=(b_i+α)/(M+Kα)。每桶都平滑，包含新类别与缺失空桶。PSI=Σ(q_i−p_i)ln(q_i/p_i)，使用自然对数；JS=.5Σp_i log₂(p_i/m_i)+.5Σq_i log₂(q_i/m_i)，m=(p+q)/2，单位bit，JS在0至1。固定同一箱字典时交换p/q对称；交换整条管线的参考/候选会重建分箱，不能假定得到相同数值。缺失桶参与散度，缺失比例另报。

`services/comparison.py`：所选连续特征的非缺失值执行双侧两样本KS（SciPy ks_2samp，method=auto），统计量是两ECDF最大绝对差。类别不执行KS，p/q为null。`services/multiple_testing.py`对本运行全部所选连续特征组成的一个检验族做Benjamini–Hochberg：排序p_(i)，q_(i)=min_{j≥i}(m p_(j)/j,1)，再映回原顺序；q≤配置FDR α才标记拒绝。默认五特征中m=3，而不是把类别也算入m。BH的FDR解释有独立或适当正相关依赖等条件；这里没有证明真实语料任意依赖条件下的FDR控制。

“建议核对”取 q≤FDRα 或 PSI≥.2 或 JS≥.05，后两者是明确的效应量启发阈值，不是p值或显著性。页面分别显示FDR拒绝和建议核对，未拒绝也不声称分布相同。分布漂移不能证明下游模型变差，补采应先调查采样口径与来源，并独立评估质量。

计算失败态包括空快照、空/不足5条的切片、参考连续常量/全缺失、连续有效值不足、非有限值、未知/重复特征及非法平滑/FDR/分箱参数。结果存完整冻结箱、两边计数/平滑比例、原p/q/检验族、参考/候选切片ID和输入SHA-256。指纹覆盖两边全量id/reference/全部五特征（包含null及未选特征）、配置和算法版本，按reference稳定排序；顺序改变不改指纹，任一影响字段变化会改指纹。

## 工程与开发

| 层 | 实现 |
|---|---|
| 前端 | Vue3.5.45 / TypeScript5.7 / vue-tsc3.3 / Vite6.4.6 / Nginx1.27 |
| 后端 | Python3.11 / FastAPI / SQLAlchemy2 / Pydantic |
| 算法 | NumPy2.2.1、SciPy1.15 |
| 数据/任务 | MySQL8 / Redis7 / Celery5.4 + Kombu5.4.2 |
| 认证 | PBKDF2-SHA256 210000轮、JWT HS256 8小时、服务器角色校验 |

五服务恰为frontend/backend/worker/db/redis，全部有健康探针/健康依赖；Nginx探针127.0.0.1，worker定向Celery ping。db-data、redis-data、artifacts分别持久化库、队列、共享计算JSON。Nginx剥离/api/前缀，API原生路由无重复前缀。Kombu锁定5.4.2，避免Celery5.4 Redis extra与新Kombu redis-py范围冲突。

环境变量见.env.example：COMPOSE_PROJECT_NAME隔离短名；FRONTEND_PORT/BACKEND_PORT/DB_PORT映射；MYSQL_DATABASE/USER/PASSWORD及ROOT_PASSWORD配置库；JWT_SECRET签名；SEED_DEMO控制自动种子。演示值用于本机，部署通过环境变量替换。

```sh
# 本机设置可达 DATABASE_URL / REDIS_URL / JWT_SECRET
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn src.main:app --reload --port 19215
# 另一个终端，同环境变量
celery -A src.worker.app worker --concurrency=1
# 前端Vite开发代理已指向127.0.0.1:19215
cd frontend
npm ci
npm run dev
```

结构：backend/src/{routes,controllers,services,models,schemas,middlewares,utils,constants,config}；backend/scripts/seed_demo.py；backend/migrations/；frontend/src/{api,stores,types,components/common,hooks,pages,router,utils,constants}。metadata首次建表，migrations说明结构，生产增量升级需另行规划。快照名/片段自然键/基准运行名让seed可重复且不覆盖用户修改；基准仅缺失时计算。请求ID和全局错误两个中间件；AuditLog记录登录、导入、任务和审稿；CSV公式前缀转义。

共享枚举位置：后端backend/src/constants/enums.py的Role/RunStatus/PlanStatus/FindingStatus/BatchStatus/BatchRowStatus；前端frontend/src/constants/enums.ts对应角色/运行/计划/发现/批次/行标签；使用于鉴权、运行/计划/批次服务、schema和Badge/Layout/各页面。测试脚本、真实截图、CSV、日志、报告仅位于批次根test-artifacts/gb-0011，源码不含截图/测试报告。真机测试、oracle和已知差异见该目录TESTING.md。

## 范围与License

合成匿名片段仅展示分布研究，不含真实字幕、说话人或设备身份；没有下游模型质量评测、生产负载验证或自动补采执行。页面样本前100条、完整切片用于计算；获批计划CSV供人工采集安排。Google字体联网加载，离线使用浏览器回退。收尾 `docker compose down -v --remove-orphans` 清理本栈演示卷。

MIT，见LICENSE。
