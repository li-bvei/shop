# 当前项目状态

## 仓库基线

- 当前生产代码版本：`a293455 ui: show branch name instead of internal id`（2026-09-18 已部署）；GitHub 在其后可能仅有文档提交。
- 上一个重要提交：`b5c700c`（积分抽奖返还流水余额修复，P1-07）→ `4bc23df`（仕入先管理 PDF 导出重排）→ `829e531`（仕入先管理按月筛选 + 前端新版本检测）→ `c58287c`（旧日报锁定）→ `1453cc5`（收银机零钱默认数量 + レジ固定金額可改）→ `1fc5fa1`（批量替换空字符串/日期校验 bug 修复）→ `960bbac`（进货批量替换重构为多条件组合 + 2026注文書 数据核对）。
- 再往前：`34eee9e`（进货性能/数据修复、日报离线保存、平台租户管理批次）。
- 再往前的历史基线：`ec54c2d docs: 2026-09-06 batch — ops fixes, org feature gates, platform console, check-in tiers`。
- 工作区已知未跟踪：`store-admin-frontend/.claude/`。本次不处理。
- `docs/ai-handoff/05_TESTS_AND_RISKS.md` 是 2026-09-14 一次独立审计留下的记录，审计范围覆盖到 `960bbac`；其中 P1-01（批量替换空字符串/日期校验）和 P1-08（reconcile 命令事务边界）已在 `1fc5fa1` 修复，其余条目仍待处理，见该文件本身。
- **本文档撰写之后（2026-09-19 ～ 09-22）还有几轮未在本文件其余章节回填的改动**（手机端响应式布局、供应商聚合加载改用后端已有字段、支付方式改成软删除、月度经营新增年度切换与 PDF、日报 PDF 重做）——这些改动现已进入 Git 版本管理；下面单独列一节说明日报 PDF，其余批次尚未完整回填，接手前建议同时查看 `git log`，不要只依赖本文档。

## 2026-09-25 手机端易用性与积分抽奖体验优化（已实现，未提交/未部署）

