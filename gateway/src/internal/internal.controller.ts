import { Controller, Get } from '@nestjs/common';

import { InternalAuthClient } from './internal-auth.client';
import { Public } from '../auth/decorators/public.decorator';

/** 网关→后端内部信任自检（node:http + X-Internal-Token）。 */
@Controller('api/internal')
export class InternalController {
  constructor(private readonly client: InternalAuthClient) {}

  @Public()
  @Get('ping')
  ping(): Promise<{ ok: boolean; detail: string }> {
    return this.client.ping();
  }
}
