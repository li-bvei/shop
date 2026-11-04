# 排班（按时间排班）重构

最后整理：2026-11-03

本文件说明 2026-11-03 对排班模块的重构：为什么去掉固定的「上午 / 下午 / 全日」三格、参照了哪些开源项目、
数据怎么迁移、出勤如何按时间计算，以及已知限制。打卡 / 补卡 / 审计这一层见 [08_ATTENDANCE.md](08_ATTENDANCE.md)。

---

## 1. 重构前的问题

- `BranchScheduleSetting` 只存三组时间：`morning_*`、`afternoon_*`、`full_day_*`（含全日休息时段）。
- 排班表每一格只能在「休 → 上午 → 下午 → 全日」之间循环点选；保存时把这三组时间之一写进 `Shift`。
- 与三组时间都不相同的排班显示为「自定义」，**在排班表里既不能新建也不能修改**（`saveSingleCell` 对它直接跳过），
  `crosses_midnight` 也固定写 `false` —— 排班表实际上排不出跨夜班。
- 新建分店会被自动种上同样的三组时间（10:30–15:00 / 17:00–22:00 / 10:30–22:00），前端也没有任何修改它们的界面。
- 演示种子同样按这三格生成排班。

`Shift` 模型本身一直是按时间存的（`planned_start` / `planned_end` / `crosses_midnight` / `planned_break_minutes`），
工资引擎也一直按实际时间计算 —— 限制完全在「三格模板 + 排班表交互」这一层。

## 2. GitHub 调研（2026-11-03 实际访问仓库与文档）