- **原则**：≤768px 才启用手机专用组件（`composables/useIsMobile.ts`，matchMedia），桌面代码路径不动；业务公式/抽奖结果不改，手机与桌面共用同一批计算函数。
- **A 底部导航**：`components/mobile/MobileBottomNav.vue`（ホーム/経営/日報/仕入れ/その他，その他 = `MobileSheet.vue` 底部抽屉）。菜单项与权限/功能开关过滤抽到 `composables/useNavItems.ts`，`AppSidebar.vue` 与底部导航共用同一份，未授权项不出现。`AppShell.vue` 提供 `--mobile-nav-h`；手机顶栏隐藏原汉堡按钮（导航已在底部）。`index.html` viewport 加 `viewport-fit=cover` 适配 safe-area。
- **B 日报手机表单**：`components/mobile/DailyReportMobileForm.vue`（5 步：基本/支払/レジ/経費/確認，固定 前へ/次へ/保存 栏；输入 ≥52px、字号 ≥16px、数字 ≥18px、レジ枚数 −/数字/+）。`DailyReportView.vue` 在手机上切换到它，Excel/PDF/离线草稿/冲突处理/旧日报锁定原样复用。`DailyReportForm.vue` 的普通 `<script>` 新增导出 `computeCashRegisterStatus` / `visiblePaymentMethodsFor` / `syncPaymentAmountKeysOn`，桌面表单也委托给它们，避免手机端复制公式。
- **C 仕入れ手机录入**：`components/mobile/PurchasingMobileEntry.vue` + `PurchaseEntryFields.vue`（竖向单品录入、保存并继续、记住上次日期/仕入先、历史卡片、底部抽屉编辑、「絞り込み」抽屉）；共用逻辑在 `utils/purchaseEntry.ts`，`PurchasingView.vue` 在桌面仍走原表格。
- **D 顾客卡（GuestCardView/GuestOnboarding）**：功能性 Emoji 全部换成 `@element-plus/icons-vue`（图标 24px、导航文字 ≥12px、按钮 ≥52px/交換 48px）；配色改白/浅灰/品牌绿，抽奖红仅作强调；语言切换按钮 48px。
- **E 抽奖转盘**：`WheelOfFortune.vue` 改用固定版本 `spin-wheel@5.0.2`（`spinToItem` 落到后端返回的奖品）+ `canvas-confetti@1.9.4`（`disableForReducedMotion`）；音效用 WebAudio 合成（默认关，`localStorage pc_wheel_sound`），无外部音频/动画素材。**后端 `_draw_result_body` 现在返回 `prize_id`，前端按 `prizeId` 落点，绝不按奖品名匹配、绝不在前端随机**；奖品加载失败/为空时禁用抽奖并给「もう一度読み込む」；积分返还是转盘上的独立浅绿色段；抽到的 id 不在当前转盘上时重新拉取一次奖品，仍不在则只展示结果不转。转盘上的文字最多 8 字（其余省略），完整名称在结果卡片里。`/api/guest/prizes/` 仍不返回权重。
- **文案**：新增文字全部在 `ja.ts` / `zh.ts`（`nav.tab*`、`dailyReport.m*`、`purchasing.m*`、`guest.wheel*`）。
- **验证**：`npm run type-check`、eslint、`npm run build` 全绿；后端 `promotions dashboard dailyreports paymentmethods purchasing` 255 项通过（`promotions.tests` 新增断言：抽奖结果 `prize_id` 必在 `/api/guest/prizes/` 里）。浏览器实测 320/375/390/430 无横向滚动、≥48px 点击区（日报/仕入れ/顾客卡）、日报/仕入れ主体文字 ≥16px、256px 布局宽（≈200% 缩放）保存栏仍可点、暗色模式；真实抽奖一次，后端 prize_id=60（积分返还）与转盘停靠段一致；奖品接口 500 时显示重试并可恢复。
- **独立复查后追加修复**：`/api/guest/prizes/` 不再列出 `weight=0`（已停用、永远抽不中）的奖品；转盘构建失败时禁用抽奖（`ready`），卸载时结算挂起的 Promise 并 `confetti.reset()`；手机日报点主 保存 时会先保存レジ设置里改过的默认枚数/应有金额；仕入れ手机筛选加请求序号防旧响应覆盖、加载更多失败回退页码、清空月份时同步清价格变动、两处筛选标签名修正；「その他」抽屉点当前页面也会关闭；手机端说明文字统一 ≥16px。
- **部署**：无新 migration，`cd /www/wwwroot/shop && bash deploy.sh` 即可。

## 2026-09-22 日报 PDF 下载改为离屏打印稿（已实现，待部署）

