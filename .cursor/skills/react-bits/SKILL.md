---
name: react-bits
description: >-
  Integrates a React Bits component into office-multiagent from the user's
  four inputs (提示词, 示例代码, 源码, CLI) plus the effect's purpose. Use when
  the user pastes a React Bits prompt, usage example, component source, or
  `npx shadcn add @react-bits`, or asks to add a reactbits.dev motion effect.
---

# React Bits 动效接入

用户一次给出四样东西，再加上这段动效用来做什么：

1. 提示词（组件名、变体、依赖、Props）
2. 示例代码
3. 源码（TSX，以及同条消息里的 CSS）
4. CLI（`npx shadcn@latest add @react-bits/...`）

动效目的优先于示例里的原始场景。示例写 Ask anything，目的写替换办公助手底部输入条，就接进工作台输入条，不另做一套演示页。

## 接入

1. 依赖按提示词安装，在 `frontend/` 用 npm（`npm install`，镜像 `https://registry.npmmirror.com`）。已在 `frontend/package.json` 里的不要重复加。不要改 git config。
2. 组件放到 `frontend/src/components/bits/`，CSS 同目录，`import './Name.css'`。这是 Vite，删掉 `'use client'`。
3. 源码按给出的实现抄进来。只改目的必需的部分：无障碍名称、文案、以及调用方传入的 props。不要重写交互。
4. 颜色只用本项目已有色，不新增色相（见 `frontend/src/styles.css` 的 `:root`）：
   - 强调 `#58a6ff`
   - 底 `#0f1115`，卡片 `#1a1f27`，次级面 `#222834`，边 `#2c3444`
   - 字 `#e6e9ef`，弱字 `#8b93a7`
   - 成功 `#3fb950`，错误 `#f85149`，警告 `#d29922`
5. 输入条在聊天主区底部（`.chat-main` 里、消息列表之下），不要改成脱离布局的 `fixed` 浮层，也不要盖住侧栏。
6. 出现/消失若目的需要，包在组件外面，用 `motion`。组件自己的拖拽、悬停、点击、形变保持原样。
7. 浏览器里验证：组件自己的交互，以及目的里的结果（发送、停止、上传、模型切换仍走现有接口）。减弱动效时不做多余弹跳。
8. 用中文说明做了什么。用户没要求就不要提交，也不要自动 `docker compose up`。
