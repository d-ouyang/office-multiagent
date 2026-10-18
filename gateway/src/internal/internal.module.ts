import { Module } from '@nestjs/common';

import { InternalAuthClient } from './internal-auth.client';
import { InternalController } from './internal.controller';

@Module({
  controllers: [InternalController],
  providers: [InternalAuthClient],
})
export class InternalModule {}
