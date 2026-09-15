# 上线测试报告与风险交接

> 审计日期：2026-09-14
>
> 审计基准：`main` / `960bbac01ab1f719c45a3b0a0ce00e651a6cf280`；当前与 `origin/main` 一致
> 结论：**暂不建议直接上线（Conditional No-Go）**。自动化回归全部通过，但仍有数据完整性、批量修改安全、部署闭环和生产安全阻断项。

本文是本轮唯一测试交接文档。部署地址、GitHub 上传和服务器拉取命令继续以 `04_DEPLOYMENT_RUNBOOK.md` 为准，不再新建分散报告。

> **2026-09-15 更新（`1fc5fa1`）**：P1-01 和 P1-08 的核心问题已修复——
> `bulk_replace` 的空白 `item_name` 不再归一化成 `''` 去匹配全部记录，
> `match`/`replace` 里的日期改为提前用 DRF `DateField` 校验（非法值返回
> 400，不再可能在查询求值时抛出未捕获异常），`date_from > date_to`
> 显式拒绝；`reconcile_purchases_2026` 的新建供应商现在和记录插入在同一个
> `transaction.atomic()` 里。新增 3 个回归测试，`purchasing` 应用测试从
> 29 个增加到 32 个，全部通过。P1-01 里"预览与确认之间没有服务端
> token/version""没有批量操作审计记录""没有最大影响行数限制"这几点
> **仍未处理**——属于要不要做审计日志/操作留痕这类产品决定，不是单纯 bug，
> 留给下一轮按需排期。
>
> **2026-09-15 更新（之后一批提交）**：P1-07 已修复——`draw_lottery` 里
> "先扣分再返还，两条流水都写最终余额"改成扣分后先快照 `balance_after`
> 再应用返还，`DrawLotteryServiceTests` 新增逐行余额断言（不再只断言
> `sum(delta) == balance`）。P1-05 已修复——`accounts/services.py` 新增
> `validate_new_password()`，账号创建（`UserSerializer`）、自助改密
> （`ChangePasswordView`）、管理员重置（`UserViewSet.reset_password`）、
> 平台跨企业创建账号/重置密码（`organizations/views.py` 两处）、
> `provision_organization` 服务函数的 admin 密码全部改为统一走 Django
> `AUTH_PASSWORD_VALIDATORS`（长度从 6 提到 10，另加常见密码库/纯数字/
> 与账号名过于相似校验），不再各处各写一份 `len(password) < 6`；`/api/
> token/` 登录端点新增 IP 维度（30/min）+ 账号维度（8/min）双重限流
> （`accounts/throttling.py`，复用 `promotions` 已有的 DB-cache 限流模式）。
> 顺带修了三处前端"弱密码被服务端拒绝后界面完全没反应"的静默失败
> （`SettingsView.vue` 自助改密/账号创建/管理员重置密码，
> `platform/PlatformFeaturesView.vue` 账号创建/重置密码/新建企业）——这些
> 调用点原本只认识少数几个自定义错误码，服务端新增的校验失败信息不在其中，
> 之前会被无声吞掉。P1-05 建议里的"超级管理员 MFA/限制管理入口来源"未做，
> 属于更大范围的加固，留待后续。P1-02、P1-03、P1-04、P1-06 仍未处理，以下
> 原始审计内容保持不变。

## 1. 本轮范围与工作区状态

已检查项目自有的全部 Python、TypeScript、Vue、JavaScript、HTML、Docker/Nginx/环境模板、迁移、测试和 17 份项目 Markdown；依赖目录、构建产物、虚拟环境和真实导入数据文件不作为项目源码逐行审查对象。

当前代码约 46,111 行（Python/TypeScript/Vue/JavaScript）。审计开始时以下 7 个文件属于用户已有修改；审计期间它们由外部操作提交为 `960bbac` 并同步到 `origin/main`。本轮审计没有执行该 commit/push，也没有回退或改写这些业务文件：

- `store-admin-backend/purchasing/tests.py`
- `store-admin-backend/purchasing/views.py`
- `store-admin-frontend/src/api/purchasing.ts`
- `store-admin-frontend/src/i18n/locales/ja.ts`
- `store-admin-frontend/src/i18n/locales/zh.ts`
- `store-admin-frontend/src/views/PurchasingView.vue`
- `store-admin-backend/purchasing/management/commands/reconcile_purchases_2026.py`

