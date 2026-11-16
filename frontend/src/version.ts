/**
 * 版本号兜底值（v2.3.0-p1.5）。
 *
 * 真正的版本以运行时 `/api/v1/health` 返回的 `version` 为准——它由 CI 在构建镜像时
 * 用 `git describe --tags --always` 注入，随 tag 自动变化，前端不需要重新构建就能显示新版本。
 *
 * 为什么不再写死：这里原先写 `v2.0.0` 并注释"发新 tag 时改这一处"，实际从 v2.0.0
 * 之后连续两个大版本没人改，侧栏一直显示旧版本。版本号不能依赖人记得改。
 */
export const APP_VERSION = 'dev';
export const APP_BLURB = '企业级智能办公助手';
