/**
 * 统一的接口错误模型（v2.4.1）。
 *
 * 为什么存在：此前 429 在界面上直接显示 `HTTP 429`。后端明明返回了
 *   {"detail":{"code":"BALANCE_INSUFFICIENT","message":"钱包余额不足：余额 ¥0，本次预估 2986…"}}
 * 但 `useNdjsonStream` 只抛了状态码，把最有用的 message 丢了——用户看到"HTTP 429"只能来问人。
 *
 * 分两层：
 *   1. `parseApiError` 负责把 HTTP 响应体解析成结构化错误（status/code/message）；
 *   2. `describeError` 负责把错误翻译成"用户能懂 + 知道下一步做什么"的文案。
 * 展示交给 `components/Notice.tsx`，不要再在页面里手写红条。
 */

/** 后端两种错误体：FastAPI 的 {detail:{code,message}} 与网关的 {error:{code,message}}。 */
export interface ApiErrorBody {
  detail?: { code?: string; message?: string } | string;
  error?: { code?: string; message?: string };
  message?: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

/** 从响应体里尽力取出 code + message；取不到就退化成"请求失败（HTTP xxx）"。 */
export function parseApiError(status: number, body: unknown): ApiError {
  const b = (body ?? {}) as ApiErrorBody;
  if (typeof b.detail === 'string' && b.detail.trim()) {
    return new ApiError(status, '', b.detail.trim());
  }
  const obj = (b.detail && typeof b.detail === 'object' ? b.detail : undefined) ?? b.error ?? {};
  const code = String(obj.code ?? '');
  const message = String(obj.message ?? b.message ?? '');
  return new ApiError(status, code, message || `请求失败（HTTP ${status}）`);
}

export type NoticeKind = 'error' | 'warning' | 'info';

export interface NoticeCopy {
  kind: NoticeKind;
  title: string;
  /** 后端原文或补充说明（可含金额、token 数等具体信息） */
  message?: string;
  /** 下一步能做什么——这一行比错误本身更有用 */
  hint?: string;
}

/**
 * 把任意异常翻译成可展示的文案。
 *
 * 设计原则：标题说"发生了什么"，message 保留后端给的数字，hint 说"你能做什么"。
 * 不把 `HTTP 429` 这种实现细节当标题——它对用户没有任何行动指示。
 */
export function describeError(err: unknown): NoticeCopy {
  if (err instanceof ApiError) {
    if (err.code === 'BALANCE_INSUFFICIENT') {
      return {
        kind: 'warning',
        title: '余额不足，本次任务没能开始',
        message: err.message,
        hint: '充值后可以直接重发同一条消息，不用重新描述需求。',
      };
    }
    if (err.code === 'QUOTA_PAUSED' || err.code.includes('TOKEN_LIMIT') || err.code.includes('QUOTA')) {
      return {
        kind: 'warning',
        title: '已达单任务上限，任务已暂停',
        message: err.message,
        hint: '把任务拆小一些，或联系管理员调整单任务上限。已产生的进度不会丢。',
      };
    }
    if (err.status === 401) {
      return {
        kind: 'error',
        title: '登录已过期',
        message: err.message,
        hint: '重新登录即可继续；输入框里的内容还在。',
      };
    }
    if (err.status === 403) {
      return { kind: 'error', title: '没有权限执行这个操作', message: err.message, hint: '如需权限请联系管理员。' };
    }
    if (err.status === 404) {
      return { kind: 'error', title: '找不到请求的资源', message: err.message };
    }
    if (err.status === 429) {
      return { kind: 'warning', title: '请求有点频繁', message: err.message, hint: '稍等几秒再发一次。' };
    }
    if (err.status >= 500) {
      return {
        kind: 'error',
        title: '服务暂时不可用',
        message: err.message,
        hint: '稍后重试；持续出现请联系管理员。',
      };
    }
    return { kind: 'error', title: '请求失败', message: err.message };
  }

  const text = err instanceof Error ? err.message : String(err ?? '');
  if (/fetch|network|failed to fetch/i.test(text)) {
    return {
      kind: 'error',
      title: '连不上服务',
      message: text,
      hint: '检查网络或代理设置，然后重试。',
    };
  }
  return { kind: 'error', title: '操作没有完成', message: text || '未知错误' };
}