当前唯一未提交修改是本文档。发布前仍应确认 `960bbac` 确实是准备上线的业务版本。

## 2. 已执行测试

| 检查 | 结果 | 说明 |
|---|---:|---|
| Django 全量测试 | **432/432 通过** | MySQL 临时测试库，用时 340.391 秒 |
| `manage.py check` | 通过 | 无普通系统检查错误 |
| `makemigrations --check --dry-run` | 通过 | `No changes detected` |
| Python 模块编译 | 通过 | 全部后端业务包可编译 |
| `pip check` | 通过 | 无损坏的 Python 依赖关系 |
| 前端 `type-check` | 通过 | `vue-tsc --build` |
| Oxlint | 通过 | 只读运行，未使用 `--fix` |
| ESLint | 通过 | `eslint . --no-cache` |
| 前端生产构建 | 通过 | Vite build 成功 |
| 排班保存专项测试 | **1/1 通过** | Node test |
| 浏览器静态冒烟 | 通过（有限范围） | 登录页、顾客登记页、Kiosk 登录保护路由正常渲染，无 console error |
| `npm audit --omit=dev` | 有风险 | 2 个 moderate，来自 `exceljs -> uuid <11.1.1`；无 high/critical |
| `docker compose config` | 结构通过 | 本机缺少根 `.env`，4 个 MySQL 变量被渲染为空，不能据此启动新数据库 |
| Docker 镜像构建 | **未完成** | 本机 Docker daemon 未运行，并非构建代码已验证失败 |
| 当前开发环境 `check --deploy` | 6 个警告 | DEBUG、密钥、HTTPS、Cookie、HSTS 均为开发值 |
| 模拟生产安全变量 `check --deploy` | 2 个提示 | 仅剩 HSTS includeSubDomains/preload；启用前需确认所有子域均永久 HTTPS |

测试过程另有两个重要警告：

- MySQL 忽略 `inventory.Product` 的条件唯一约束（Django `models.W036`）。
- 当前开发 `SECRET_KEY` 太短，PyJWT 报 `InsecureKeyLengthWarning`；生产密钥不能沿用模板值。

浏览器测试没有对真实业务库执行登录、创建、修改、删除、抽奖或核销，以免污染现有经营数据。完整端到端操作必须在隔离的 staging 数据库完成。

## 3. 现有本地数据只读一致性结果

本轮只输出异常数量，没有输出客户手机号、姓名、Token、供应商账户或明细。

通过项：

- 跨 Organization 的进货/供应商、库存/商品、账号/分店、顾客/消费确认关系异常均为 0。
- 重复非空 JAN 组为 0；重复 `(Organization, phone)` 顾客组为 0。
- 商品名标准化异常为 0。
- 库存现存量与库存流水汇总差异为 0；负库存为 0。
- 顾客最终积分余额与积分流水 `delta` 总和差异为 0。
- 活动时间区间、奖品/兑换库存上下限、抽奖/券/打卡活动归属异常均为 0。
- 日报晨间人数、组数、营业额均未超过全日值；未发现负营业额。
- 工资未发现非正时薪或负数月度结果。

需要处理或确认：

1. 进货存在 **13 条负数记录**：9 条负数量、4 条负单价，并因此产生 13 条负金额。它们可能是退货/冲销，但当前模型没有业务类型和原记录引用，无法审计其合法性。
2. 按 `ROUND_HALF_UP` 取整到日元后，仍有 **8 条**进货记录不满足 `amount = quantity × unit_price`，分布在 2026-01/04/05/06，净差额 -53 日元，单条最大差额 11 日元。原因很可能是历史导入先用高精度数量算金额、再把数量存成两位小数；编辑这些行时 `save()` 会重算并静默改变金额。
3. 积分最终余额正确，但顾客 ID 22 的两次“积分抽奖后返还积分”各有一条扣分流水把 `balance_after` 写成返还后的最终值。异常流水 ID 为 48、53。逐笔流水的 running-balance 语义不成立，虽然最终余额没有错。
4. 5 张已核销券没有 `redeemed_by`。代码确认这是顾客端低价值券自助核销的设计，不是脏数据；报表和后台必须明确显示“顾客自助确认”，不能显示成未知或审计缺失。

