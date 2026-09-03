# 抽奖系统重新检查与测试报告（AI 修复提示词版）

> 检查日期：2026-09-03  
> 检查范围：`/Users/tatsuya/Documents/Projects/shop` 当前工作区全部代码、配置、迁移、测试、前端页面和 Markdown 文档。  
> 本轮原则：只读检查、测试和报告；没有修改任何代码，也没有执行代码自动修复。

## 1. 结论摘要

当前项目后端可以通过全量测试，抽奖/积分/券专项也全部通过；前端可以完成类型检查、oxlint 和生产构建。抽奖核心事务、余额扣减、奖品权重快照、库存扣减、券核销、跨租户隔离和幂等抽奖已有较完整实现。

但当前不建议直接上线。主要上线阻断项是：

1. 活动的 `starts_at` / `ends_at` 只保存，不参与登记、消费确认、积分兑换和抽奖的有效性判断。
2. 后台新建奖品时，`total_stock` 不会自动写入 `remaining_stock`；限量奖品可能被当成无限库存。
3. 客人使用“手机号 + 生日”或“手机号 + PIN”恢复时没有 Organization 上下文；同一手机号存在于多个租户时，可能返回错误租户的客户卡。
4. 直抽次数只保存在客户聚合字段 `draw_chances`，作废某一笔消费时无法准确区分该笔次数和其他消费产生的次数，存在错误扣回后续次数的风险。
5. 消费确认没有请求幂等键。当前业务测试明确允许同一营业日的第二笔确认继续发积分，但网络重试或店员重复点击会被当成新消费；这需要业务确认并补充防重策略。
6. 前端 ESLint 仍有 2 个错误；生产构建虽成功，但有约 1.37 MB 和 0.93 MB 的大 chunk 警告。

## 2. 项目整体与模块边界

这是一个 Django + DRF 后端、Vue 3 + TypeScript 前端、MySQL 8 数据库的餐饮连锁店铺管理系统，使用 Organization 做租户根边界，主要角色为 `admin`、`branch`、`staff`。

当前代码包含两套“抽奖”相关功能，必须区分：

| 模块 | 作用 | 入口 |
|---|---|---|
| `lottery` | 历史抽奖名单、人员、批次和记录录入/查询 | `/api/lottery/*`、前端 `/lottery` |
| `promotions` | 当前积分卡、打卡、消费确认、积分抽奖、奖品库存、券核销、风控 | `/api/guest/*`、`/api/promotions/*`、前端 `/pc/*`、`/kiosk/*`、`/promotions` |

其他主要模块包括日报、进货、供应商、商品/库存、排班、工资、员工、看板和支付方式。本轮只检查了当前工作区，没有发现或读取另一个独立项目。

当前 Markdown 文档中，`promotions-开发任务书.md` 和 `打卡与抽奖实施方案.md` 仍有“阶段 1/2/2.5/3”的历史分层；源码已经包含一部分阶段 2、2.5、3 功能，`开发进度.md` 也没有覆盖最近的抽奖实现，文档状态需要后续同步。

## 3. 本轮执行的测试

| 检查项 | 结果 | 说明 |
|---|---|---|
| `venv/bin/python manage.py check` | 通过 | 无普通 Django system check 问题 |
| `venv/bin/python manage.py test promotions --verbosity 1` | 通过 | 96/96，66.090 秒 |
| `venv/bin/python manage.py test --verbosity 1` | 通过 | 355/355，262.772 秒 |
| `venv/bin/python manage.py makemigrations --check --dry-run` | 通过 | `No changes detected`；沙箱首次检查数据库历史时有本地连接权限提示，实际测试数据库可正常创建 |
| `venv/bin/python -m pip check` | 通过 | 无依赖冲突 |
| `npm run type-check` | 通过 | Vue/TypeScript 类型检查通过 |
| `npx oxlint .` | 通过 | 无输出、退出码 0 |
| `npx eslint . --no-cache` | 失败 | 2 个 `no-unused-vars` 错误，见第 9 节 |
| `npm run build-only` | 通过 | Vite 生产构建通过，但有大 chunk 警告 |
| `npm run test:schedule-save` | 通过 | 1/1 |
| `manage.py check --deploy` | 有预期提醒 | 6 项开发配置安全提醒，见第 10 节 |
| 前端 HTTP 健康检查 | 通过 | `GET /pc/register` 返回 200 |
| 后端无 guest token 访问 | 符合预期 | `GET /api/guest/card/` 返回 404 `card-not-found` |