| 项目 | 许可证 | 维护情况 | 排班数据模型（与本次相关的部分） |
|---|---|---|---|
| [Frappe HR](https://github.com/frappe/hrms) | GPL-3.0（2026-11-01 一轮核实，见 08；本轮 `LICENSE` 原始路径返回 404，未重新读取） | develop 分支最近提交 2026-11-02 | `Shift Type`：用户命名、`start_time` / `end_time`、`color`、迟到/早退宽限、上班前/下班后可打卡窗口、工时计算方式、半天/缺勤工时阈值；**结束早于开始即视为夜班**（[shift-type 文档](https://docs.frappe.io/hr/shift-type.md)）。`Shift Assignment`：员工 + `shift_type` + 起止日期，**不存时间，按引用实时读取**。`Shift Schedule`：按星期与频率循环生成分配 |
| [Horilla](https://github.com/horilla-opensource/horilla) | LGPL-2.1 | master 最近提交 2026-07-29 | `EmployeeShift` + `EmployeeShiftSchedule`（班次 × 星期一行：`start_time` / `end_time` / `minimum_working_hour` / `is_night_shift`，`save()` 中 `is_night_shift = start_time > end_time`）、`RotatingShift`、`ShiftRequest`；2.0 分支新增按日期的 `Roster`（员工 + 日期 + 班次） |
| [Schichtplaner](https://github.com/bpalme/shiftplanner)（fork 自 lennystepn-hue/schichtplaner） | MIT | fork 仅 2026-03-01～03-02 的提交，0 star | Next.js + Prisma + PostgreSQL，界面只有德语。`Shift`：每周一张排班表里的具体行（`dayOfWeek`、`shiftFrom` / `shiftTo` 字符串、`maxEmployees`、`pauseValue` + `pauseOption`），**没有可复用的班次模板层** |
| [MASTERPLAN](https://github.com/schorschii/MASTERPLAN) | LICENSE 为 GPL-3.0，但 README 写明超过 5 个用户需购买许可 | 2026-06 有零星提交，整体稀疏 | PHP + MySQL。`Service`：`start` / `end`（文本）、`wd1`～`wd7` 星期标志、`employees` 需求人数、`color` |
| [Staffjoy suite](https://github.com/staffjoy/suite) | MIT（附带的 Highcharts 为非商用许可） | 2018 年停更 | Flask + MySQL，已不维护 |

### 结论：没有可以「直接拿来用」的现成应用

- **Frappe HR / Horilla / MASTERPLAN** 是完整的 HRMS 或排班系统，许可证为 copyleft（MASTERPLAN 还有用户数收费条款），
  不能并入本项目这样的闭源 SaaS；而且整体替换意味着放弃本项目已有的多租户、日报、工资链路。
- **MIT 许可的两个**：Schichtplaner 是技术栈完全不同、刚起步的小 fork，没有模板层；Staffjoy 已停更 8 年。

因此本次**不引入任何外部代码或依赖**，而是按这些项目共同的、按时间排班的形状重构本项目自己的排班模块。
数据模型和工作流属于设计，可以借鉴。

### 采纳 / 不采纳

| 决策 | 依据 |
|---|---|
| **班次模板（ShiftTemplate）：每店任意数量，各自有名称、起止时间、休息分钟、颜色** | Frappe `Shift Type`（start/end/roster color）、Horilla `EmployeeShiftSchedule`、MASTERPLAN `Service` 都是这一形状 |
| **结束时间不晚于开始时间 = 跨夜**，不另设标志 | Frappe 文档与 Horilla `save()` 都这样判定；少一个需要与时间保持一致的字段 |
| **排入时把模板时间复制到排班**，排班只保留模板引用（用于名称与颜色） | 与 Frappe 不同（Frappe 的 Assignment 实时引用 Shift Type 的时间）。本项目的排班直接生成出勤记录、进入工资，实时引用会让「改一下模板」悄悄改掉已排、已做、已发工资的日子 |
| **休息用分钟数表示** | Schichtplaner 的 `pauseValue` 同样如此；本项目工资引擎本来就按 `planned_break_minutes` / `actual_break_minutes` 扣减 |
| **宽限分钟仍放在分店规则上**，不放到每个模板 | Frappe 放在 Shift Type 上。本项目已有分店级宽限（0007），按模板分别设置目前没有业务需求，保持现状 |
| 不采纳：按星期循环生成（Frappe `Shift Schedule`、Horilla 轮班） | 本项目已有「复制上一月」「批量设置连续日期」，够用 |
| 不采纳：上班前 / 下班后打卡窗口、半天 / 缺勤工时阈值 | 本项目按营业日切换时刻归属打卡，工资按实际工时计，不需要「半天」判定 |
| 未做：每个时段的需求人数（Schichtplaner `maxEmployees`、MASTERPLAN `employees`） | 列为后续需求，见第 7 节 |

## 3. 数据模型与迁移

### 新增 / 变更

- `ShiftTemplate`：`branch`、`name`（可空，空时按时间显示）、`start_time`、`end_time`、`break_minutes`、
  `color`（7 色）、`sort_order`、`active`；`crosses_midnight` 为只读属性（`end_time <= start_time`）。
- `Shift.template`：可空外键，`on_delete=SET_NULL`。删除模板只会让排班失去名称与颜色，**时间不变**。
- `BranchScheduleSetting`：删除 8 个固定时段字段，只保留考勤规则（宽限、营业日切换时刻、自助打卡开关）。
- `seed_default_schedule_setting()` 不再为新分店创建任何班次时间。

| 迁移 | 内容 | 回滚 |
|---|---|---|
| `scheduling/0010_shifttemplate_shift_template` | 建 `ShiftTemplate` 表，`Shift` 加 `template` 外键 | 标准 schema 回滚 |
| `scheduling/0011_shift_templates_from_fixed_slots` | 每个分店的三组固定时间各生成一个**无名称**模板（全日休息 = 休息结束 − 开始，单位分钟）；起止时间与某组完全相同的既有排班关联到对应模板（与旧排班表判断「这一格是上午/下午/全日」的规则相同），其余保持未关联。**不改任何排班的时间**，因此不影响任何出勤记录或工资结果 | 把前三个模板的起止时间写回恢复后的列，然后删除全部模板。**全日休息时段的位置无法从分钟数还原**，回滚后为列默认值（15:00–17:00） |
| `scheduling/0012_remove_fixed_slot_fields` | 删除 8 个固定时段列 | 重新加回各列（列默认值），再由 0011 的回滚写回时间 |

迁移只使用 historical models，不 import 运行时模块。

## 4. 出勤按时间计算

### 4.1 打卡会替换按排班自动生成的记录（行为变化）

- **之前**：`generate_actual_records` 生成的记录是 `manager_confirmed`，而 `attendance.is_frozen()` 把所有
  `manager_confirmed` 都当作店长判断过、不再被打卡覆盖。结果是：**只要那天有排班，员工的打卡永远不会生效**，
  出勤和工资始终按排班时间。
- **现在**：`source='plan'` 且没有 `adjustment_reason` 的记录（即还没有人动过的排班副本）不再视为冻结。员工打卡后，
  记录改为 `source='punch'`、`status='pending'`，迟到 / 早退按实际打卡时间计算；**在店长确认之前不计入工资**。
- 店长确认过或改过的日期、管理员锁定的日期仍然不会被打卡覆盖。

### 4.2 改排班时，自动生成的记录跟着改

- `ShiftViewSet.perform_update`：在同一事务内调用 `attendance.sync_plan_record()`，把仍是排班原样副本的记录
  改成新时间，并写一条 `source=generated`、`reason=shift_retimed` 的审计。之前改了排班时间，已生成的记录不变，
  会按旧时间计薪。
- `ShiftViewSet.perform_destroy`：调用 `attendance.discard_plan_record()` 删除该排班自动生成的记录
  （`reason=shift_deleted`，审计保留员工 / 日期 / 删除前的值）。之前删除排班后，已确认的记录会留下来继续计薪。
  已经打过卡、补过卡或店长改过的记录会保留，只是不再关联排班。
- 排班换了员工或日期时，旧日期的自动记录会被删除，新日期的记录由下一次生成补上。
- `generate_actual_records` 对已有记录也会做同样的校正，返回值新增 `updated`。
- 判断「还没人动过」的规则：`source='plan'`、`adjustment_reason` 为空、且不是 `admin_locked`。
  这与 0008 给历史数据贴标签的规则一致（序列化器在时间与排班不同时强制要求填写调整原因）。

### 4.3 工时

`ActualWorkRecordSerializer` 新增只读的 `planned_minutes` / `worked_minutes`，直接调用工资引擎的
`wages.calculation.classify_minutes()`，因此页面上显示的工时与计薪工时用的是同一套算法（跨度减休息，不为负）。
前端 `utils/shiftTime.ts` 在排班表草拟时用同样规则实时计算。

### 4.4 工资的影响

- 工资引擎代码（`wages/calculation.py`）**未改动**，输入契约不变：仍只读取
  `manager_confirmed` / `admin_locked` 且未缺勤的记录的 `actual_start` / `actual_end` / `crosses_midnight` /
  `actual_break_minutes`。
- 但**工资结果可能变化**，这是修正的目的：被改过时间的排班，其自动记录会按新时间计薪；被删除的排班不再计薪；
  有排班且员工打了卡的日子，要等店长确认后才计入工资。`admin_locked` 的日期不受任何影响。

## 5. 前端

- **排班表**（`SchedulingView.vue` 月度排班表）
  - 顶部「点击格子时」：选「逐格编辑」，点格子会打开编辑框，可以选模板、设为休息，或输入任意起止时间和休息分钟；
    选某个模板或「休」，点格子即直接排入，一个月仍是每天点一下。
  - 格子显示模板名称和时间（无名称或手工输入的显示时间；跨夜显示为「22:00–次日02:00」），颜色取自模板，手工输入的为灰底描边。
  - 每个区域每天显示「人数」和「工时」，表尾显示每位员工的本月工时和区域合计。
  - 「批量设置连续日期」可选模板、自定义时间或休息；「复制上一月」原样复制每天的时间。
  - 输入的时间若与某个启用中的模板完全相同，会自动关联该模板。
- **班次模板与考勤规则**（新标签页）：模板的新增 / 编辑 / 启用停用 / 删除，显示计薪工时；考勤规则（迟到、早退宽限，
  营业日切换时刻，员工自助打卡）由总部管理员修改，店长账号只读。**这些规则此前在界面上没有任何入口。**
- **实际工作确认、员工出勤、我的出勤**：新增计划工时 / 实际工时；Excel 导出中两列为数值（小时）。
- 中日文案同步新增，两份 locale 键数一致（1695 / 1695）。

## 6. 权限

| 接口 | admin | branch | staff |
|---|---|---|---|
| `GET/POST/PATCH/DELETE /api/shift-templates/` | 本组织所有分店 | 仅本店（新建时强制本店，指定其他分店返回 403） | 403 |
| `PATCH /api/branch-schedule-settings/{branch}/` | 本组织分店 | 403（只读） | 403 |

`shift-templates` 已加入 `common/features.py` 的 `scheduling` 模块开关。排班引用其他分店的模板会被拒绝
（`shift-template-branch-mismatch`）。

## 7. 已知限制

- **每人每天仍只有一条出勤记录**（`ActualWorkRecord` 唯一键为员工 + 日期），排班表每格一个班次。
  中间有长休息的「两段班」用一个班次加休息分钟表示；工时正确，但休息时段的位置不记录。
- **没有需求人数 / 时段覆盖曲线**，只有每天的人数与工时合计。
- **有排班但没有打卡的日子仍按排班时间计入**，与重构前相同；员工没来需要店长标记缺勤。
- 模板删除后，用过它的排班显示为手工时间（灰底），时间不变。
- 0011 的回滚无法还原全日休息时段的位置（见第 3 节）。

## 8. 验证

见 [01_CURRENT_STATE.md](01_CURRENT_STATE.md) 2026-11-03 条目中的实际命令与结果。