## 4. P1：上线前必须完成

### P1-01 采购批量替换可能扩大到整店数据

位置：`store-admin-backend/purchasing/views.py:127-188`。

- `item_name` 只检查原始字符串 truthy；仅空白字符串经 `normalize_item_name()` 后变成空字符串，而 `icontains=''` 会匹配当前账号范围内的全部记录。
- `date`、`date_from`、`date_to` 和替换日期没有先经过 DRF `DateField`；非法值不能保证稳定返回 400。
- `date_from > date_to` 未拒绝；预览与确认之间没有服务端 token/version，确认时数据范围可以变化。
- `queryset.update()` 绕过逐行 `save()`，且没有批量操作审计记录、操作者、条件快照、受影响 ID 或回滚依据。
- 当前测试覆盖空字典、预览不写、组合条件、替换供应商和分店隔离，但缺少归一化后空字符串、非法日期、反向日期范围、跨 Organization 供应商、预览漂移和并发测试。

上线要求：增加专用 serializer；归一化后再次判空；日期强类型校验；确认使用服务端 preview token/hash 或记录版本；事务内落不可变审计记录；设置最大影响行数或要求二次输入匹配数量；补齐上述测试。

### P1-02 进货负数与金额口径没有业务模型

位置：`purchasing/models.py:42-69`、`purchasing/serializers.py:30-107`、历史导入命令。

当前 API 对数量、单价没有非负限制，负数既可能是合法退货，也可能是误录；系统无法区分。历史导入还存在 8 条“展示数量”和金额计算精度不一致。

上线要求：由店主确定以下二选一口径并固化到模型、API、报表和测试：

- 普通进货数量/单价必须大于等于 0；退货使用 `record_type=return`、正数金额、原进货引用和原因；或
- 明确允许负数冲销，但必须增加类型、原因、操作者和原记录引用，并在月度统计/应付账款中明确净额口径。

随后用原始订单表核对 13 条负数和 8 条精度差异；在确认前不得批量改写真实数据。

### P1-03 JAN 唯一性在 MySQL 只靠应用层，存在并发重复

位置：`inventory/models.py:20-38`、`inventory/serializers.py:14-29`。

MySQL 不创建带 `condition=` 的唯一约束。Serializer 的 `exists()` 可拦截普通重复提交，但两个并发请求仍可能同时通过。

上线要求：把空 JAN 统一为 `NULL`，使用无条件数据库唯一约束 `(organization, jan_code)`；MySQL 允许多行 `NULL`，同时能约束所有非空 JAN。迁移前先扫描/清理重复值，并增加 MySQL 并发测试。

### P1-04 部署流程不是单一、安全、可回滚的发布链

位置：根目录 `deploy.sh`、`docker-compose.yml`、`04_DEPLOYMENT_RUNBOOK.md`。

- `deploy.sh:20-22` 使用 `git reset --hard`，与已确认的 `git pull --ff-only origin main` 要求冲突，可能直接丢弃服务器现场修改。
- 用户常用的 `docker compose up -d --build` 不执行 migration；若版本含迁移，新代码可能先连接旧结构。
- 脚本没有迁移前备份、恢复演练、版本化回滚步骤或失败自动停止/回滚策略。
- 所谓 smoke check 不校验状态码，且注释把 404 当“路由正常”，即使后端不可用也可能继续显示 done。
- backend/frontend 没有 Compose healthcheck/readiness，只有 MySQL 有 healthcheck。

上线要求：弃用 `reset --hard`；合并为一个经过验证的发布脚本：检查干净工作树 → `pull --ff-only` → 备份并验证备份 → build → migration → 启动 → health/readiness → 核心 API smoke → 失败回滚。部署命令和服务器路径仍以 `04_DEPLOYMENT_RUNBOOK.md` 为准。

### P1-05 密码与登录防护不足

位置：`accounts/serializers.py:70`、`accounts/views.py:132-169`、`organizations/views.py:214-249,289-303`、JWT 登录端点。

账号创建、管理员重置、自助改密和平台重置只要求 6 位，且直接 `set_password()`，没有统一调用 Django `validate_password()`；JWT 登录端点没有专用限流/失败锁定。公网管理系统不应仅依靠 6 位口令。

