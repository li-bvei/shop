w# 店铺积分卡 / 打卡抽奖 — 开发任务书（给 AI 编码代理）

## 0. 怎么用这份文档

- **产品设计的唯一真相来源**是同目录的 `打卡与抽奖实施方案.md`。本文档不重复产品逻辑，只补三样东西：**① 项目现状 ② 编码约定 ③ 阶段 1 的具体实现任务 ④ 需要你（实现者）拍板的技术细节**。
- 开工前**必须完整读一遍** `打卡与抽奖实施方案.md`（18 节），特别是 §2 信任模型、§5 积分、§6 奖池、§7 券、§11 数据模型、§13 反作弊。
- 分阶段做。本文档聚焦**阶段 1（客人卡 + 打卡 + 消费确认 + 赚积分）**。阶段 2 及以后见 §8。
- 这是现有项目的增量开发，**严格沿用现有约定**（见 §2）。不要引入新的架构风格、新的状态管理、新的 HTTP 客户端。

---

## 1. 项目现状

### 1.1 是什么

`shop` 是一个**多租户的店铺后台管理系统**（餐饮连锁）。一个 Django + DRF 后端 + 一个 Vue 3 SPA 前端。已上线功能：日报、进货、供应商、商品、库存、员工、排班、工资、仪表盘。本任务是给它加一个**面向客人的积分卡 + 打卡 + 抽奖**模块。

### 1.2 仓库结构

```
shop/
├── store-admin-backend/     Django + DRF + MySQL
│   ├── config/              settings.py / urls.py / wsgi.py
│   ├── common/              permissions.py（复用）· test_utils.py（复用）
│   ├── organizations/ accounts/ branches/ staff/ paymentmethods/
│   ├── dailyreports/ purchasing/ dashboard/ scheduling/ wages/ inventory/
│   └── manage.py  requirements.txt  Dockerfile
├── store-admin-frontend/    Vue 3 + TS + Element Plus + Pinia + vue-router + vue-i18n
│   └── src/{api,router,stores,layouts,components,views,i18n,composables}
├── docker-compose.yml       db(mysql8) + backend(gunicorn) + frontend(nginx)
├── 打卡与抽奖实施方案.md      ← 产品设计（必读）
├── 抽奖与打卡功能方案.md      ← 更早的评审稿（背景参考，部分已被上面那份取代）
└── promotions-开发任务书.md   ← 本文档
```

没有 `CLAUDE.md`。约定靠读现有代码归纳，本文档 §2 已归纳好。

### 1.3 后端栈

```
Django==4.2.30            djangorestframework==3.16.1
djangorestframework-simplejwt==5.5.1   django-filter==25.1
django-cors-headers==4.9.0             django-environ==0.14.0
PyMySQL==1.2.0            gunicorn      （无 celery / redis / channels）
```

- MySQL 8 via PyMySQL（`config/__init__.py` 里 `pymysql.install_as_MySQLdb()` 垫片）
- 测试用 SQLite（`common/test_utils.py`）——**写模型时注意 MySQL/SQLite 差异**，见 `inventory/serializers.py` 里 `validate_jan_code` 的注释：MySQL 不支持带 `condition=` 的 `UniqueConstraint`，需要在 serializer 里补校验
- 时区：`TIME_ZONE = 'Asia/Tokyo'`，`USE_TZ = True`
- JWT：access 8h，refresh 7d，`ROTATE_REFRESH_TOKENS = True`

### 1.4 后端约定（重点，照抄）

**app 结构** — 每个 app：`models.py` / `serializers.py` / `views.py`（DRF ViewSet）/ `services.py`（跨模型事务性业务逻辑）/ `urls.py`（`DefaultRouter`）/ `admin.py` / `tests.py`。参考 `inventory/` 或 `purchasing/`。

**接入方式** — `config/settings.py` 的 `INSTALLED_APPS` 末尾加 `'promotions'`；`config/urls.py` 加 `path('api/', include('promotions.urls'))`。和最近加的 `inventory` 一模一样。

**多租户** — `Organization`（租户）→ `Branch`（门店，`id` 是 SlugField 主键，如 `shinsaibashi`）→ `accounts.User`。`User.role` ∈ `admin` / `branch` / `staff`：
- `admin`：管本 Organization 全部门店
- `branch`：只管自己 `user.branch`
- `staff`：默认被 `DenyStaffRole` 拒绝一切，按需在具体 view 上 opt-in

