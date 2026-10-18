import { Controller, Get } from '@nestjs/common';

import { Public } from '../auth/decorators/public.decorator';

/** 网关自身健康检查（免 token）。注意：这只说明网关活着，不含后端状态。 */
@Controller('api')
export class HealthController {
  @Public()
  @Get('health')
  health(): { status: string; service: string } {
    return { status: 'ok', service: 'office-multiagent-gateway' };
  }
}