上线要求：所有密码入口统一调用 Django validators，建议最少 10–12 位；增加登录 IP+账号双维度限流、失败告警和审计；超级管理员启用更严格策略，最好加 MFA 或限制管理入口来源。

### P1-06 生产代理、端口和安全环境必须现场验证

位置：`docker-compose.yml:44-49`、`config/settings.py:190-194`、`store-admin-frontend/nginx.conf:45-71`。

- `8082:80` 默认监听所有主机接口，可能绕过宝塔 HTTPS 反代直接访问 HTTP。只作为反代上游时应绑定 `127.0.0.1:8082:80`，并用防火墙复核。
- 实际链路若为“客户端 → 宝塔 Nginx → frontend Nginx → Django”，`PROMOTIONS_TRUSTED_PROXY_COUNT=1` 可能记录到代理地址而非客户端地址，从而削弱限流和风控；应按生产 `X-Forwarded-For` 实测确定值。
- 本地 `.env` 是开发模板状态，不能代表服务器已配置 `DEBUG=False`、强密钥、HTTPS Cookie、HSTS、可信 Origin/Host。

上线要求：在生产服务器执行安全检查并记录脱敏结果；验证 HTTP 强制跳 HTTPS、直连 8082 不可公网访问、真实客户端 IP 正确、Cookie 带 Secure/HttpOnly/SameSite、错误页不泄漏 DEBUG。

### P1-07 积分流水逐笔余额语义错误

位置：`promotions/services.py:827-852`。

积分抽奖抽中“积分返还”时，扣分流水和返还流水都写入同一个最终 `points_balance`。总和和最终余额正确，但第一条流水的 `balance_after` 不等于执行该条后的余额，违反模型“不变流水/运行余额”说明。

上线要求：先写扣分后的余额，再写返还后的余额，或合并成一条净变化流水并明确原因；增加逐行累计余额断言，而不只断言 `sum(delta) == customer.points_balance`。修复历史流水前先做只读预览和备份。

### P1-08 reconciliation 命令的事务边界不完整

位置：`purchasing/management/commands/reconcile_purchases_2026.py:78-97,154-166`。

新供应商在主事务开始前创建；后续插入失败时会留下半完成供应商。命令还硬编码分店和保护日期，缺少执行批次审计、确认参数、源文件 hash 和自动备份要求。

上线要求：把供应商创建和记录插入放入同一个 `transaction.atomic()`；默认 dry-run，真实写入要求显式 `--apply`、分店参数、预期插入数确认、源文件 hash、执行日志和前置备份；补幂等、失败回滚、错误分店和保护日期测试。

## 5. P2：上线后短期完成或上线前一并收口

1. 前端 Dockerfile 使用 `node:20-slim`，但 `package.json` 明确要求 `^22.18.0 || >=24.12.0`。应统一到 Node 22 LTS 或符合声明的固定版本，避免本机通过、容器失败。
2. 生产 bundle 有大文件警告：主包约 1.37 MB（gzip 448 KB），Excel 导出包约 931 KB，供应商页约 410 KB。继续按路由/导出能力懒加载，并做移动网络首屏指标。
3. `npm audit` 有 2 个 moderate `uuid` 漏洞，经 `exceljs` 引入。`npm audit fix --force` 会降级到破坏性版本，不能直接执行；应评估升级/替换 Excel 导出库并做导出回归。
4. Python 漏洞数据库审计未执行：当前环境未安装 `pip-audit`。CI 应固定运行 `pip-audit -r requirements.txt` 或等价工具。
5. 前端只有 1 个 Node 专项测试，没有 Vitest 组件测试或 Playwright/Cypress 核心流程。类型检查和 build 不能证明按钮、表单、权限和错误恢复可用。
6. 没有可确认的生产错误监控、集中日志、备份任务成功告警、磁盘/数据库容量告警和定时任务告警。
7. `01_CURRENT_STATE.md`、根目录旧报告和开发进度中的 HEAD、测试数量、阶段状态已过期；旧方案仍写“无 throttle/阶段未完成”，与当前实现冲突。历史文档应标记 archived，不再作为 AI 当前事实来源。
8. HSTS `includeSubDomains`/preload 不是机械开启项；只有确认全部子域永久 HTTPS 后再启用。

## 6. 模块上线评价