测试期间出现的非失败警告：

- MySQL 不支持 `inventory.Product` 的条件唯一约束，Django 报 `models.W036`；该约束不会创建到 MySQL，需要继续依靠应用层校验或改为数据库兼容约束。
- 本地 JWT 使用的 SECRET_KEY 长度不足，PyJWT 报 `InsecureKeyLengthWarning`；生产必须换成随机长密钥。

## 4. 客户角色测试

### 4.1 浏览器页面实测

使用当前本地前端进行只读页面检查：

| 场景 | 结果 |
|---|---|
| 无活动 token 打开 `/pc/register` | 显示“二维码无效或活动结束” |
| 使用当前 active demo campaign token 打开 `/pc/register?t=...` | 正常显示手机号、姓名、生日、PIN、隐私同意和发卡按钮；未勾同意时按钮禁用 |
| 打开 `/pc/login` | 正常显示 PIN 恢复和生日只读两种模式 |
| 未登录打开 `/kiosk/verify` | 跳转 `/login?redirect=/kiosk/verify` |
| 未登录打开 `/kiosk/redeem` | 跳转 `/login?redirect=/kiosk/redeem` |
| 未登录打开 `/promotions` | 跳转登录页 |
| 未登录打开 `/lottery` | 跳转登录页 |

本轮没有在实际业务数据库提交手机号、PIN、积分消费或券核销。原因是这些动作会产生持久化客户/积分/抽奖/核销数据，并且涉及个人标识和登录凭据；写入链路已在 Django 临时测试数据库中由 API 测试覆盖。

### 4.2 客户 API/服务流程覆盖

当前 96 个 promotions 测试覆盖了以下客户流程：

- 首次登记：有效活动 token、手机号归一化、隐私同意；未同意或 token 无效时拒绝。
- 已有手机号再次登记：不返回旧卡片 token，转到恢复/登录流程。
- 卡片访问：正确 token 可以读取余额、积分流水、集章、抽奖次数和有效券；错误或缺失 token 被拒绝。
- 生日只读登录：可查看卡片快照，但不返回 `card_token`，不能通过只读会话花积分。
- PIN 恢复：正确 PIN 恢复完整卡片；错误 PIN 使用通用错误；连续失败会锁定并生成风险事件；弱 PIN 被拒绝。
- 客户积分换抽奖：扣除 `points_per_draw`，服务器加权抽奖，返回奖品结果/券或积分返还。
- 客户积分换券：扣积分、生成固定面额的下次到店券。
- 连续点击/重试：相同抽奖 `request_id` 幂等，不重复扣积分或生成第二个抽奖结果。
- 余额不足、每日抽奖上限、奖品库存耗尽和无可用奖品：后端拒绝且不应产生半条数据。

## 5. 运维、店员、分店和管理员测试

### 5.1 店员角色

- 可以通过卡片 token 或手机号查客户，但返回给平板的是掩码手机号，不返回完整卡片 token。
- 可以提交消费金额，后端按 `amount_yen // 1000 * points_per_1000yen` 计算积分。
- 消费确认会创建 `SpendVerification`，首次营业日创建 `CheckInRecord`，保存确认员工、分店、来源 IP 和风险等级。
- 可以查看自己最近创建的确认记录；不能列出全部消费确认。
- 不能管理活动、奖品和库存，不能调整客户积分，不能作废消费确认。
- 可以验证和核销普通券；需要店长确认的高价值券，普通 `staff` 被拒绝。
- 可选的账号级 `StaffPermission` 开关可以禁止某个 staff 进行消费确认或券核销。

### 5.2 branch 角色

- 只能看到并操作本分店活动和记录。
- 可以查看本分店客户相关运营数据，但不能执行管理员专属的积分调整、客户删除、消费确认作废和奖品经济配置操作。
- 可以核销需要店长确认的券；同 Organization 跨分店券核销当前被实现为允许，这是现有测试明确覆盖的业务选择，需要继续确认是否符合实际运营政策。

