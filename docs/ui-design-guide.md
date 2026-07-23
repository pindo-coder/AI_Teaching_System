# 前端 UI 设计规范与改造指南

> 适用对象：`frontend/`（Vue 3 + Element Plus + Vite）
> 目标：把当前"手工作坊式美学 CSS"升级为"令牌驱动的设计系统"，统一视觉、降低维护成本、为暗色模式和移动端铺路。

## 0. 现状诊断（实测数据）

| 指标 | 现状 | 问题 |
|------|------|------|
| 全局样式 | 单文件 `styles/main.css`（约 1900 行），仅 2/30+ 组件用 scoped | 样式全局污染，改一处动全身 |
| 硬编码颜色 | **498 个**不重复 hex 色值 | 同义蓝色十几种，无法统一换肤 |
| CSS 变量 | 仅 3 个（`--primary/--muted/--border`） | 令牌化不足 1% |
| 圆角 | **17 种**（8/9/10/11/12/13/14/15/16/18/20/22/23/24/25/28/30px…） | 无圆角刻度 |
| 渐变/阴影/模糊 | 78 linear + 27 radial 渐变、103 处 box-shadow、12 处 blur | 装饰过载，GPU 占用高，低端设备掉帧 |
| 字重 | 43 处非标准字重（650/750/800…） | PingFang SC / 微软雅黑无此字重，浏览器合成渲染不一致 |
| Element Plus | 未做任何主题定制（默认 #409EFF） | 与品牌蓝 #2857D7 撞色，按钮/标签两套蓝色并存 |
| 响应式 | 17 个零散断点（860/950/1250px…） | 无断点体系，移动端基本不可用 |
| 字号 | 页面标题 34–52px，元信息低至 10px | 层级靠"大小区别"，信息噪音大 |

**风格判断**：当前是"蓝色科技感 + 玻璃拟态"（轨道光环、辉光球、星点图谱）。方向本身契合 AI 产品，但装饰远超内容承载力，且与 Element Plus 默认风格割裂。建议演进为**"学术扁平风（Academic Flat）"**：保留品牌蓝，装饰收敛，信息层级靠排版与留白。

## 1. 设计原则

1. **内容先行**：思政平台的核心资产是教材原文与引用证据，视觉永远服务于阅读，每屏装饰元素 ≤1 处。
2. **层级靠灰度与字重**，不靠大字号轰炸：页面标题收敛到 28px。
3. **渐变预算制**：全站同时存在的装饰渐变 ≤3（首页 Hero、课程详情 Hero、知识图谱底）；其余一律纯色。
4. **组件库优先**：能用 Element Plus 主题变量解决的，禁止手写覆写样式。
5. **红色克制**：思政红仅用于时政要闻、党建标识等点睛场景，不用作品牌主色（避免与错误态混淆，也避免视觉压迫）。

## 2. 设计令牌（可直接落地的 tokens.css）

新建 `frontend/src/styles/tokens.css`，在 `main.ts` 中先于 `main.css` 引入：

```css
:root {
  /* 品牌色阶（蓝色 = 信任/学术） */
  --blue-50:  #EEF4FD;  --blue-100: #D7E5FA;  --blue-200: #AECBF4;
  --blue-400: #6D9FE8;  --blue-600: #2857D7;  --blue-800: #1C40A4;  --blue-900: #122C73;

  /* 中性色（墨水色系，带蓝灰倾向） */
  --ink-900: #172236;   /* 正文/标题 */
  --ink-600: #526073;   /* 次要文字 */
  --ink-400: #718096;   /* 提示文字（原 --muted） */
  --line:    #E6EAF0;   /* 边框（原 --border） */
  --bg-page: #F5F7FB;   /* 页面底色 */
  --bg-card: #FFFFFF;

  /* 语义色 */
  --color-primary: var(--blue-600);
  --color-success: #15803D;  --color-success-bg: #EAF3DE;
  --color-warning: #B45309;  --color-warning-bg: #FAEEDA;
  --color-danger:  #DC2626;  --color-danger-bg:  #FCEBEB;
  --color-party:   #B91C1C;  /* 思政红：时政/党建点睛专用 */

  /* 字阶（6 级封顶） */
  --fs-page-title: 28px;  --fs-section: 20px;  --fs-card-title: 16px;
  --fs-body: 14px;        --fs-aux: 13px;      --fs-meta: 12px;
  --fw-regular: 400; --fw-medium: 500; --fw-bold: 700;  /* 禁用 650/750/800 */

  /* 圆角（4 级） */
  --radius-control: 6px;  --radius-input: 10px;
  --radius-card: 14px;    --radius-overlay: 20px;

  /* 间距（4pt 网格） */
  --space-1: 4px;  --space-2: 8px;   --space-3: 12px;
  --space-4: 16px; --space-6: 24px;  --space-8: 32px;
  --page-padding: clamp(16px, 4vw, 40px);  /* 替换固定 38/46px */

  /* 阴影（2 级封顶，其余用边框表达层次） */
  --shadow-1: 0 1px 3px rgba(23, 34, 54, .06);
  --shadow-2: 0 8px 24px rgba(23, 34, 54, .10);

  /* 断点（统一 3 档，禁止新增零散断点） */
  /* mobile <768 / tablet 768-1279 / desktop ≥1280 */
}
```