| 模块 | 自动化/数据结果 | 上线判断 |
|---|---|---|
| 登录、账号、租户、功能开关 | 回归通过、跨租户数据检查通过 | 完成 P1-05/P1-06 后可上线 |
| 日报、支付、看板、月度分析 | 回归通过、现有数据关系正常 | staging 浏览器 E2E 后可上线 |
| 进货、供应商 | 回归通过，但存在批量替换风险、负数口径和 8 条金额差异 | **当前阻断** |
| 商品、库存 | 流水与库存一致，现有 JAN 无重复 | 数据库 JAN 唯一约束修复后可上线 |
| 员工、排班、工资 | 回归通过，现有工资数据检查正常 | staging E2E、打印/移动端人工验收后可上线 |
| Promotions 积分/抽奖/券/打卡 | 事务、幂等、库存和租户测试较完整 | 修复流水语义，确认代理限流与自助核销文案后可上线 |
| 历史 Lottery | 回归通过 | 上线前继续确认 staff 是否应看到完整联系方式 |
| 平台运营控制台 | 权限回归通过 | 强密码、登录保护和超级管理员运维策略完成后可上线 |
| Docker/部署 | 配置可解析，镜像未在本机实际构建 | **当前阻断** |

## 7. 必须新增的发布门禁

全部满足后，状态才能从 Conditional No-Go 改为 Go：

- [ ] P1-01 至 P1-08 已修复并新增回归测试。
- [ ] 13 条负数进货和 8 条金额差异已由业务负责人逐条确认，保留确认记录。
- [ ] CI 使用 MySQL 8 跑 432+ 全量测试，并运行前端 type-check/lint/build/组件测试/E2E。
- [ ] Docker backend/frontend 镜像在干净环境成功构建；从空库完成 migrate 和最小种子验证。
- [ ] staging 完成五条端到端：登录与权限、日报保存与历史、进货录入/筛选/安全批改、排班到工资、顾客登记到打卡/积分/抽奖/核销。
- [ ] 备份可恢复到新数据库，并记录恢复用时和校验结果。
- [ ] 生产 `check --deploy`、HTTPS、直连端口、Host/Origin、真实 IP、限流、Cookie、错误页全部验收。
- [ ] 发布后 smoke check 对关键端点设置明确期望状态码，失败时命令返回非 0。
- [ ] 确认 `960bbac` 是预期发布版本，服务器使用 `git pull --ff-only origin main`，不得强制 reset。

## 8. 建议开发顺序（可直接交给后续 AI）

### 批次 A：先保护经营数据

阅读 `purchasing/models.py`、`serializers.py`、`views.py`、`tests.py` 和 reconciliation/import 命令。修复 P1-01、P1-02、P1-08；不要直接修改真实进货数据。先生成差异预览、补测试并跑后端全量测试。

### 批次 B：修数据库与账本不变量

阅读 inventory 和 promotions 的模型、迁移、services、tests。完成 JAN 的 NULL+数据库唯一迁移；修复积分返还逐笔 `balance_after`；编写迁移前数据扫描和 MySQL 并发测试。任何历史数据修复都先备份、dry-run、输出数量，再等待确认。

### 批次 C：发布与安全闭环

统一 `deploy.sh` 与 `04_DEPLOYMENT_RUNBOOK.md`，保持服务器目录 `/www/wwwroot/shop`、远端 `origin`、分支 `main` 和 `git pull --ff-only origin main`。增加备份/恢复、migration 顺序、health/readiness、状态码断言、回滚；统一 Node 版本；强化密码和登录限流；验证代理链与 8082 绑定。

### 批次 D：staging E2E 与经营验收

建立无真实个人信息的 staging fixture，用 Playwright 覆盖五条核心流程和 admin/branch/staff/guest/platform 权限矩阵；同时人工验收日文/中文、手机/平板/桌面、打印、扫码枪、相机权限、弱网重试和重复点击。完成后重新更新本文档的测试数量、commit 和 Go/No-Go 结论。

## 9. 本轮没有执行的操作

- 没有修改业务代码或真实业务数据。
- 本轮审计没有提交、push、pull 或部署；审计期间仓库由外部操作前进到 `960bbac`。
- 没有执行 reconciliation/import/seed/清理命令。
- 没有登录生产服务器，因此不能声明生产 `.env`、容器、迁移、备份和域名已合格。
- 没有完成 Docker build，因为本机 Docker daemon 未运行。