### 5.3 admin 角色

- 可管理本 Organization 内的活动、客户、积分调整、客户删除、消费确认作废、奖品、里程碑、风险事件和 staff 权限。
- 不能操作其他 Organization 的客户、消费确认、券和活动。
- 消费确认是追加记录，普通更新/删除路由未开放；作废需要原因并写反向积分流水。

### 5.4 风控和运营流程

当前实现了并测试了：非营业时段确认、员工短时间大量确认、金额刚好等于券门槛、同客户多分店出现、同 IP 多账号登记、客户短时间多次抽奖、高价值奖品连中、作废后价值已被使用等风险事件。

风控规则原则上只标记风险，不自动判定作弊；风险事件支持 Organization/branch 隔离和管理员/分店查看、审核。

## 6. 抽奖专项检查结果

| 项目 | 结果 | 证据/说明 |
|---|---|---|
| 安全随机数 | 通过 | `promotions/services.py` 使用 `secrets.SystemRandom()` |
| 权重抽奖 | 通过 | 只从 active、weight>0 且有库存的奖品中选择 |
| 权重快照 | 通过 | `LotteryDraw` 保存 `weight_snapshot` 与 `total_weight_snapshot` |
| 总库存 | 有风险 | 新建奖品的 `remaining_stock` 初始化缺失，见 F-02 |
| 每日库存 | 通过专项测试 | 按 prize + branch + business local date 统计已中奖记录 |
| 客户每日抽奖上限 | 通过专项测试 | `max_draws_per_customer_per_day` 生效 |
| 积分抽奖扣款 | 通过专项测试 | 余额不足拒绝，成功后扣分并写流水 |
| 直抽次数扣减 | 基础通过 | 有次数才能抽，成功后扣 1 次 |
| 直抽与消费确认关联 | 有审计缺口 | guest direct draw 没有传入 `spend_verification`，见 F-04 |
| 抽奖幂等 | 通过专项测试 | 同客户相同 `request_id` 不重复扣分；不同客户碰撞被拒绝 |
| 奖品券生成 | 通过专项测试 | 普通奖品生成下次到店券，积分返还奖不生成券 |
| 最小消费门槛 | 通过专项测试 | 未达到门槛不能核销 |
| 过期券 | 通过专项测试 | 过期时拒绝并标记过期 |
| 高价值券审批 | 通过专项测试 | staff 拒绝，branch/admin 可审批后核销 |
| 重复券核销 | 通过服务实现/测试 | 行锁保证单次核销 |

## 7. 已确认问题与 AI 修复任务

以下每个任务块都可以单独交给 AI 编码代理。交给 AI 时应要求先阅读指定文件和对应 Markdown，再修改代码并补测试；不要让 AI 顺带重构无关模块。

### F-01 / P1：活动时间窗没有真正生效

现象：`Campaign` 有 `starts_at` 和 `ends_at`，但核心路径只检查 `status == active`。状态为 active、但尚未开始或已经结束的活动，仍可能被登记、消费确认、积分兑换和抽奖。

定位：

- `/Users/tatsuya/Documents/Projects/shop/store-admin-backend/promotions/services.py:44-60`：`load_store_token`
- `/Users/tatsuya/Documents/Projects/shop/store-admin-backend/promotions/services.py:223-232, 554-580, 683-690`
- `/Users/tatsuya/Documents/Projects/shop/store-admin-backend/promotions/views.py:314-317`

可复制给 AI 的提示词：

```text
请修复抽奖活动有效期校验。先阅读：
- store-admin-backend/promotions/models.py 的 Campaign
- store-admin-backend/promotions/services.py 的 load_store_token、verify_spend、draw_lottery、redeem_points
- store-admin-backend/promotions/views.py 的 _active_campaign_for 和所有 guest 入口
- 打卡与抽奖实施方案.md §6、§8、§13

要求：
1. 定义一个统一、可测试的 campaign_is_usable/campaign_active_at 规则，明确 starts_at/ends_at 为空时的含义；建议开始时间包含、结束时间不包含。
2. 登记、消费确认、积分换抽奖、积分换券、直抽都必须按同一规则校验，不能只检查 status。
3. 错误码保持稳定、不要泄露活动是否存在的额外信息。
4. 增加开始前、结束后、边界时刻、无时间窗和暂停状态测试。
5. 不改变 Organization/Branch 隔离，不重构无关模块。
6. 修复后运行 python manage.py test promotions 和全量测试。
```

