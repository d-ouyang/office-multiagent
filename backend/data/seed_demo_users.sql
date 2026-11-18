-- 演示账号种子（幂等）：p6.44 追加。明文密码不落仓库（见团队密库/交接文档）。
-- ⚠️ 这是演示环境账号；生产正式使用前请改密（auth/change-password 或 UPDATE password_hash）。
INSERT INTO `user` (`employee_id`, `username`, `password_hash`, `role`, `model_pool_id`)
SELECT * FROM (SELECT 'EMP002', 'ouyang', '$2b$12$NuUApez4mfG1k0S7wgMTUebmSE2bVS49TOomqLMhPsWIWaxGBo84W', 'admin', 3) AS t
WHERE NOT EXISTS (SELECT 1 FROM `user` WHERE username='ouyang') AND NOT EXISTS (SELECT 1 FROM `user` WHERE employee_id='EMP002');
INSERT INTO `user` (`employee_id`, `username`, `password_hash`, `role`, `model_pool_id`)
SELECT * FROM (SELECT 'EMP003', 'wangfang', '$2b$12$XH0I3EnrV3lfpk3qw883x.Xd6bquu1KmbjZREASs9Z2F6dXf88tEK', 'user', 2) AS t
WHERE NOT EXISTS (SELECT 1 FROM `user` WHERE username='wangfang') AND NOT EXISTS (SELECT 1 FROM `user` WHERE employee_id='EMP003');
INSERT INTO `user` (`employee_id`, `username`, `password_hash`, `role`, `model_pool_id`)
SELECT * FROM (SELECT 'EMP004', 'lilei', '$2b$12$XH0I3EnrV3lfpk3qw883x.Xd6bquu1KmbjZREASs9Z2F6dXf88tEK', 'user', 2) AS t
WHERE NOT EXISTS (SELECT 1 FROM `user` WHERE username='lilei') AND NOT EXISTS (SELECT 1 FROM `user` WHERE employee_id='EMP004');
INSERT INTO `user` (`employee_id`, `username`, `password_hash`, `role`, `model_pool_id`)
SELECT * FROM (SELECT 'EMP005', 'zhangmin', '$2b$12$XH0I3EnrV3lfpk3qw883x.Xd6bquu1KmbjZREASs9Z2F6dXf88tEK', 'user', 2) AS t
WHERE NOT EXISTS (SELECT 1 FROM `user` WHERE username='zhangmin') AND NOT EXISTS (SELECT 1 FROM `user` WHERE employee_id='EMP005');
INSERT INTO `user` (`employee_id`, `username`, `password_hash`, `role`, `model_pool_id`)
SELECT * FROM (SELECT 'EMP006', 'liuyang', '$2b$12$XH0I3EnrV3lfpk3qw883x.Xd6bquu1KmbjZREASs9Z2F6dXf88tEK', 'user', 2) AS t
WHERE NOT EXISTS (SELECT 1 FROM `user` WHERE username='liuyang') AND NOT EXISTS (SELECT 1 FROM `user` WHERE employee_id='EMP006');
INSERT INTO `user` (`employee_id`, `username`, `password_hash`, `role`, `model_pool_id`)
SELECT * FROM (SELECT 'EMP007', 'chenjing', '$2b$12$XH0I3EnrV3lfpk3qw883x.Xd6bquu1KmbjZREASs9Z2F6dXf88tEK', 'user', 2) AS t
WHERE NOT EXISTS (SELECT 1 FROM `user` WHERE username='chenjing') AND NOT EXISTS (SELECT 1 FROM `user` WHERE employee_id='EMP007');
INSERT INTO `wallet` (`user_id`, `balance`)
SELECT u.id, 100000 FROM `user` u
WHERE u.username IN ('ouyang','wangfang','lilei','zhangmin','liuyang','chenjing')
  AND NOT EXISTS (SELECT 1 FROM wallet w WHERE w.user_id = u.id);