**权限工具**（`common/permissions.py`，直接 import 用）：
- `BranchScopedQuerysetMixin` — viewset 混入，自动按 org/branch 过滤 queryset + `perform_create` 注入 branch。`branch_field` 默认 `'branch_id'`，支持关系路径
- `IsAdminRole` — 只允许 `role == admin`
- `DenyStaffRole` — **项目级默认权限之一**，拒绝 staff。想让 staff 访问某 view，在该 view 上写 `permission_classes = [IsAuthenticated]` 覆盖，然后在 `get_queryset` / `perform_*` 里手动判 `user.role == user.Role.STAFF`。范例：`scheduling/views.py` 的 `AvailabilityRequestViewSet` / `ActualWorkRecordViewSet`

**DRF 默认配置**（`config/settings.py` `REST_FRAMEWORK`）：
```python
DEFAULT_AUTHENTICATION_CLASSES = (JWTAuthentication,)
DEFAULT_PERMISSION_CLASSES = (IsAuthenticated, DenyStaffRole)
DEFAULT_FILTER_BACKENDS = (DjangoFilterBackend,)
DEFAULT_PAGINATION_CLASS = None      # 前端拉全量、客户端过滤
```

**项目目前没有的东西**（本功能要补）：
- **分页** — 全局关闭。但本功能的客人 / 打卡 / 消费确认 / 抽奖 / 兑换列表会快速增长，**这几个后台列表必须分页**。照 `purchasing/views.py` 的 `PurchasePagination`（`PageNumberPagination`，`page_size=50`，`max_page_size=200`）在本 app 内局部启用
- **缓存** — 无 `CACHES` 配置（默认 `LocMemCache`，多 worker 不共享）。限流（阶段 3）依赖共享缓存。**阶段 1 就把 DB 缓存表建好**：`config/settings.py` 加 `CACHES`（`django.core.cache.backends.db.DatabaseCache`），迁移里或部署脚本里 `python manage.py createcachetable`
- **限流 / throttle** — 无。阶段 3 加。阶段 1 的公开接口先留 TODO 注释标出该限流的位置

**追加账本模式**（本功能的 `PointsLedger` 照此写）— `inventory/models.py` 的 `StockTransaction`：不可变、不 update 不 delete、每次余额变动配一条、纠正靠反向记一条。

**事务性余额变动**（本功能的"发积分""扣积分抽奖"照此写）— `inventory/services.py` 的 `adjust_stock`：
```python
with transaction.atomic():
    row = Model.objects.select_for_update().get_or_create(...)  # 行锁
    ... 校验 ...
    row.save(update_fields=[...])
    Ledger.objects.create(...)                                  # 同一事务内写账本
```

**追加历史 + who/when 从 request 取**（不信客户端）— `dailyreports/models.py` 的 `DailyReportHistory`。

**审计字段** — `scheduling` 里普遍：`created_by` / `updated_by` / `verified_by` / `confirmed_at` 等，从 `self.request.user` / `timezone.now()` 注入，不从 payload 取。作废走独立 action（`void`），留 `voided_by` / `void_reason`。

**测试 fixture**（`common/test_utils.py`，直接继承）：
- `ApiTestCase` — 1 个 Organization、2 个 Branch（各 seed 了付款方式 + 排班设置）、1 个 admin、每 branch 1 个 branch 账号、1 个 staff 账号（关联 branch_a 的一个 StaffMember）。`self.org` / `self.branch_a` / `self.branch_b` / `self.admin` / `self.branch_a_user` / `self.staff_user` / `self.staff_employee`
- `TwoOrganizationApiTestCase` — 两个独立 Organization，用于跨租户隔离测试
- `self.login_as(user)` — 走真实 `/api/token/` 拿 JWT（不是 `force_authenticate`）

### 1.5 前端栈与约定

```
vue@3.5  element-plus@2.14  pinia@4  vue-router@5.2  vue-i18n@9.14
vite@8  typescript@6  vue-tsc   node ^22.18 || >=24.12
```
已有依赖里有 `html2canvas` `jspdf`（截图 / PDF）。**没有 QR 库**——本功能加 `qrcode`（npm）用于前端渲染二维码。

**`src/api/*.ts` 模式** — 每个模块：定义前端用的 camelCase interface + 后端 DTO 的 snake_case interface + `fromDto()` 转换函数 + 导出 async 函数调用 `http`。参考 `src/api/inventory.ts`。**所有网络请求走 `src/api/http.ts` 导出的 `http.get/post/patch/delete`**，它处理 JWT header + 401 自动 refresh + `ApiError`。

**⚠ 但公开客人接口没有 JWT**——见 §4.7，需要为 guest 接口做一个不带 Authorization、带 guest token 的轻客户端，不要硬塞进 `http`。

