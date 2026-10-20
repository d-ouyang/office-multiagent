/**
 * 登录用户源（p6.1）——网关直查 office MySQL 的 `user` 表。
 *
 * 为什么登录在网关：§13.3 认证单点——JWT 由网关签、后端 PyJWT 验；登录（验密+签发）
 * 与验签必须在同一信任层（RAG 同构）。mysql2 连接池懒创建：模块加载不连库，
 * MySQL 未就绪只影响 login 请求（如实 503），不影响网关健康与代理转发。
 */
import { Injectable } from '@nestjs/common';
import { createPool, type Pool } from 'mysql2/promise';

export interface UserRow {
  id: number;
  employee_id: string;
  username: string;
  password_hash: string;
  role: string;
}

export interface UserRepoConfig {
  host: string;
  port: number;
  user: string;
  password: string;
  database: string;
}

@Injectable()
export class UserRepo {
  private pool: Pool | null = null;

  constructor(private readonly cfg: UserRepoConfig) {}

  private get pool_(): Pool {
    if (!this.pool) {
      this.pool = createPool({ ...this.cfg, connectionLimit: 4 });
    }
    return this.pool;
  }

  async findByUsername(username: string): Promise<UserRow | null> {
    const [rows] = await this.pool_.execute(
      'SELECT id, employee_id, username, password_hash, role FROM `user` WHERE username = ? LIMIT 1',
      [username],
    );
    return (rows as UserRow[])[0] ?? null;
  }
}