## 3. Element Plus 主题接管（消除撞色）

EP 2.x 支持 CSS 变量覆盖，在 `tokens.css` 同级新增 `element-theme.css`：

```css
:root {
  --el-color-primary: var(--blue-600);
  --el-color-primary-light-3: var(--blue-400);
  --el-color-primary-light-5: var(--blue-200);
  --el-color-primary-light-7: var(--blue-100);
  --el-color-primary-light-8: var(--blue-50);
  --el-color-primary-light-9: #F4F8FE;
  --el-color-primary-dark-2:  var(--blue-800);
  --el-color-success: var(--color-success);
  --el-color-warning: var(--color-warning);
  --el-color-danger:  var(--color-danger);
  --el-border-radius-base: var(--radius-control);
  --el-border-radius-small: 4px;
  --el-border-radius-round: 999px;
  --el-font-size-base: var(--fs-body);
  --el-text-color-primary: var(--ink-900);
  --el-text-color-regular: var(--ink-600);
  --el-border-color: var(--line);
  --el-border-color-light: var(--line);
  --el-border-color-lighter: #EEF1F6;
}
```

效果：按钮、标签、分页、表单、消息提示全部自动输出品牌蓝，**删除 main.css 中所有 `.el-button` 手写覆写**（现有 20+ 处）。

## 4. 排版规范

| 用途 | 规格 | 规则 |
|------|------|------|
| 页面标题 | 28/36 · 700 | 每页 1 处，替换现有 34–52px hero 标题 |
| 区块标题 | 20/28 · 700 | 配合 12px 灰字副标题 |
| 卡片标题 | 16/24 · 500 | |
| 正文 | 14/22 · 400 | 表格、表单、列表默认 |
| 教材长文 | 15–16px · 行高 1.8 | 阅读场景专用 class `.prose-textbook` |
| 辅助说明 | 13/20 · 400 · ink-600 | |
| 元信息/标签 | 12/18 · 400 · ink-400 | **全站最小 12px**，清除现有 10/11px |

字体栈保持 `Inter, "PingFang SC", "Microsoft YaHei", sans-serif`，但字重只允许 400/500/700——后两款中文字体没有中间字重，650/750 会被浏览器合成导致粗细不一。

## 5. 色彩使用规则

| 场景 | 用法 |
|------|------|
| 品牌蓝 blue-600 | 主按钮、链接、激活态、进度条 |
| blue-50/100 | 选中底色、hover 底色、信息标签底 |
| 思政红 #B91C1C | **仅**时政要闻角标、党建专题标识，面积 <5% |
| 成功绿 | 已掌握、已发布、审核通过 |
| 警示橙 | 待审核、临期任务（≤3 天） |
| 危险红 | 删除、逾期、失败 |
| 知识图谱深色区 | 保留现状的深空蓝（#071B3D 系），它是全站唯一的"沉浸式场景"，但边框/文字色并入令牌 |

## 6. 组件规范要点

**卡片**：白底 + `1px solid var(--line)` + `radius-card 14px` + 无阴影；hover 仅 `translateY(-2px)` + `--shadow-1`。删除 inset 顶条、渐变底、双层边框等"炫技"变体，逾期/紧急状态改用左侧 3px 语义色条 + 语义色标签。

**Hero 区**：仅首页与课程详情保留渐变，且统一为同一组令牌渐变 `linear-gradient(120deg, var(--blue-800), var(--blue-600))`，删除轨道环/辉光球/星点装饰（这些 DOM+CSS 每页重复约 60 行）；标题 28px。