**路由**（`src/router/index.ts`）— 数组式 routes，`meta: { public: true }` 免登录（目前只有 `/login`），`meta: { roles: ['admin','branch'] }` 角色门。`beforeEach` 守卫。所有非 public 路由挂在 `AppShell` 布局下。**本功能加：**
- 公开客人页：新增几个 `meta: { public: true }` 路由，**不挂 `AppShell`**，用一个新的轻布局
- 店员平板页：一个 `meta: { roles: ['staff','branch','admin'] }` 的路由，可以挂 `AppShell` 也可以做独立 kiosk 布局（建议独立，全屏、大按钮）

**auth store**（`src/stores/auth.ts`）— `useAuthStore`，`role` / `branchId` / `staffMemberId`。`main.ts` 启动时 `restoreSession()`。公开客人页不依赖它。

**导航**（`src/components/AppSidebar.vue`）— `adminBranchNavItems` / `staffNavItems` 两个数组。店员平板页若进 `AppShell`，往 `staffNavItems` 加一项。

**i18n**（`src/i18n/locales/zh.ts` / `ja.ts`）— 两份大对象，中文为主。管理端文案两份都要加。**客人页面日文优先**（决定 15）。

**部署**（`docker-compose.yml` + `store-admin-frontend/nginx.conf`）— nginx 服务 SPA（history 模式 `try_files`）+ 反代 `/api/` 到 `backend:8000`。单域名同源。加公开客人页不需要改 nginx（同一个 SPA）。

### 1.6 本地起项目

后端：`cd store-admin-backend && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt && cp .env.example .env`，建库，`python manage.py migrate && python manage.py seed_demo_data && python manage.py runserver`（端口看前端 `.env.development.local` 的 `VITE_API_BASE_URL`）。demo 登录：`admin` / `shinsaibashi01` / `namba01` / `umeda01`（密码见 `branches/management/commands/seed_demo_data.py`）。

前端：`cd store-admin-frontend && npm install && npm run dev`。

---

## 2. 新功能总览

### 2.1 交付物

- 后端新 app：`store-admin-backend/promotions/`
- 前端三块（都在现有 SPA 内）：
  1. **管理后台** — 活动 / 奖品 / 概率 / 库存 / 客户信息管理。沿用现有 JWT + 角色 + `AppShell`
  2. **店员平板页** — 柜台平板上，扫客人卡片二维码 + 输金额 + 确认；扫券核销。`staff` 路由，kiosk 布局
  3. **公开客人页** — 登记 / 卡片（余额 / 流水 / 券）/ 只读登录 / 抽奖。`public` 路由，轻布局，日文优先
- 硬件（用户采购，不涉及代码）：柜台平板 + 蓝牙 2D 读码器（HID 键盘模式，即"扫完把内容当键盘敲进当前输入框 + 回车"，同 `inventory` 的扫码逻辑）

### 2.2 三条铁律（不可违反）

1. **唯一可信事件 = 店员在客人面前点的确认**。公开客人接口绝不接受 `amount_yen` / `table_number` / `consumed_at` / `points_granted` / `prize_id` / 直接改积分余额。积分只在店员消费确认接口里由服务端产生。
2. **价值一律"下次用"的券**。抽奖 / 兑换不作用于当前账单，收银台不退款不改账。
3. **不做手机验证**。手机号是不验证的主键，接受假号 / 借号。

### 2.3 不做清单（明确不实现）

LINE / LIFF · 浏览器定位 · 60 秒轮换二维码 + 展示屏 · 短信/邮件 OTP · 会员等级 / 会员价 · 当场抵扣餐费 · 开放式免单（顶奖是 ¥5,000 封顶券）· 前端抽奖随机（抽奖必须服务端）。

---

## 3. 阶段 1 开发任务

**范围**：客人卡（登记 / 卡片页 / 只读登录）+ 每次到店打卡 + 店员消费确认 + 按消费额发积分 + 积分流水 + 基础权限审计。
**不含**：抽奖、奖品、券、里程碑发放、风险规则（阶段 2 / 2.5 / 3）。

### 3.1 后端 — `promotions` app

#### 3.1.1 脚手架
- `python manage.py startapp promotions`，移到 `store-admin-backend/promotions/`
- `INSTALLED_APPS` 加 `'promotions'`；`config/urls.py` 加 include
- `promotions/urls.py` 用 `DefaultRouter`

#### 3.1.2 CACHES（阶段 1 就配好，给阶段 3 的限流用）
- `config/settings.py` 加：
  ```python
  CACHES = {'default': {
      'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
      'LOCATION': 'promotions_cache_table',
  }}
  ```
- 在 `promotions` 的某个 migration 里 `RunPython` 调 `createcachetable`，或写进部署文档（README + docker entrypoint）

#### 3.1.3 模型（阶段 1 子集，完整字段见 `打卡与抽奖实施方案.md` §11）

