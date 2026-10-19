/**
 * 统一错误体 filter（p5.0 共享网关 Phase C）——把抛出的异常一律规范成
 * `{ error: { code, message, detail?, requestId } }`，与代理层直接返回的错误体对齐。
 * 已直接发出的响应（流式吐了一半）不动。
 */
import { Catch, ExceptionFilter, HttpException, HttpStatus, Logger } from '@nestjs/common';
import { ArgumentsHost } from '@nestjs/common';
import type { Request, Response } from 'express';

function defaultCode(status: number): string {
  if (status === HttpStatus.UNAUTHORIZED) return 'UNAUTHORIZED';
  if (status === HttpStatus.FORBIDDEN) return 'FORBIDDEN';
  if (status === HttpStatus.NOT_FOUND) return 'NOT_FOUND';
  if (status === HttpStatus.TOO_MANY_REQUESTS) return 'TOO_MANY_REQUESTS';
  return `HTTP_${status}`;
}

@Catch()
export class AllExceptionsFilter implements ExceptionFilter {
  private readonly logger = new Logger('ExceptionFilter');

  catch(exception: unknown, host: ArgumentsHost): void {
    const ctx = host.switchToHttp();
    const req = ctx.getRequest<Request>();
    const res = ctx.getResponse<Response>();
    const requestId =
      (req.headers['x-request-id'] as string) || (res.getHeader('X-Request-Id') as string) || '-';

    let status = HttpStatus.INTERNAL_SERVER_ERROR;
    let code = 'INTERNAL_ERROR';
    let message = '服务器内部错误';
    let detail: string | undefined;

    if (exception instanceof HttpException) {
      status = exception.getStatus();
      const body = exception.getResponse();
      if (typeof body === 'object' && body !== null) {
        const b = body as Record<string, unknown>;
        code = String(b.code ?? defaultCode(status));
        message = String(b.message ?? exception.message);
      } else {
        message = exception.message;
        code = defaultCode(status);
      }
    } else if (exception instanceof Error) {
      detail = exception.message;
      this.logger.error(`未处理异常 | ${req.method} ${req.path} | ${exception.message}`);
    }

    if (!res.headersSent) {
      res.status(status).json({ error: { code, message, detail, requestId } });
    }
  }
}