### F-02 / P1：限量奖品新建后可能变成无限库存

现象：`Prize.remaining_stock` 是只读且默认为 NULL；`PrizeViewSet.perform_create` 只保存 `campaign`。管理员提交 `total_stock=10` 时，`remaining_stock` 仍可能是 NULL，而抽奖逻辑把 NULL 当成无限库存。

定位：

- `/Users/tatsuya/Documents/Projects/shop/store-admin-backend/promotions/serializers.py:231-253`
- `/Users/tatsuya/Documents/Projects/shop/store-admin-backend/promotions/views.py:768-814`
- `/Users/tatsuya/Documents/Projects/shop/store-admin-backend/promotions/services.py:519-551`
- 当前测试 `/Users/tatsuya/Documents/Projects/shop/store-admin-backend/promotions/tests.py:738-756` 手动同时传了 `remaining_stock`，没有覆盖后台新建路径。

可复制给 AI 的提示词：

```text
请修复 Prize 的总库存/剩余库存初始化和编辑规则。先阅读：
- store-admin-backend/promotions/models.py 的 Prize
- promotions/serializers.py 的 PrizeSerializer
- promotions/views.py 的 PrizeViewSet
- promotions/services.py 的 _pick_prize 和 draw_lottery
- 打卡与抽奖实施方案.md §6、§7、§11

要求：
1. total_stock 为 NULL 表示无限库存；total_stock 为非 NULL 时，新建奖品必须把 remaining_stock 初始化为 total_stock。
2. 明确更新 total_stock、remaining_stock 的权限和策略，禁止把剩余库存写成负数或无意中重置已消耗库存。
3. 现有数据库数据要兼容，不能破坏已有奖品和抽奖历史。
4. 增加 API 新建限量奖品、抽奖耗尽、编辑库存边界和并发扣库存测试。
5. 不允许前端通过请求体直接伪造 remaining_stock 绕过规则。
```

### F-03 / P1：guest 手机号恢复缺少租户上下文

现象：客户数据按 `(organization, phone)` 唯一，但 `GuestLoginView` 按 `phone + birthday_md` 全局查询，`recover_card` 也按手机号全局查询。若多个 Organization 使用同一手机号，可能读取或恢复到不确定的客户卡。

定位：

- `/Users/tatsuya/Documents/Projects/shop/store-admin-backend/promotions/views.py:190-225`
- `/Users/tatsuya/Documents/Projects/shop/store-admin-backend/promotions/services.py:181-212`
- `/Users/tatsuya/Documents/Projects/shop/store-admin-backend/promotions/models.py:85-110`

可复制给 AI 的提示词：

```text
请修复 guest 手机号登录/PIN 恢复在多租户下的客户选择问题。先阅读：
- promotions/models.py 的 Customer 和 Campaign
- promotions/views.py 的 GuestLoginView、GuestRecoverView、GuestRegisterView
- promotions/services.py 的 recover_card、register_customer
- common/permissions.py 和跨 Organization 测试

要求：
1. 不得因为 phone+birthday 或 phone+PIN 在多个 Organization 命中而返回任意一个客户。
2. 设计一个保留现有用户体验的租户上下文方案，例如要求店内 campaign/store_token，或让恢复入口明确绑定 Organization；如果确实决定系统只允许全局手机号唯一，必须以数据库约束、迁移和文档证明。
3. 错误响应不能泄露手机号是否存在或属于哪个租户。
4. 增加两个 Organization 使用相同手机号/生日/PIN 的登录、恢复、登记隔离测试。
5. token-authenticated card、店员 lookup 和券核销的现有行为不能被破坏。
```

### F-04 / P1：直抽次数作废扣回无法按来源准确归属

现象：客户只有聚合字段 `draw_chances`。两笔消费各产生一次直抽资格后，客户抽掉其中一次，再作废第一笔消费，系统只能简单执行 `draw_chances -= 1`，可能误扣掉第二笔消费产生的未使用资格。另一个审计问题是 guest `/draw/` 创建 `LotteryDraw` 时没有传 `spend_verification`。