**按钮**：全部走 EP 主题；危险操作用 `type="danger" plain`；禁止手写渐变按钮。

**状态标签**：统一 `el-tag` 的 `effect="light"` + 语义色，对照表：已掌握=success、待复习=warning、已逾期=danger、中央材料=primary、教材=info、地方材料=default。

**表格/表单**：行高 ≥48px，操作列右对齐；表单 label 顶对齐（移动端友好），输入框圆角 10px。

**引用卡片（核心特色组件）**：保留引用证据设计，但 `mark` 高亮从 #FFE88A 改为 `var(--color-warning-bg)`，证据类型标签套用语义色对照表。

## 7. 布局与响应式

- 页面容器：`max-width: 1280px; margin: 0 auto; padding: var(--page-padding)`，替换固定 38px/46px。
- 顶栏：高度 64px（现 78px 偏高），导航链接在 <1024px 时收进抽屉菜单（当前移动端导航直接溢出）。
- 卡片网格统一 `repeat(auto-fill, minmax(300px, 1fr))`，删除写死的 3/4 列。
- 断点只允许三档：**768 / 1024 / 1280**，以 mobile-first 写 `min-width` 媒体查询；逐步替换现有 860/950/1250 等散点。
- 校准工作台这类三栏专业工具：桌面优先，<950px 时给"请用桌面端操作"的引导页而非硬压缩。

## 8. 可访问性（A11y）

1. 正文/背景对比度 ≥ 4.5:1：ink-900 on white = 14.8 ✅；ink-400 (#718096) on white = 4.0，仅用于 14px 以上辅助文字，更小字必须 ink-600。
2. 全站补 `:focus-visible` 轮廓：`outline: 2px solid var(--blue-400); outline-offset: 2px;`（当前键盘导航无焦点态）。
3. 图表/进度不以颜色为唯一信息载体：进度条配百分比文字，图谱节点配文字标签（现状已部分做到）。
4. 悬浮 AI 助教面板需 `role="dialog"` + Esc 关闭 + 焦点圈定。
5. 为暗色模式预留：所有颜色一律走令牌，二期只需在 `[data-theme="dark"]` 下重定义令牌值即可，**本期不做**。

## 9. CSS 工程化改造（与视觉同步进行）

```
frontend/src/styles/
├── tokens.css          # 设计令牌（唯一颜色来源）
├── element-theme.css   # EP 变量接管
├── base.css            # reset + 排版基线 + focus-visible
└── utilities.css       # .muted/.eyebrow 等少量工具类
```

- 拆分 `main.css`：页面专属样式下沉到各 `.vue` 文件的 `<style scoped>`（目前仅 2/30+ 组件 scoped），公共模式（卡片、页头、hero）抽成 `components/ui/` 下的无逻辑展示组件（`UiCard.vue`、`UiPageHeader.vue`、`UiStatPill.vue`）。
- 引入 Stylelint（`stylelint-config-standard`）+ 两条自定义规则：`declaration-property-value-disallowed-list` 禁 hex 色值（强制走令牌）、限制 `font-weight` 白名单 400/500/700。
- `db/models.py` 式命名问题前端同样存在：`NoteRichEditor.vue`、`richText.ts`、`noteContent.ts` 边界重叠，借样式下沉一并梳理。

## 10. 落地路线图（不动业务逻辑，纯样式层）

| 批次 | 内容 | 验收标准 |
|------|------|---------|
| 第 1 批（半天） | 新增 tokens.css + element-theme.css，全局引入 | 按钮/标签/分页变品牌蓝，无视觉回归 |
| 第 2 批（1 天） | 字阶、字重、最小字号全局替换；删 10/11px | grep 无 650/750/800；无 font-size <12px |
| 第 3 批（2 天） | 圆角/间距/阴影按刻度收敛；渐变预算制（全站 ≤3） | 圆角值 ≤4 种；渐变 ≤3 处 |
| 第 4 批（2 天） | main.css 拆分下沉 scoped；抽 UiCard/UiPageHeader | main.css <200 行 |
| 第 5 批（1 天） | 响应式断点统一 + 顶栏抽屉菜单 + focus-visible | 768/1024/1280 三档；键盘可全程操作 |
| 第 6 批（按需） | Stylelint 门禁接入 CI | 新增 hex 色值直接报错 |

每批都是独立 PR，纯 CSS/DOM 调整，不触碰 API 与状态逻辑，风险可控。
