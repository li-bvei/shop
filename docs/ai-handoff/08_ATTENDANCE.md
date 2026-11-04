# 员工出勤（打卡）模块

最后整理：2026-11-03

本文件描述「上下班打卡 + 补卡申请 + 变更审计」这一层的设计、选型依据、迁移方式和边界。
源码和 Git 为准；本文件描述的是 `scheduling` app 新增的三个模型与其 API。

---

## 1. 这一层解决什么问题

在本次改动之前，系统只有「排班 → 店长手工确认实际出勤 → 工资计算」这条链路。
`ActualWorkRecordViewSet` 的 docstring 当时明确写着：

> this system has no time-clock hardware, so actual times only ever come from
> a manager's confirmation, never the employee's own submission

本次改动新增的是这条链路**下面**的一层：员工本人的打卡记录。
**没有删除、没有替换任何既有流程**，排班、手工录入、确认、锁定、工资计算全部保持原样。

---

## 2. 核心不变量（最重要的一段）

> **打卡是证据（evidence），店长确认是权限（authority）。**

- 任何由打卡或补卡申请产生的 `ActualWorkRecord`，状态一律是 `pending`。
- `wages/calculation.py` 只读取 `status in (manager_confirmed, admin_locked)` 且 `absent=False` 的记录。
- 因此**员工无法通过打卡改变自己的工资**，工资计算的输入契约与改动前完全一致。

由此派生出三条在 `scheduling/attendance.py` 中强制执行的规则：

| 规则 | 原因 |
|---|---|
| `admin_locked` 的日期永不被自动重写 | 该日可能属于已结算的工资月；迟到的打卡仍会被存下来（它是证据），但不改写记录 |
| `manager_confirmed` 的日期也不被自动重写 | 否则后到的打卡会覆盖人的判断。**例外**（2026-11-03）：按排班自动生成、还没有人动过的记录（`source='plan'` 且 `adjustment_reason` 为空）只是排班的副本，不是人的判断，员工打卡会替换它并回到 `pending`，见 [09_SCHEDULING.md](09_SCHEDULING.md) 第 4 节 |
| 每一次写入都与 `attendance.log_change()` 成对出现，且在同一事务内 | 出勤是工资输入，「谁、何时、从什么改成什么、为什么」必须比这次修改活得更久 |

对应测试：`scheduling/tests_attendance.py::PayrollSafetyTests`（7 个用例）。

> **第三条的调用点**（本项目没有、也不需要一个统一的 `_write_record` 包装函数；
> 审计是在每个写入路径上显式调用 `log_change()`）：
> `attendance.rebuild_from_punches`（打卡）、`attendance.apply_correction`（补卡生效）、
> `ActualWorkRecordViewSet` 的 `perform_create` / `perform_update` / `perform_destroy` /
> `bulk_confirm` / `lock` / `unlock`（店长录入与状态变更）、
> `SchedulePeriodViewSet.generate_actual_records`（排班生成，`source=generated`）、
> `ShiftViewSet` 的 `perform_update` / `perform_destroy` 经 `attendance.sync_plan_record` /
> `attendance.discard_plan_record`（排班改时间或删除时同步自动生成的记录，`source=generated`，2026-11-03 新增）。
> 已核对：这是当前代码里全部会创建或修改 `ActualWorkRecord` 的路径。

---

## 3. GitHub 选型与依据

两个候选方案都**实际访问并读取了仓库和数据模型**（2026-11-01 核实）：

### 候选 A：Horilla HRMS
- 仓库：<https://github.com/horilla-opensource/horilla>（实际跳转至 `horilla/horilla-hr`）
- **许可证：LGPL-2.1**
- 维护状态：**活跃**。默认分支 `2.0`，最近提交 2026-10-30（2 天前），6,581 commits，1.5k star，964 fork，119 open issues
- 技术栈：Django（与本项目同栈，可比性最高）
- 数据模型（`attendance/models.py`）：
  - `AttendanceActivity`：原始打卡，**一行存一对** in/out（`clock_in_date`+`clock_in` / `clock_out_date`+`clock_out`）
  - `Attendance`：每日汇总，`unique_together = ("employee_id", "attendance_date")`
  - `AttendanceLateComeEarlyOut`：迟到/早退**单独一行**，`type` 为 `late_come`/`early_out`，**不含分钟数**
  - `GraceTime`：容差配置
  - 补卡申请：**字段直接挂在 `Attendance` 行上**（`is_validate_request`、`is_validate_request_approved`、`request_type`、`requested_data` JSON）
  - 无休息时间模型