定位：

- `/Users/tatsuya/Documents/Projects/shop/store-admin-backend/promotions/services.py:365-380`
- `/Users/tatsuya/Documents/Projects/shop/store-admin-backend/promotions/services.py:603-634`
- `/Users/tatsuya/Documents/Projects/shop/store-admin-backend/promotions/views.py:363-388`
- `/Users/tatsuya/Documents/Projects/shop/store-admin-backend/promotions/models.py:361-398`

可复制给 AI 的提示词：

```text
请修复 direct draw chance 的来源归属、消费作废和审计链路。先阅读：
- promotions/models.py 的 SpendVerification、LotteryDraw、Customer
- promotions/services.py 的 verify_spend、draw_lottery、void_spend_verification
- promotions/views.py 的 GuestDrawView
- 打卡与抽奖实施方案.md §6、§8、§10、§13

要求：
1. 能准确表示每笔消费产生了多少直抽资格、已使用多少、作废时还能撤销多少。
2. 作废一笔消费不得误扣其他消费留下的未使用资格；已使用的资格按照产品规则保留或生成风险待处理记录，但不能静默误扣。
3. 直抽成功记录应能追溯到产生资格的 SpendVerification；如果采用聚合资格池，必须明确并实现可审计的分配策略。
4. 保持 draw_lottery 的余额锁、库存锁、request_id 幂等和并发安全。
5. 增加“两笔消费→使用一次→作废第一笔”和并发测试，并验证 LotteryDraw.spend_verification 或等价审计字段。
```

### F-05 / P1-P2：消费确认的重复提交策略不完整

现象：同一客户、同一活动、同一营业日只复用 `CheckInRecord`，但每次都新建 `SpendVerification`、发积分；集章也每次增加。当前实现符合“每笔真实消费都可以确认”的一种解释，但没有请求幂等键，因此网络重试或店员重复点击会产生重复奖励。

定位：

- `/Users/tatsuya/Documents/Projects/shop/store-admin-backend/promotions/services.py:223-309`
- `/Users/tatsuya/Documents/Projects/shop/store-admin-backend/promotions/views.py:609-669`
- `/Users/tatsuya/Documents/Projects/shop/store-admin-backend/promotions/tests.py:125-138`

可复制给 AI 的提示词：

```text
请先解决消费确认“真实多笔消费”和“重复请求”之间的业务规则，再实现代码。先阅读：
- promotions/services.py 的 verify_spend
- promotions/models.py 的 SpendVerification、CheckInRecord
- promotions/views.py 的 SpendVerificationViewSet
- 打卡与抽奖实施方案.md §4、§8、§10、§13

要求：
1. 明确是否“一笔 POS 消费只能确认一次”，以及同一营业日第二笔真实消费是否仍应发积分。
2. 若一笔消费只能确认一次，增加 request_id/交易号等幂等键，重复请求返回原确认结果，不重复积分、集章或直抽资格。
3. 若当前没有 POS 交易号，至少让前端重试可以安全复用 request_id，并保留人工确认不同消费的路径。
4. 集章是否按每笔消费还是每次到店必须明确；不要只为了让测试通过而把所有第二笔消费拒绝。
5. 增加重复点击、网络重试、同日两笔真实消费、并发确认和作废测试。
```

### F-06 / P2：`max_draws_per_verification` 配置没有生效

现象：Campaign 保存了 `max_draws_per_verification`，但 `verify_spend` 达到 `direct_draw_threshold_yen` 时固定只增加 1 次；前端 CampaignPayload 也没有该字段。若该字段是未来配置，应隐藏/标记未实现；若是当前规则，应按定义计算并测试。

定位：

- `/Users/tatsuya/Documents/Projects/shop/store-admin-backend/promotions/models.py:29-48`
- `/Users/tatsuya/Documents/Projects/shop/store-admin-backend/promotions/services.py:258-262`
- `/Users/tatsuya/Documents/Projects/shop/store-admin-frontend/src/api/promotions.ts:108-121`

可复制给 AI 的提示词：