- **问题**：`DailyReportView.vue` 原来的"下载PDF"（`downloadLiveElementAsPdf`）是对屏幕上正在编辑的 `DailyReportForm` 实时截图（html2canvas）再塞进单页 jsPDF。这个做法两个反复出现的问题：① 依赖当前页面的亮/暗主题 CSS 变量，深色模式下禁用输入框的暗色文字画在暗色背景上，看起来像"黑色的不可选中框"；② 表单本身是给屏幕编辑用的高度，硬缩成一页会让字变得很小。
- **修复**：改成跟 `SuppliersView.vue`/`MonthlyAnalysisView.vue` 一样的模式——不再截图，`DailyReportView.vue` 内部新增 `buildDailyReportPdf()`，用 `pdfExport.ts` 新导出的 `el()` DOM 构建小工具 + 原生内联样式（白底黑字灰边框，不引用任何 `--*` 主题变量、不含 Element Plus 组件）拼一份专用的紧凑排版，再走已有的 `renderOffscreenToPdf`（内部仍是 html2canvas + jsPDF，单页等比缩小兜底逻辑未改）。因为版式本身就比屏幕编辑表单紧凑得多，正常一天的数据实测在不缩放的情况下就能装进一页（约 760px 高，A4 可用高度约 1030px），字号保持设计时的大小（核心数字 24px、表格正文约 12–14px），全部加粗。
- **数据一致性**：新增导出 `cashRegisterDenominationBreakdown()`（`DailyReportForm.vue`）把"某面额的数量/默认数量/小计"收敛成一处公式，屏幕上的行小计、`computeCashRegisterTotal`、PDF 三处共用，不会出现 PDF 数量和小计对不上的情况；PDF 的"数量"列在有默认数量叠加时会用"(当天+默认)"的小字标注，不会只显示当天数量却让小计悄悄含了默认值。点击下载会重新 `fetchPaymentMethods`/`fetchCashRegisterDefaults` 取最新值，不用页面加载时缓存的旧数据（刚改完支付方式名字/新增删除/收银机默认数量或固定金额，立即下载都是对的）；表单当前未保存内容（含离线草稿）仍按屏幕当前内容导出。
- **清理**：确认 `downloadLiveElementAsPdf` 和 `.pdf-export-mode`（`global.css`/`variables.css`/`DailyReportForm.vue` 三处）都已无其他调用方后整体删除，浏览器"打印/导出"按钮的 `usePrintFit` 行为未受影响。
- **验证**：`npm run type-check`（`vue-tsc --build`）、`npm run build`、`eslint` 全绿；后端 `dashboard`/`purchasing`/`dailyreports`/`paymentmethods` 四个 app 测试套件 107 项全过（本轮未改后端代码）。真实浏览器验证了：深色模式下 PDF 仍是白底黑字；0 条报销和多条超长文本报销都正常；2026-09-15 前后两种日报的默认数量叠加逻辑分别正确；改完收银机固定金额/默认数量、改完支付方式名字后不刷新页面立即下载都拿到最新值；已停用但当天有金额的支付方式保留显示、金额为 0 的非现金方式隐藏。顺带发现并修了两处 `npm run build` 才会暴露的类型错误（`api/suppliers.ts` 的 create/update 参数类型误把服务端计算字段 `monthlyPayable` 也当成必填入参；`MonthlyAnalysisView.vue` 支付方式图 label formatter 参数类型跟 ECharts 实际类型不匹配），不影响运行时行为。
- **2026-09-22 追加**：PDF 页头日期带随当前语言变化的星期（中文“星期二”、日文“火曜日”，文件名不变）；收银机区读取前一自然日的日报/本地草稿，把当前累计差额拆成“前日遗留差额”和“本日新增差额”（本日新增 = 当前差额 - 前日遗留），避免前日短款延续到今日时被误认为今日新短款。前一日没有数据时明确显示无法判定，不按 0 猜测。

## 2026-09-13 ～ 09-15 这一批做了什么

### 进货管理（purchasing）
- 月度合计改成数据库端聚合（`month_total` action），不再靠前端翻页汇总，解决筛选/翻页数秒延迟。
- 修复同日多条记录排序丢失 `-id` 兜底排序的问题。
- **数据完整性 bug**：`import_purchases_2026` 用 `bulk_create()` 导入的历史数据从未走过 `save()`，导致 `item_name_normalized` 长期为空——影响了全库 5070 条进货记录里的 5030 条（99%），价格履历/供应商比价/涨跌对比对这些记录一直是坏的。已用 `backfill_item_name_normalized` 命令修复并在生产执行。
- 价格履历：行内提示改为对比"上次进货"（原来是"上月均价"，价格相同时也不再显示）；历史抽屉默认只显示上月+本月，加"显示全部历史"开关。
- 新增品目联想框"新商品将保存"提示；IME 回车误提交加固 + 数量/单价必填校验。
- 批量替换（bulk_replace）：从"只能单选日期或供应商"重构为多条件组合查找（日期/日期范围/供应商/品目关键词任意组合），替换目标为日期和/或供应商，预览确认后才写入。**2026-09-15 又修了两处 bug**（见下）。
- 新增 `reconcile_purchases_2026` 一次性命令：把用户提供的 `2026注文書.xlsm`（Jan–Sep 11，4713 行）与生产库现有记录做多重集对比，只插入真正缺失的记录，数量/单价按数据库实际精度（2 位/0 位小数）取整后再比较，避免把已存在的小数公斤商品误判成"缺失"而重复录入。`2026-09-13` 整天从比对源头排除，绝不触碰。已在生产执行：插入 453 条（¥1,224,872.50），新建供应商"啓真社"，验证幂等（复跑显示 0 条）且 9/13 数据逐字节未变。
- 2026-09-15 修复：批量替换的品目关键词全是空格时会归一化成空字符串，`icontains=''` 匹配范围内全部记录而不是报错；日期字段原来没有提前校验，非法值可能在查询求值时才抛出未捕获异常。reconcile 命令的新建供应商原来在事务外，现改到同一个 `transaction.atomic()` 里。