### 候选 B：Frappe HR
- 仓库：<https://github.com/frappe/hrms>
- **许可证：GPL-3.0**
- 维护状态：**活跃**。11,436 commits，9.0k star，2.9k fork；doctype 定义文件 `modified` 日期为 2026-10（`employee_checkin` 为 2026-10-19）
- 技术栈：Frappe 框架（自有 ORM，非 Django）
- 数据模型（doctype JSON）：
  - `Employee Checkin`：**一行一次打卡**，`log_type` 为 `IN`/`OUT`，`time` 为 Datetime，`attendance` 反向链接到当日 Attendance
  - `Attendance`：`status` 枚举（Present/Absent/On Leave/Half Day/Work From Home）、`working_hours` Float、`late_entry`/`early_exit` **布尔值**、`in_time`/`out_time`
  - `Shift Type`：策略集中于此 —— `late_entry_grace_period`、`early_exit_grace_period`、`begin_check_in_before_shift_start_time`、`allow_check_out_after_shift_end_time`、`determine_check_in_and_check_out`、`working_hours_threshold_for_absent`/`_half_day`
  - `Attendance Request`：**独立 doctype**，走 Frappe 的 submit/cancel/amend
  - **跨午夜：Shift Type 没有单独的跨日字段，按 `end_time` 早于 `start_time` 推断为夜班**（2026-11-03 重读 [shift-type 文档](https://docs.frappe.io/hr/shift-type.md) 更正；此前这里误写为「没有跨日概念」）

### 结论与采纳方式

**两者均为 copyleft（LGPL-2.1 / GPL-3.0），与本项目的闭源 SaaS 不兼容。
因此：不复制任何代码、不引入任何依赖，只借鉴设计（模型结构与工作流，不受著作权保护）。**

| 决策 | 依据 |
|---|---|
| **打卡层 + 每日汇总层两层结构** | 两个方案一致采用。本项目的 `ActualWorkRecord` 已经就是每日汇总层（`unique(employee, work_date)` 与两者的 key 相同），**所以只需补上打卡层**，工资链路零改动 |
| **一次打卡一行、带 `kind`**（采纳 Frappe 形状） | Horilla 的「一行存一对」会让「忘记下班打卡」变成 UPDATE 既有行，其 `duration()` 甚至在**读取时**把 `clock_out` 回填为 `now`。作为工资输入，这个形状不可接受。append-only 才能审计与重放 |
| **迟到/早退存分钟数**（优于两者） | Frappe 只有布尔 `late_entry`/`early_exit`，Horilla 的单独行连时长都没有。但「迟到 3 分钟」和「迟到 90 分钟」是两回事，布尔值无法区分 |
| **补卡申请独立建模**（采纳 Frappe 形状） | Horilla 把请求状态糊在出勤行上，导致同一天只能有一个在途申请、且没有历史；独立模型可留全量「谁申请了什么、谁批的」 |
| **显式休息打卡 + 营业日切换时刻** | Horilla 完全没有休息概念，Frappe 靠打卡交替推断。但本项目的工资引擎**已经**扣减 `actual_break_minutes`，排班**已经**带休息分钟，推断会与既有数据矛盾。打卡归属哪一天则采纳 Horilla 的「日期与营业日分离」：Frappe 只在班次定义上按时间推断夜班，打卡的归属靠班次前后的打卡窗口，本项目没有采用打卡窗口 |

---

## 4. 数据模型

### 新增模型（`scheduling/models.py`）

**`AttendancePunch`** —— 一次打卡事件，append-only
- `employee` / `branch` / `work_date`（营业日，非日历日）
- `kind`：`clock_in` / `clock_out` / `break_start` / `break_end`
- `punched_at`：**永远是服务器时间**，绝不接受客户端时间戳（手机时钟可能错误或被故意修改）
- `source`：`self`（本人）/ `manager`（店长代打）
- API **只有 create / list / retrieve**，没有 update、没有 delete，任何角色都没有

**`AttendanceCorrectionRequest`** —— 补卡/更正申请
- 申请内容：`requested_start` / `requested_end` / `requested_break_minutes` / `requested_crosses_midnight` / `requested_absent`
- `reason` **必填**
- `status`：`pending` / `approved` / `rejected` / `withdrawn`，含 `decided_by` / `decided_at` / `decision_note`
- 「同一员工同一天只能有一个 pending」在 `AttendanceCorrectionRequestViewSet.perform_create` 中校验，**不是数据库约束** —— MySQL 会静默丢弃条件唯一索引的条件（Django `models.W036`，`inventory.Product` 已有同样的警告），放在数据库会给人虚假的安全感

**`AttendanceChangeLog`** —— append-only 审计
- `before` / `after` 为 JSON 快照，只含出勤相关字段
- `employee` / `branch` / `work_date` 冗余存储，`record` 为 `SET_NULL` —— 记录被删除后日志仍然说得清是谁的哪一天
- API **只读**，没有任何写入路由

### 既有模型新增字段

`ActualWorkRecord`：
- `source`：`plan` / `punch` / `manual` / `correction`
- `late_minutes` / `early_leave_minutes`：扣除分店容差后的偏差分钟，**服务端派生，序列化器 read-only**（客户端不能自称迟到 0 分钟）

`BranchScheduleSetting`（每分店可调）：
- `late_grace_minutes` / `early_leave_grace_minutes`：默认 0（诚实的默认值 —— 想要宽限的分店主动开启）
- `attendance_day_cutover_hour`：默认 5。**早于此时刻的打卡归属前一个营业日** —— 22:00 上班、01:30 下班会落在同一天，月末也不会被切到错误的工资月
- `self_punch_enabled`：默认 True。关闭后该分店完全回到改动前的「店长录入」模式

以上四项自 2026-11-03 起可在「排班管理 → 班次模板与考勤规则」中由总部管理员修改（店长只读）；此前没有界面入口，只能保持默认值。
原有的上午 / 下午 / 全日三组固定时间已迁移为班次模板并从该模型删除，见 [09_SCHEDULING.md](09_SCHEDULING.md)。

---

## 5. 迁移

| 迁移 | 内容 | 可回滚 |
|---|---|---|
| `scheduling/0007_actualworkrecord_early_leave_minutes_and_more` | 新增 3 个模型 + 7 个字段（全部带默认值，不改既有数据） | 是（标准 schema 回滚） |
| `scheduling/0008_backfill_actual_work_source` | 给历史记录贴 `source` 标签：有 `shift` 且 `adjustment_reason` 为空 → `'plan'`，其余保持 `'manual'` | 是，`reverse` 将 `'plan'` 改回 `'manual'`，即 0007 之后的原始状态 |
| `scheduling/0009_backfill_attendance_exception_minutes` | 回填历史记录的 `late_minutes` / `early_leave_minutes`（按分店容差与跨午夜规则重算） | 是，`reverse` 将两列清零，即 0007 默认值 |

**生产兼容性**：
- 0007 全部为新增，无字段删除、无类型变更、无数据改写
- 0008 / 0009 都**不触碰任何出勤数值（除下述两列）、状态或缺勤标记**。`wages/calculation.py` 读取的是
  `status`、`absent`、`actual_start`、`actual_end`、`actual_break_minutes`，既不读 `source`
  也不读 `late_minutes` / `early_leave_minutes`，因此这两个迁移**不可能影响任何已结算工资**。
  对应测试：`HistoricalExceptionMinuteBackfillTests::test_nothing_the_wage_engine_reads_is_touched`。

**0008 能说明什么、不能说明什么（重要）**：

`shift` 外键在店长修改记录之后依然保留，所以它只能证明「这一天有排班」，
**不能证明这一天的时间仍然来自排班**。因此 0008 的 `'plan'` 是一个**尽力而为的标签，不是精确还原**：

- `shift_id IS NULL` → `'manual'`：确定正确（从未排班，只能是手工录入）。
- `adjustment_reason` 非空 → 保持 `'manual'`：确定正确。序列化器在实际时间与班次不一致时**强制要求**
  填写该字段（`ActualWorkRecordSerializer.validate`），unlock 也会往里追加，本版本之前没有其他写入方，
  所以非空就是「人动过」的正向证据。
- 其余有排班的记录 → `'plan'`：**可能包含店长改过、但恰好改回计划时间（或在该校验生效前改过）的日期**。
  区分它们所需的信息从未被记录下来。

之所以仍然打标签而不是全部留作 `'manual'`：这一列在店长列表里回答的是「这一天有没有人看过」，
对一整月排班历史全写 `'manual'` 比带着已记录限制的 `'plan'` 更容易误导。
本版本之后的所有写入都在写入时就确定 `source`（见上面的审计调用点清单），
所以这个歧义只存在于早于该字段的历史数据中。

**0009 为什么必要**：0007 给两列的默认值 0 对新记录是对的，对历史是错的 ——
`ActualWorkRecordFilter.filter_exception` 直接查询这两列，所以不回填的话，
店长用默认的「只看异常」视图看过去几个月，会**一条迟到/早退都看不到**，不是少了细节，而是答案是错的。

**部署**：这三个迁移都还没有应用到任何环境（本地 `showmigrations scheduling` 显示 0007/0008/0009 均未应用）。
部署步骤以 [`04_DEPLOYMENT_RUNBOOK.md`](04_DEPLOYMENT_RUNBOOK.md) 的「生产服务器拉取并部署」为准
（`git pull --ff-only origin main` → build → `manage.py migrate` → `up -d`）。
**不要用仓库根目录的 `bash deploy.sh`**：它内部是 `git reset --hard origin/<ref>`，
与运行手册明确要求的 `--ff-only` 冲突，也会丢弃服务器上任何未提交修改
（已登记为 `05_TESTS_AND_RISKS.md` 的 P1-04，本次未改动该脚本）。

---

## 6. 权限边界

三层同心作用域，**在 queryset 上强制**（不只是详情路由），所以列表请求不可能泄漏，伪造 pk 只会 404：

| 角色 | 可见范围 | 可写范围 |
|---|---|---|
| `admin` | 本 Organization 的全部分店 | 同左；仅 admin 可 lock / unlock |
| `branch` | 仅本分店 | 同左；可确认、可审批补卡申请 |
| `staff` | **仅本人**，且账号必须关联 `StaffMember` | 仅本人打卡、提交/撤回本人申请 |

- staff 提交的 `employee` 字段**被忽略而非被信任** —— 发别人的 id 不会成功，只会写成自己的
- staff 不能审批任何申请（含自己的）：审批是补卡进入工资链路的唯一入口，必须是第二双眼睛
- 前端路由隐藏只是装饰，以上全部由后端 `AttendanceScopedMixin` 执行
- 新增的三个 API 路径都已登记在 `common/features.py` 的 `scheduling` 模块开关下

对应测试：`AttendancePermissionTests`（6 例）、`AttendanceTenantIsolationTests`（6 例，跨 Organization）。

---

## 7. API

| 路径 | 方法 | 说明 |
|---|---|---|
| `/api/attendance-punches/` | GET, POST | 打卡；无 PATCH / DELETE |
| `/api/attendance-punches/today/` | GET | 当前应该按哪个按钮（`canClockIn` / `canClockOut` / `canStartBreak` / `canEndBreak`） |
| `/api/attendance-corrections/` | GET, POST | 补卡申请 |
| `/api/attendance-corrections/{id}/approve/` | POST | 仅 branch / admin |
| `/api/attendance-corrections/{id}/reject/` | POST | 仅 branch / admin，`note` 必填（员工有权知道理由） |
| `/api/attendance-corrections/{id}/withdraw/` | POST | 本人撤回 |
| `/api/attendance-change-logs/` | GET | 只读审计 |
| `/api/actual-work-records/?exception=true` | GET | 新增筛选：只看迟到/早退/缺勤/打卡不全的日期 |
| `/api/schedule-periods/{id}/generate_actual_records/` | POST | 既有端点；新增：每条生成的记录在同一事务内写 `source=generated` 审计条目 |

---

## 8. 前端

| 文件 | 角色 | 内容 |
|---|---|---|
| `views/staff/MyAttendanceView.vue` | staff | 上下班/休息打卡（2×2 大按钮，手机优先）、本月本人记录、补卡申请 |
| `views/AttendanceView.vue` | admin / branch | 按分店·员工·月份查询、**默认只看异常**、待审批队列置顶、批量确认、锁定/解锁、变更历史、Excel 导出 |

路由 `/my-attendance`（staff）和 `/attendance`（admin, branch），均受 `scheduling` 模块开关控制。
中日文案已补齐（`i18n/locales/{zh,ja}.ts` 的 `attendance.*` 与 `nav.attendance` / `nav.myAttendance`）。

四个打卡按钮**永远渲染、按需禁用**，不做显示/隐藏 —— 按钮忽隐忽现的界面读起来像坏了，
「退勤按钮为什么不见了」是一通客服电话，「休憩中所以退勤是灰的」是自解释的。
可用性由服务端 `today/` 决定，前端不自行推断；服务端在写入时同样校验顺序，
所以过期的页面最多得到一个明确的错误，绝不会写出错误的记录。

---

## 9. 测试

`scheduling/tests_attendance.py`，共 **87 个用例**，按「保护什么」而非按端点分组：

| 测试类 | 用例数 | 保护的东西 |
|---|---|---|
| `BusinessDateTests` | 5 | 营业日切换，跨午夜归属 |
| `SummarizePunchesTests` | 5 | 打卡归约，含未闭合休息、缺下班打卡 |
| `ExceptionMinutesTests` | 9 | 迟到/早退分钟、容差扣减、跨午夜班次 |
| `PunchApiTests` | 10 | 打卡 API、服务端时钟、顺序校验、分店开关 |
| `PayrollSafetyTests` | 7 | **核心不变量**（见第 2 节） |
| `CorrectionRequestTests` | 13 | 补卡提交/审批/驳回/撤回 |
| `AttendancePermissionTests` | 6 | 角色边界 |
| `AttendanceTenantIsolationTests` | 6 | 跨 Organization 隔离 |
| `AttendanceChangeLogTests` | 5 | 审计必留痕，且比记录活得久 |
| `ExceptionFilterTests` | 3 | 异常筛选是全月的精确划分 |
| `HistoricalExceptionMinuteBackfillTests` | 13 | 迁移 0009：历史迟到/早退能被既有筛选识别，且不动工资引擎读取的任何字段 |
| `GeneratedRecordAuditTests` | 3 | 排班生成的记录也必写 `generated` 审计条目，重复执行不产生噪声 |

实际运行结果（2026-11-01）：

```
# 2026-11-01，本模块首次落地时
venv/bin/python manage.py test
Ran 594 tests in 445.234s
OK

# 2026-11-02，独立核查后的修复（出勤相关定向运行）
venv/bin/python manage.py test scheduling organizations wages accounts
Ran 298 tests in 234.393s
OK
```

（改动前基线为 501 个。注意：`--parallel 4` 会在 `wages.tests.WageV2SimpleTests` 上报
`TransactionManagementError`，这是**改动前就存在**的并行运行器问题，串行运行全部通过。）

迁移本身的验证范围要说清楚：测试数据库是从全部迁移建起来的，所以 0007/0008/0009 的**正向**应用已被
每次测试运行覆盖；两个 `RunPython` 的**正向与反向函数**由上表的用例直接调用验证。
**没有**在一个带历史数据的数据库上实际执行过 `migrate` 再 `migrate scheduling 0006` 回滚。

---

## 10. 已知限制

- **没有地理位置/设备校验**。打卡只记录服务器时间与来源（self / manager），不验证员工是否真的在店内。
  Frappe HR 有 `latitude`/`longitude`/`geolocation`，本项目暂未采纳 —— 需要先确认业务上是否要求，以及是否涉及员工隐私合规。
- **没有生物识别/硬件打卡机对接**。两个参考方案都有，本项目目前只有网页打卡。
- **未闭合的休息不计入休息时长**，只在审核列表中标记 `break-not-closed`。
  这是刻意的：猜一个时长会直接减少员工的带薪时间。
- **`attendance_day_cutover_hour` 是每分店一个固定小时**，不随班次变化。
  对「同一分店既有早班又有通宵班」是够用的（切换时刻只要落在两个班次之间的空档即可），
  但如果未来出现 24 小时连续运营，需要改为按班次判定。
- **`bulk_confirm` 读取 `request.data['ids']` 时要求 JSON 请求体**。表单编码会把数组压成字符串，
  而 `id__in` 会把字符串按字符迭代。前端 `bulkConfirmActualWorkRecords` 发的是 JSON，所以生产不受影响；
  这是改动前就存在的脆弱点，本次未改动该端点的这一行为，仅在测试中显式使用 `format='json'`。
- **`source = 'plan'` 对历史记录只是尽力而为的标签**，不能证明那一天的时间没有被店长改过（见第 5 节）。
  本版本之后写入的记录不受此限制。