```text
请处理 max_draws_per_verification 的配置与实现不一致。先阅读模型、serializer、前端 CampaignPayload 以及打卡与抽奖实施方案.md §6、§15。
要求：
1. 先确认产品规则：一次消费达门槛是否永远只送 1 次，还是金额可以产生多次直抽。
2. 若当前永远只送 1 次，删除或明确标记该字段为未启用，并避免后台展示一个看似可配置但不起作用的字段。
3. 若需要生效，明确 floor/门槛/上限算法，服务端计算，不信任前端，并增加边界和并发测试。
4. 前后端字段、文案和测试必须一致。
```

### F-07 / P2：后台前端不能配置活动开始/结束时间

现象：后端 Campaign serializer 有 `starts_at`、`ends_at`，但前端 `CampaignPayload` 和活动表单没有提交这两个字段。即使后端补上时间窗校验，运营人员也可能无法通过当前后台设置时间。

定位：

- `/Users/tatsuya/Documents/Projects/shop/store-admin-frontend/src/api/promotions.ts:25-139`
- `/Users/tatsuya/Documents/Projects/shop/store-admin-frontend/src/views/PromotionsView.vue:70-140`
- `/Users/tatsuya/Documents/Projects/shop/store-admin-backend/promotions/serializers.py:25-64`

可复制给 AI 的提示词：

```text
请让营销后台的 Campaign 时间字段与后端一致。先阅读 promotions API 类型转换、PromotionsView 表单和 CampaignSerializer。
要求：
1. 支持 starts_at/ends_at 的显示、编辑、提交和回填，明确使用 Asia/Tokyo 时区。
2. 校验结束时间不得早于开始时间；显示空值代表无边界的含义。
3. 与统一活动有效期校验共享规则，不在前端单独实现另一套逻辑。
4. 增加前端类型检查、后端 serializer/API 测试。
```

### F-08 / P2：生日月日允许不存在的日期

现象：`normalize_birthday_md` 只检查月份 1–12、日期 1–31，因此 `02-31` 会被接受。前端也固定提供每月 31 天。

定位：

- `/Users/tatsuya/Documents/Projects/shop/store-admin-backend/promotions/utils.py:60-78`
- `/Users/tatsuya/Documents/Projects/shop/store-admin-frontend/src/views/guest/GuestRegisterView.vue:27-42, 105-115`

可复制给 AI 的提示词：

```text
请修复生日月日的日历合法性校验。先阅读 promotions/utils.py、GuestRegisterView、GuestLoginView 以及现有生日测试。
要求：
1. 接受 M/D、MM-DD、日文格式后，统一校验为真实月日；至少拒绝 02-31、04-31、06-31、09-31、11-31。
2. 不需要年份，不要把 02-29 按固定年份错误拒绝；应采用明确的无年份规则。
3. 前端日期选择器应避免向用户提供明显无效的日期，后端仍必须是最终校验者。
4. 保持错误码和已有合法输入兼容，并补测试。
```

### F-09 / P2：历史 lottery 模块对 staff 返回完整个人信息

现象：历史 `/lottery` 页面允许 staff 进入，后端 `DabingPersonSerializer` 和记录 serializer 返回完整手机号、联系方式等字段；前端默认隐藏后四位不能替代后端最小权限。

定位：

- `/Users/tatsuya/Documents/Projects/shop/store-admin-backend/lottery/views.py:16-29`
- `/Users/tatsuya/Documents/Projects/shop/store-admin-backend/lottery/serializers.py:17-44`
- `/Users/tatsuya/Documents/Projects/shop/store-admin-frontend/src/router/index.ts:73-77`

可复制给 AI 的提示词：

```text
请按最小权限原则检查历史 lottery 模块的 staff 个人信息返回。先阅读 lottery 的 views、serializers、models、前端 LotteryView 和现有角色权限测试。
要求：
1. 明确 staff 是否业务上需要读取完整手机号、联系方式、生日和设备信息。
2. 若不需要，后端按角色使用掩码 serializer 或禁止 staff 进入该模块；不能只靠前端隐藏。
3. 保持 admin/branch 当前必要的运营能力和 Organization 隔离。
4. 增加 API 响应字段级权限测试，防止未来前端改动重新暴露 PII。
```

## 8. 当前通过但应持续关注的实现