### 仕入先管理（SuppliersView.vue）
- 按月筛选与手动金额：手动覆盖值已从 `Supplier.payable_override` 的单一全局字段改为 `SupplierMonthlyPayableOverride`，按“供应商＋分店＋月份”独立保存，因此上月等历史月份也可手动修改，不会串到其它月份或其它分店。手动状态显示恢复按钮，点击后删除该月覆盖值，立即恢复按进货记录自动合计。migration 0008 会把旧字段中已有的 2026-09 覆盖值复制给机构内各分店以保留旧数据。
- 梅田店仕入品目种子：migration 0008 新增 `PurchaseItemSeed`（只用于联想，不参与金额合计）；`seed_purchase_catalog --source shinsaibashi --target umeda` 从心斋桥现有交易提取每个供应商/品目的最近名称与单价，幂等写入梅田店。命令不会复制或创建 `PurchaseRecord`，避免把心斋桥实际成本误记到梅田店。
- **生产执行记录（2026-09-17）**：在 `/www/wwwroot/shop` 运行 `bash deploy.sh`，migration `purchasing.0008` 成功应用，容器重建及 `manage.py check` 通过。随后正式运行梅田品目种子命令，写入 540 项；再次以 `--dry-run` 复核结果为 `0 create, 0 update`，确认可重复执行且没有重复数据。
- 确认 `Supplier` 是仕入先管理和仕入管理（purchasing）共用的同一张表（`purchasing.Supplier`，按 organization 隔离），后端不存在重复模型或数据不同步的问题；若前端看不到新增的供应商，是某个已打开页面没有重新拉取列表，切换页面/刷新即可。
- PDF 导出（`handleDownload`）调整：标题改成"{年}年{月}月材料費"（跟着页头选择的月份走）；去掉カテゴリー列（仅 PDF，页面表格和编辑表单里的カテゴリー字段没动）；当月未払金为 ¥0 的供应商不出现在 PDF 里；各单元格 `white-space: nowrap` + 超长省略号截断，尽量不在格子内换行。振込先口座这一格排版：第一行（小字灰色，类似注音）是**银行名自己的假名**（`bankNameFurigana`），第二行是"银行名 + 户主假名"（`accountHolderFurigana` 跟在银行名后面，不是叠在上面——2026-09-16 改的，之前搞反了把户主假名放去银行名上面），第三行是支店名/口座种类/口座番号。
- 新增供应商表单：口座種類（账户种类）从自由文本改成固定选项的下拉选择（`ACCOUNT_TYPE_OPTIONS = ['普通', '当座', '貯蓄']`），仍是选填（可留空），后端字段本身还是普通 `CharField` 没加数据库级约束。

### 日报（dailyreports）
- 报销明细：金额/品目输入框在浏览器缩放/窄屏下会挤成不可读的窄条，改成有底线宽度 + 超出自动换行；删除按钮固定尺寸不再跟着缩小。
- 报销联想词不再自动带出金额（报销金额基本不会重复）。
- 打印接入 `usePrintFit` 自动缩放单页 A4；支付方式明细里金额为 0 的行打印时自动隐藏（屏幕上照常显示）。
- 新增离线保存：保存时遇到网络故障会把内容存本地草稿，联网后自动同步；如果云端同时有更新的保存（比如换设备保存过），会弹出来让用户选用哪一份，不会静默覆盖。