| 模型 | 阶段 1 要点 |
|---|---|
| `Campaign` | 活动配置。`organization` + `branch`（FK，PROTECT/CASCADE 按现有惯例）、`status`、时间窗、`points_per_1000yen`（默认 10）、`stamp_target`（可空=关集章）、`business_day_cutover`（time，默认 05:00，见 §4.5）、`created_by`/`updated_by`/时间戳 |
| `Customer` | **`organization` + `phone` 唯一约束**（`UniqueConstraint(fields=['organization','phone'])`，MySQL 支持无 condition 的，OK）。`name`(blank) `birthday_md`(CharField 5, blank, 格式 `MM-DD`) `card_token`(唯一, 不可猜, 见 §4.2) `points_balance`(整数, 默认 0, 是 `PointsLedger` 的汇总, 只由 service 改) `stamp_count`(整数) `first_seen_at` `last_seen_at` `last_activity_at` `status`(active/blocked) `risk_level` `privacy_consented_at` |
| `PointsLedger` | 不可变。`customer` `delta`(整数, 正=赚/负=花) `reason`(TextChoices: spend/milestone/expire/adjust；draw/voucher 阶段 2.5) `source_content_type`+`source_object_id` 或简单 `source_ref` 字段 `balance_after` `note` `operator`(FK User, null, adjust 时填) `created_at`。**不给 update/delete 入口** |
| `CheckInRecord` | `customer` `branch` `campaign` `spend_verification`(FK) `checked_in_at` `local_date`(DateField, 按营业日算, 见 §4.5) `result` `risk_level`。**`UniqueConstraint(fields=['customer','campaign','local_date'])`** |
| `SpendVerification` | 全案最重要。`customer` `check_in_record`(FK) `campaign` `branch` `table_number`(blank) `amount_yen`(PositiveIntegerField) `consumed_at`(DateTimeField) `points_granted`(整数, 服务端算) `verified_by`(FK User, PROTECT/SET_NULL) `verified_at` `source_ip`(GenericIPAddressField, null) `status`(accepted/voided) `risk_level` `voided_at`/`voided_by`/`void_reason` `created_at`。**追加不可改**（普通 PATCH 关掉，见下） |

- `admin.py` 注册（只读为主，方便排查）
- 迁移用 `python manage.py makemigrations promotions`

#### 3.1.4 服务层 `promotions/services.py`

```python
def register_customer(*, organization, phone, name='', birthday_md='', ip=None) -> Customer
# 归一化 phone（去空格/横线，统一 0xx 和 +81 格式，存一种）；get_or_create by (org, phone)；
# 生成 card_token；记 privacy_consented_at；返回 Customer

def verify_spend(*, campaign, branch, customer, amount_yen, table_number, consumed_at, verified_by, ip) -> SpendVerification
# 校验：amount_yen >= 0 整数；consumed_at 不晚于 now；consumed_at 在营业日窗口内（§4.5）；
#       同一 customer 同 campaign 同 local_date 未打过卡（否则按规则：仍确认但不重复记打卡 / 或拒绝——见 §13 风险规则，阶段 1 先"仍确认、打卡 UniqueConstraint 兜底"）；
# 事务内：
#   - select_for_update 锁 Customer 行
#   - 创建 CheckInRecord（local_date 唯一约束防重复；已存在则复用）
#   - points = amount_yen // 1000 * campaign.points_per_1000yen
#   - customer.points_balance += points；customer.stamp_count += 1（若启用）；save(update_fields=...)
#   - PointsLedger.objects.create(delta=points, reason='spend', balance_after=..., source=SpendVerification)
#   - 创建 SpendVerification
# 返回 SpendVerification

def adjust_points(*, customer, delta, note, operator) -> PointsLedger   # admin 手动调分
def delete_customer_by_phone(*, organization, phone)                     # APPI 删除，级联见 §4.4
```

- 归一化手机号写成 `promotions/utils.py` 的 `normalize_phone()`，配单元测试（参考 `purchasing/utils.py` `normalize_item_name`）

#### 3.1.5 序列化器 / 视图 / 路由

**公开客人 API**（`permission_classes = [AllowAny]`，`authentication_classes = []`，鉴权靠 guest token 见 §4.7）：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/guest/register/` | `{ store_token, phone, name?, birthday_md?, consent:true }` → 校验 store_token（§4.6）解析出 campaign/branch → `register_customer` → 返回 `{ card_token, name, points_balance, stamp_count }` + `Set-Cookie` guest cookie（§4.7）。`consent` 必须为 true |
| POST | `/api/guest/login/` | `{ phone, birthday_md }` → 查 Customer，命中返回**只读**会话（不下发能核销的凭证）。用于换设备找回 |
| GET | `/api/guest/card/` | 凭 guest token / cookie 或只读会话 → `{ points_balance, stamp_count, ledger: [...最近 N 条], vouchers: [], campaign: {...} }`（vouchers 阶段 2 才有内容） |

- 全部标 `# TODO(phase-3): throttle` 注释
- store_token 解析失败 / campaign 非 active → 400，不泄漏细节