- 抽奖使用行锁和权重快照，核心实现方向正确；上线前仍应增加真实 MySQL 并发压测，而不是只依靠顺序单元测试。
- 公开 guest 限流已经接入 `DatabaseCache` 和 DRF throttle，当前不是“完全无限流”。但主要按 IP 限制，仍需评估 NAT 误伤、分布式攻击、card token/手机号维度和代理配置 `PROMOTIONS_TRUSTED_PROXY_COUNT`。
- 同 Organization 跨分店券核销当前是允许的，并有测试；这不是自动判定的 bug，而是需要店主确认的运营规则。
- 积分过期按 `months * 30` 天近似计算；如果要求严格按自然月，应另行定义并补日历边界测试。
- 客户删除会脱敏/解绑流水、消费确认、抽奖和券，但仍需上线前确认 APPI 保留期限、备份、日志和导出文件是否也要处理。
- 一个分店能否同时有多个 active Campaign、活动结束后的客户积分和券应绑定哪个活动，目前主要依赖业务约定，建议增加数据库/服务层不变量。

## 9. 前端质量问题

### ESLint 失败项

1. `/Users/tatsuya/Documents/Projects/shop/store-admin-frontend/src/components/CampaignPrizesDrawer.vue:5`：导入 `Delete` 但未使用。
2. `/Users/tatsuya/Documents/Projects/shop/store-admin-frontend/src/views/PromotionsView.vue:9`：导入 `todayJst` 但未使用。

可复制给 AI 的提示词：

```text
请只修复以下两个 ESLint 未使用导入，不要进行其他重构：
- store-admin-frontend/src/components/CampaignPrizesDrawer.vue:5 的 Delete
- store-admin-frontend/src/views/PromotionsView.vue:9 的 todayJst

修复后运行：
1. npm run type-check
2. npx oxlint .
3. npx eslint . --no-cache
4. npm run build-only
```

### Bundle 警告

Vite 构建通过，但报告：

- 约 1.37 MB 的主 chunk，gzip 约 448 KB。
- 约 0.93 MB 的 Excel 导出 chunk，gzip 约 257 KB。

这不是当前功能失败，但建议后续把 Excel、PDF、图表和非首屏管理模块继续动态拆包；拆包后必须重新运行生产构建和主要路由加载检查。

## 10. 生产上线检查

`manage.py check --deploy` 当前有 6 项开发配置提醒：

- 未设置 HSTS。
- 未启用 SSL 强制跳转。
- SECRET_KEY 仍为开发值/长度不足。
- `SESSION_COOKIE_SECURE=False`。
- `CSRF_COOKIE_SECURE=False`。
- `DEBUG=True`。

这些不是本地开发功能失败，但正式上线前必须通过生产环境变量、HTTPS 反向代理和正式域名处理。店内固定二维码写入前端域名，正式域名确认后要重新生成并打印二维码。

## 11. 推荐 AI 修复顺序

1. F-03 多租户 guest 登录/恢复隔离。
2. F-01 活动时间窗统一校验。
3. F-02 限量奖品库存初始化和编辑策略。
4. F-04 直抽次数来源、作废和审计链路。
5. F-05 消费确认幂等和同日集章业务规则。
6. F-07 前端活动时间字段。
7. F-06 无效配置字段的实现/隐藏决策。
8. F-09 历史 lottery staff PII 权限。
9. F-08 生日合法性。
10. ESLint 两个未使用导入和前端包拆分。

每一项修复后，都要求 AI：

- 先读相关源码、迁移、测试和产品 Markdown。
- 先写能复现问题的测试，再修改实现。
- 运行专项测试、全量后端测试和前端检查。
- 不改变无关模块、租户隔离、权限边界和已有审计字段。
- 在最终输出中列出修改文件、测试命令、测试结果和仍需业务确认的决策。

## 12. 工作区声明

本轮没有修改代码。检查开始和收尾时工作区都存在多项未提交修改和新增文件；两次状态清单出现了部分差异，不能归因于本次检查，可能有其他并行开发进程，请提交前自行确认。整个过程中没有执行 reset、checkout、格式化、lint 自动修复或删除操作。临时启动的本地前端测试服务已停止；数据库测试使用 Django 测试数据库并在测试结束后销毁。
