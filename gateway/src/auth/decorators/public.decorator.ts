import { SetMetadata } from '@nestjs/common';

export const IS_PUBLIC_KEY = 'isPublic';

/** 标记一个路由免 JWT 放行（全局 JwtAuthGuard 会读取这个元数据）。 */
export const Public = () => SetMetadata(IS_PUBLIC_KEY, true);