**店员 API**（`permission_classes = [IsAuthenticated]`，view 内判 `role in (staff, branch, admin)`；`staff` 只能操作自己 `user.branch`）：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/promotions/customers/lookup/` | `{ card_token \| phone }` → `{ id, name, phone(脱敏后段), points_balance, stamp_count, vouchers:[] }`。scoped 到 `user` 的 org |
| POST | `/api/promotions/spend-verifications/` | `{ card_token \| phone, amount_yen, table_number?, consumed_at? }`（`consumed_at` 缺省 = now）→ `verify_spend` → `{ check_in_id, points_granted, points_balance, risk_level:"normal" }`。`branch` = `user.branch`（admin 必须传 branch 且校验属本 org） |
| GET | `/api/promotions/spend-verifications/mine/` | 当前店员今天创建的确认，倒序 |

**管理员 / 分店 API**（`BranchScopedQuerysetMixin` + 现有角色规则；列表分页）：

| 方法 | 路径 | 说明 |
|---|---|---|
| CRUD | `/api/promotions/campaigns/` | admin 全 org，branch 只本店读写（参考 `scheduling` 的 branch 写权限判断） |
| GET | `/api/promotions/customers/` | 搜索（`phone` / `name`），分页；detail 含 `PointsLedger` 分页 |
| POST | `/api/promotions/customers/{id}/points-adjust/` | `{ delta:int, note:str(必填) }` · **仅 admin** · 调 `adjust_points` |
| DELETE | `/api/promotions/customers/{id}/` | · **仅 admin** · `delete_customer_by_phone` 级联（§4.4） |
| GET | `/api/promotions/campaigns/{id}/checkins/` `/verifications/` | 分页、可按日期 / 门店 filter（`django_filters`） |
| POST | `/api/promotions/verifications/{id}/void/` | `{ reason:str(必填) }` · **仅 admin** · 事务内：标 `status=voided` + 反向 `PointsLedger`（`delta = -points_granted`, `reason='adjust'`, `note='void: ...'`）+ 扣回 `customer.points_balance` |

- `SpendVerification` 的 ViewSet **关掉 update/destroy**（`http_method_names` 限制，或 `perform_update` raise `PermissionDenied`）。改动只能走 `void` action（admin）。参考 `scheduling` 的 `perform_update` 注释里 "普通 PATCH 永不移动 branch-scoped 业务行" 的思路

#### 3.1.6 权限要点
- 公开接口：`AllowAny`，但 **guest token / cookie 必须校验**，不能凭空返回别人的卡
- `staff`：只 `spend-verifications` + `customers/lookup` + `spend-verifications/mine`（阶段 2 加券核销）。**不能**列 campaigns / 所有客人 / 改积分
- `branch`：本店 campaign 读写 + 本店记录读 + `customers/lookup`。奖品库存是否可管 = 决定 09（默认 admin only，阶段 2 才有奖品）
- `admin`：本 org 全部；`points-adjust` / `void` / `DELETE customer` 仅 admin

#### 3.1.7 迁移 / 管理命令
- `promotions/management/commands/seed_promotions_demo.py` — 建一个 demo Campaign（active，绑 demo 的某个 branch，用 §5 默认值），方便前端联调
- 更新 `store-admin-backend/README.md`：新增 app、CACHES、`createcachetable`、seed 命令

### 3.2 前端

#### 3.2.1 依赖
- `npm i qrcode` + `npm i -D @types/qrcode`

#### 3.2.2 guest API 客户端 — `src/api/guest.ts`
- **不用 `http.ts`**（那个强绑 JWT）。写一个极简 fetch 封装：`credentials: 'include'`（带 guest cookie），可选 `X-Guest-Token` header（从 `localStorage` 的 `pc_guest_token` 读，§4.7），同源 `/api/guest/*`，复用 `ApiError` 类（从 `http.ts` export，或复制一份）
- 导出：`register()` / `guestLogin()` / `fetchCard()`

#### 3.2.3 公开客人页（`meta: { public: true }`，新轻布局 `src/layouts/GuestShell.vue`）
- 路由前缀建议 `/pc/*`（promo card）：
  - `/pc/register?t=<store_token>` — 登记页：手机号（必填）+ 姓名 + 生日（月/日两个 select）+ 隐私告知勾选 + 提交。成功后写 `localStorage.pc_guest_token` + 跳卡片页
  - `/pc/card` — 卡片页：大二维码（`qrcode` 渲染 `card_token`）+ 积分余额 + 集章进度 + 积分流水（最近 N 条）+ 券列表（阶段 2）。底部"截图保存"提示
  - `/pc/login` — 只读登录：手机号 + 生日 → 进只读卡片视图
- 老客人扫店内固定码 → 命中 `/pc/register?t=...`，前端检测 `localStorage.pc_guest_token` 存在则直接跳 `/pc/card`
- 日文优先：这几个页面的 i18n key 用 `guest.*` 命名空间，`ja` 先写全，`zh` 跟上
- `main.ts` 的 `restoreSession()` 对 guest 页无害（无 JWT 直接返回），但可以在 GuestShell 里不依赖 auth store

#### 3.2.4 店员平板页（`meta: { roles: ['staff','branch','admin'] }`，kiosk 布局）
- 路由 `/staff/promo-verify`（或类似）
- 一个常驻输入框（`autofocus`，提交后自动 `.focus()` 回来——参考现有进货录入页的 focus 管理，注意近期修过"下拉框在每次提交后弹出"的 bug，别重蹈）
- 流程：读码器把 `card_token` 敲进输入框 + 回车 → 调 `customers/lookup` → 显示客人名 + 积分 + 集章 → 店员输金额（数字键盘友好）→ 提交 `spend-verifications/` → 显示"打卡已记 / +N 积分 / 余额 X"，2 秒后回到待扫态
- 读不出时：手输 `card_token` 短码 / 手输手机号
- 用现有 `src/api/*.ts` 模式写 `src/api/promotions.ts`（走 `http`，因为店员是登录态）

#### 3.2.5 管理后台页（进 `AppShell`，`meta: { roles: ['admin','branch'] }`）
- `AppSidebar.vue` 的 `adminBranchNavItems` 加"营销活动"入口
- 阶段 1 只需：活动列表 + 活动编辑（配置字段）+ 客人列表 / 详情（含积分流水）+ 打卡 / 消费确认记录（分页表格，参考 `PurchasingView.vue` 的分页表格）+ 客人删除按钮（二次确认）+ 手动调分弹窗
- 奖品管理页留到阶段 2

#### 3.2.6 i18n
- 管理端文案：`zh.ts` + `ja.ts` 都加，`promotions.*` 命名空间
- 客人端文案：`guest.*`，日文写全

### 3.3 测试要求

- 后端每个 app 都有 `tests.py`，本 app 也要。**至少覆盖**：
  - `verify_spend` service：积分计算正确 / 同营业日不重复打卡 / `consumed_at` 未来被拒 / 事务失败不留半条数据（参考 `inventory/tests.py` `AdjustStockServiceTests`）
  - 并发：两个请求同时确认同一 customer，积分不重复加 / 不丢（`select_for_update`）
  - 跨租户隔离：用 `TwoOrganizationApiTestCase`，org A 的店员 lookup 不到 org B 的 customer；A 的 admin 删不了 B 的 customer
  - 权限：`staff` 不能列 campaigns / 不能调分 / 不能 void；`branch` 不能碰别店；公开接口不接受 `amount_yen`
  - 公开接口：无效 store_token 被拒；`consent != true` 被拒；guest token 错乱拿不到别人的卡
  - `void`：反向流水 + 余额扣回正确
- 跑 `python manage.py test promotions`

---

## 4. 需要实现者拍板的技术细节（含建议）

### 4.1 手机号归一化
- 存**归一化后**的形式：去空格 / 横线 / 括号；日本号统一成一种（建议存本地格式 `09012345678`，或 E.164 `+819012345678`——**二选一，全库一致**）。建议：本地格式（店员和客人都习惯报本地格式）。`normalize_phone()` + 测试。

### 4.2 `card_token` 机制
- **建议：不透明随机串 + DB 查**（不是签名令牌）。`secrets.token_urlsafe(16)`，`Customer.card_token` 唯一索引。
- 理由：便于风险冻结（`Customer.status=blocked`）、便于按客人查、不需要密钥轮换。
- 不轮换。写进二维码的就是这个 token 本身（不是 URL）。

### 4.3 只读登录会话（手机 + 生日）
- **建议**：`/api/guest/login/` 命中后，下发一个**只读作用域**的短期 token（如 `secrets` 串存 cache，TTL 24h，标记 `readonly=true`），或直接返回卡片数据快照不发 token。
- 只读会话能访问：`GET /api/guest/card/`。**不能**：核销券、`redeem`（阶段 2.5）、改任何东西。
- 生日是弱二factor，防"随便输个号看是谁"。不是安全边界（§14 已接受）。

### 4.4 APPI 删除级联（`delete_customer_by_phone`）
- **建议**：
  - `Customer` 行删除
  - `CheckInRecord` / `SpendVerification` / `LotteryDraw`：**不删**，但把 `customer` 置空 + 加一个 `customer_deleted=True` 标记（保留营业统计、店员审计的完整性），或匿名化（清 `table_number` 等）。
  - `PointsLedger`：保留（财务/纠纷追溯），`customer` 置空
  - 未核销的 `Voucher`：作废（`status=void`）
  - 记一条操作日志（谁在何时删的哪个手机号的哈希）
- 这条要写进隐私政策文案。最终口径让用户确认。

### 4.5 营业日切换（`business_day_cutover`）
- `Campaign.business_day_cutover`（`TimeField`，默认 `05:00`）
- `local_date(dt)` = `(dt 转 Asia/Tokyo - cutover) 的日期`。跨午夜营业的店，凌晨 2 点的消费算前一天。
- 用在：`CheckInRecord.local_date`（打卡去重）、`consumed_at` 的"当前营业日窗口"校验、日报表聚合。
- `scheduling` 有 `crosses_midnight` 概念可参考，但没有 cutover 配置，本功能新增。

### 4.6 店内固定二维码 `store_token`
- **建议**：签名令牌（`django.core.signing.dumps({'campaign_id':..., 'branch_id':...})`，无过期或很长过期）。印刷贴纸，永不变。
- 内容放进 URL：`https://<domain>/pc/register?t=<store_token>`（这个是可以放 URL 的——它是"入口"，不是身份）。
- 后台"营销活动"页提供每个门店的这个 URL + 生成二维码图片下载（`qrcode` 前端渲染或 `pillow` 后端，建议前端）。

### 4.7 guest 接口鉴权
- **建议**：双写。`/api/guest/register/` 成功时：
  - `Set-Cookie: pc_guest=<card_token>; HttpOnly; Secure; SameSite=Lax; Max-Age=34560000`（约 13 月）
  - 响应体也返回 `card_token`，前端存 `localStorage.pc_guest_token`
- `/api/guest/card/`：优先读 cookie，回退读 `X-Guest-Token` header。两者都指向 `Customer.card_token`。
- 每次 `/api/guest/card/` 命中时刷新 cookie `Max-Age`（滚动续期）+ 更新 `Customer.last_seen_at`。
- 同源部署（nginx 反代 `/api/`），cookie 能带上。**本地开发**：前端 5173 / 后端 8000 跨端口，cookie 的 `Secure` + 跨站会有问题——本地用 `X-Guest-Token` header 那条路，或本地放宽 cookie 属性（`config/settings.py` 已有 `SESSION_COOKIE_SECURE` 等 env 开关的先例，加一个 `GUEST_COOKIE_SECURE`）。

### 4.8 `reward_config` JSON 结构（阶段 2 才用，先定形状）
```
cash_voucher:  { face_yen: int, min_spend_yen: int }
chef_special:  { label: str, menu_value_cap_yen: int }
drink/dessert/side_dish: { label: str }
points_refund: { points: int }
```
- `Prize.reward_type` 决定 `reward_config` 的 schema；serializer 里按 type 校验。

---

## 5. 阶段 0 配置默认值（seed / 初始 Campaign 用）

见 `打卡与抽奖实施方案.md` §18。关键项：

| 项 | 默认值 |
|---|---|
| 赚积分 | ¥1,000 → 10 分 |
| 积分换抽奖 | 100 分 / 次（阶段 2.5） |
| 积分换券 | 100 分 → ¥100（阶段 2.5） |
| 里程碑 | 累计 300 / 800 / 2500 分（阶段 2.5） |
| 集章目标 | 5 次（可关） |
| 积分过期 | 末次活动 + 12 个月（阶段 2.5 定时任务） |
| 营业日切换 | 05:00 |
| 客人记录保留 | 末次到店 + 2 年（阶段 3 定时清理） |
| 每人每日抽奖上限 | 10（阶段 2.5） |
| 共享缓存 | DB 缓存表 |

奖池权重表（阶段 2）见 §6。

---

## 6. 域名 / HTTPS

用户会申请**域名 + 证书**。上线前需要：

- `store-admin-backend/.env`（生产）：`SECURE_SSL_REDIRECT=True` `SESSION_COOKIE_SECURE=True` `CSRF_COOKIE_SECURE=True` `SECURE_HSTS_SECONDS=31536000` `ALLOWED_HOSTS=<域名>` `CORS_ALLOWED_ORIGINS=https://<域名>`（若同源可不需要）
- 新增 `GUEST_COOKIE_SECURE=True`（本文档 §4.7）
- nginx 加证书（宝塔面板反代层或容器内，看用户部署方式）
- 前端 `.env.production`：`VITE_API_BASE_URL` 指向 `https://<域名>/api` 或留空走同源
- 店内二维码贴纸里的 URL 用正式域名后再印刷

**本地开发不阻塞**：用 `X-Guest-Token` header 路径 + 放宽的 cookie 属性即可全流程联调。

---

## 7. 阶段 1 验收标准

**后端**
- [ ] `promotions` app 接入，`python manage.py test promotions` 全绿
- [ ] `python manage.py check` 无新增 warning（注意 MySQL 的 `UniqueConstraint condition` W036）
- [ ] `CACHES` 配好，`createcachetable` 有落地方式
- [ ] 公开接口不接受 `amount_yen` / `points_granted` 等；`consent != true` 被拒
- [ ] 店员确认一次消费 → 积分按 `amount_yen // 1000 * rate` 入账 + 一条 `PointsLedger` + 一条 `CheckInRecord`（同营业日不重复）
- [ ] `SpendVerification` 普通 PATCH / DELETE 被拒；`void` 反向流水 + 扣回余额正确
- [ ] 跨租户隔离测试通过；`staff` / `branch` 权限边界测试通过
- [ ] `Customer` 按 `(org, phone)` 唯一；`normalize_phone` 有测试

**前端**
- [ ] `npm run build`（含 `type-check`）通过
- [ ] 扫店内码 → 新客人登记 → 拿到卡片页 + 二维码渲染
- [ ] 老客人（浏览器有 token）扫店内码直接进卡片页
- [ ] 只读登录（手机 + 生日）能看卡、不能改
- [ ] 店员平板页：输入 card_token + 金额 → 确认 → 回显积分，输入框自动回焦
- [ ] 管理后台：活动 CRUD、客人列表 / 详情（流水）、删除、调分
- [ ] 客人页面日文文案齐全；管理端中日双语

**演示**
- [ ] `seed_promotions_demo` 后能端到端走一遍：登记 → 店员确认 → 卡片页看到积分

---

## 8. 后续阶段（简述，本次不做）

- **阶段 2**：`Prize`（分档，含 chef_special）/ `Voucher` / `LotteryDraw` 模型；后台奖品 CRUD；服务端加权抽奖（`secrets` + `select_for_update` 锁库存 + 权重快照 + 幂等 `request_id`）；券核销页（店员）；封顶顶奖 + 每日库存 + 使用门槛。奖池默认见 §6 / 方案 §6。
- **阶段 2.5**：`/api/guest/redeem/`（积分 → 抽奖 / ¥100 券）；里程碑发放；积分过期定时任务；**拿阶段 1–2 真实核销数据校准奖池权重让"一抽 EV ≈ ¥100"**；可选双轨（当次消费直接送 1 抽）。
- **阶段 3**：共享缓存限流（DRF throttle / django-ratelimit）；`RiskEvent` + 规则引擎（方案 §13 表）；风险后台；抽查报表 / 店员操作统计 / 积分出货月报；`staff` 账号级"可确认"开关；客人记录保留期清理任务。
- **阶段 4**：平板金额档位按钮；退款联动；生日券自动发放；Wallet 卡片；收款端 API 对接（若将来 POS 能开）。

---

## 9. 关键参考文件清单（开工前速览）

| 要点 | 看这个 |
|---|---|
| app 结构 / ViewSet / service / 分页 | `store-admin-backend/purchasing/` `inventory/` |
| 事务 + 行锁 + 账本 | `inventory/services.py` `inventory/models.py`（`StockTransaction`） |
| 追加历史 / who-when 不信客户端 | `dailyreports/models.py`（`DailyReportHistory`） |
| 权限工具 / 多租户 mixin | `common/permissions.py` |
| staff opt-in / 分角色 queryset | `scheduling/views.py` |
| 审计字段 / void action | `scheduling/views.py`（`ActualWorkRecordViewSet`） |
| 测试 fixture | `common/test_utils.py`；`inventory/tests.py` `organizations/tests.py` |
| MySQL/SQLite 约束差异 | `inventory/serializers.py`（`validate_jan_code`） |
| 前端 api 模块模式 | `store-admin-frontend/src/api/inventory.ts` |
| 前端 HTTP / 401 refresh | `src/api/http.ts` |
| 路由 / 角色门 / public | `src/router/index.ts` |
| 扫码枪 keyboard-wedge 处理 | `src/views/PurchasingView.vue`；`inventory` 的 `lookup` action |
| 分页表格 UI | `src/views/PurchasingView.vue` |
| i18n | `src/i18n/locales/{zh,ja}.ts` |
| 部署 | `docker-compose.yml` `store-admin-frontend/nginx.conf` `store-admin-backend/README.md` |