- 新增"収银机现有金额"零钱默认数量：500/100/50/10/5 五档面额可按分店设置一个默认枚数（后端 `CashRegisterDefaults` 模型，一分店一条记录，`denomination_defaults` JSON 字段）。**不会**预填进"枚数"输入框——枚数始终是当天实际数出来的数量，默认值只在计算小計/合计时自动加算（`computeCashRegisterTotal`/`cashRegisterRowSubtotal`），且**无条件**加算（哪怕"枚数"完全没填，小計也会按 0+默认值算出来，不需要先输入 0 才生效——这是为了不用每天重新数备用金）。加了硬编码日期线 `CASH_REGISTER_DEFAULTS_CUTOFF_DATE='2026-09-15'` 做唯一的兼容边界：日报日期早于这条线的，默认值完全不生效（小計就是纯粹的 枚数×面额），且デフォルト枚数这一列在旧日报页面直接不显示，不会显示"看似生效实则无效"的数字造成误解；日期在这条线（含）之后的日报才会显示这一列并参与计算。同一处レジ固定金額（原来硬编码 ¥130,000）可编辑，编辑后同样只影响新报表和 Excel 导出，不受这条日期线限制。仅主日报表单开放编辑默认值（`allow-cash-register-default-edits` prop），历史记录编辑弹窗保持只读展示，但两处都按同一套日期线计算小計。
- 新增日报锁定：超过一天（按日报自己的业务日期，不是保存时间）的日报默认变为只读，需要输入分店/admin 共用的一个"解锁密码"才能编辑，解锁只在当前这次编辑会话有效（刷新页面/切换日期会重新锁定）。密码是企业级共享密钥，在"设置"页由 admin 设置/修改/关闭（`Organization.report_unlock_password_hash`，`django.contrib.auth.hashers` 加密存储，从不回传明文或哈希本身）；**没有设置密码的企业，这个功能完全不生效**，所有日报和之前一样可以直接编辑，保证老租户不会被动升级到新限制。解锁流程：前端弹密码框 → `POST /api/daily-reports-unlock/` 校验密码（按账号限流，10分钟内错 5 次会被暂时拒绝）→ 成功返回一个 30 分钟有效期的签名 token（`django.core.signing.TimestampSigner`，无服务端会话状态）→ 之后对该锁定日期的 `POST`/`PATCH /api/daily-reports/` 请求带上 `X-Report-Unlock-Token` 头才会放行，否则一律 403。主日报表单和"编辑历史版本"弹窗各自独立锁定/解锁（可能同时看着两个不同日期）。前端用 `<el-form :disabled="readonly">` 整体禁用表单所有输入框，不是逐个字段加 disabled。

### 首页 / 全局
- 经营看板问候语按时间段变化（早上好/下午好/晚上好/辛苦了），不再固定写死"早上好"。
- 全局屏蔽鼠标滚轮改动数字输入框的值（焦点在 number 输入框上滚动会自动失焦，不再误改）。
- 顶栏分店标签直接使用 `/api/auth/me/` 返回的 `branchNameZh` / `branchNameJa`，不再在分店列表异步加载前把内部 ID（例如 `shinsaibashi`）显示给用户。

### 部署 / 前端版本检测
- 新增"新版本检测"：`store-admin-frontend/Dockerfile` 在 `npm run build-only` 之前把当前时间戳写进 `public/version.txt`（Vite 会原样复制到构建产物根目录，未加 hash，随 `index.html` 一样按 `nginx.conf` 的 `no-cache` 规则served），前端 `src/utils/versionCheck.ts` 每 5 分钟 + 每次标签页切回前台时用 `cache:'no-store'` 请求这个文件，和当前标签页加载时的版本号不一致就在 `App.vue` 弹一个固定在底部的提示条（"系统已更新，刷新后可使用最新功能" + 按钮），点按钮才 `location.reload()`——不做静默强刷，避免正在填的日报之类表单数据被自动刷没。仅在生产构建生效（`import.meta.env.PROD` 门控），本地 `npm run dev` 不受影响。
- **已知限制**：这只解决"本仓库内 nginx 层"的缓存问题（其实这层本来就配对了：`index.html` no-cache、`/assets/` 带 hash 长期不可变缓存）。生产实际访问先经过宝塔面板自己的外层 Nginx（负责域名+SSL），那一层的缓存/CDN 配置不在这个代码仓库里，也没有核实过——如果部署后仍然需要用户手动强刷才能看到新版本提示条本身，说明外层代理把 `index.html`（或整个页面）缓存住了，需要去宝塔那边检查，不是这次改的代码能覆盖的范围。

