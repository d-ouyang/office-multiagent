/**
 * 管理端路径判定（p7.1）——纯函数单测，覆盖 prefix/角色边界。
 * 真正的拦截面在 proxy.e2e.spec.ts（普通用户 403 / admin 放行）。
 */
import { hasAdminRole, isAdminPath } from './jwt-auth.guard';

describe('管理端闸门纯函数', () => {
  it('isAdminPath 只认 /api/v1/admin 前缀', () => {
    expect(isAdminPath('/api/v1/admin/users')).toBe(true);
    expect(isAdminPath('/api/v1/admin/users/2/recharge')).toBe(true);
    expect(isAdminPath('/api/v1/admin')).toBe(true);
    expect(isAdminPath('/api/v1/administrator')).toBe(false); // 前缀相近但不是
    expect(isAdminPath('/api/v1/tasks')).toBe(false);
    expect(isAdminPath(undefined)).toBe(false);
  });

  it('hasAdminRole 只认 admin/superadmin', () => {
    expect(hasAdminRole('admin')).toBe(true);
    expect(hasAdminRole('superadmin')).toBe(true);
    expect(hasAdminRole('user')).toBe(false);
    expect(hasAdminRole('')).toBe(false);
    expect(hasAdminRole(undefined)).toBe(false);
    expect(hasAdminRole(1)).toBe(false);
  });
});