### 权限与平台管理
- **权限漏洞修复**：平台超级管理员（`is_superuser=True`）账号如果和某个企业共用 Organization，之前会出现在该企业自己 Settings 的账号列表里，可以被该企业管理员重置密码/删除。已在 `UserViewSet` 和平台级账号接口都加上 `is_superuser=False` 过滤。
- 新增 `Organization.active` 真正生效：停用后该企业全部账号登录直接拒绝（新增 `OrganizationScopedTokenObtainPairSerializer` + `OrganizationScopedJWTAuthentication`），已登录的 token 在停用后的下一次请求也会立刻失效，和账号停用的即时性一致。之前这个字段只是存着、界面显示，从未被检查。
- 平台"运营管理"页新增：跨企业账号增/改/重置密码/删除，跨企业分店增/改/删除，"新建企业"一步创建组织+第一家分店+第一个管理员账号（替代原来只能用命令行 `provision_organization`）。
- **密码强度统一 + 登录限流**（05_TESTS_AND_RISKS.md P1-05）：新增 `accounts/services.py` `validate_new_password()`，所有设置密码的入口（账号创建、自助改密、管理员重置、平台跨企业创建/重置、`provision_organization`）统一改为调用 Django `AUTH_PASSWORD_VALIDATORS`（长度 6→10，加常见密码库/纯数字/与账号名过于相似校验），不再各处各写一份 `len(password) < 6`。`/api/token/` 登录端点新增 `accounts/throttling.py`：IP 维度 30/min + 账号维度 8/min 双重限流，复用 `promotions` 已有的 DB-cache 限流模式。顺带修了几处前端"服务端拒绝了弱密码，但界面完全没反应"的静默失败（`SettingsView.vue`、`platform/PlatformFeaturesView.vue` 的账号创建/改密/重置密码/新建企业）。
- **积分流水余额语义修复**（05_TESTS_AND_RISKS.md P1-07）：`promotions/services.py` `draw_lottery` 中奖"积分返还"奖品时，原来先扣分再加返还金额，两条 `PointsLedger` 流水的 `balance_after` 都写成了最终余额；现在扣分后先快照 `balance_after` 再应用返还，扣分流水记录的是返还前的中间余额。最终余额本来就是对的，这个 bug 只影响逐笔流水回看时的运行余额。新增测试断言两条流水各自的 `balance_after`，不再只断言 `sum(delta) == balance`。

## 需要接手者确认的事项

- 生产服务器是否确实已运行当前 HEAD；以服务器 `git rev-parse HEAD` 为准。**`1fc5fa1` 的 bug 修复截至本文撰写时尚未部署**，生产仍在跑有 bug 的 `960bbac`（批量替换空字符串问题），应尽快 `bash deploy.sh`。
- `docs/ai-handoff/05_TESTS_AND_RISKS.md` 里 P1-02（进货负数/金额精度口径，需业务负责人核对原始单据）、P1-03（JAN 并发唯一性）、P1-04（部署脚本 `reset --hard`/回滚）、P1-06（生产安全配置现场核实）仍未处理；P1-05（密码强度/登录限流）和 P1-07（积分流水语义）已在本次会话修复，见上文"权限与平台管理"小节。
- 生产平台超级管理员的用户名、密码和组织归属必须由运营者确认，不要从文档猜密码。
- 正式域名、HTTPS、真实 `SECRET_KEY`、安全 Cookie、HSTS 和 `DEBUG=False`。
- 旧 `lottery` 是历史名单/导入模块；新积分营销逻辑在 `promotions`，不要混用模型。
- 宝塔面板外层 Nginx（域名+SSL 那一层）的缓存/CDN 配置没有核实过，不在这个代码仓库里；如果部署后新版本检测提示条本身也要强刷才出现，问题在那一层，需要运营者去后台检查。
