-- 演示账号种子（幂等）：p6.44 追加。密码：管理员 Nianan@2026，其余 Office@2026
-- ⚠️ 这是演示环境账号；生产正式使用前请改密。
INSERT INTO `user` (`employee_id`, `username`, `password_hash`, `role`, `model_pool_id`)
SELECT * FROM (SELECT 'EMP002', 'ouyang', '$2b$12$QoB6edm4O2pXL./yvDZYSOuFM7zYUdu9a84N3XvBl91uumA.SEi.6', 'admin', 3) AS t
WHERE NOT EXISTS (SELECT 1 FROM `user` WHERE username='ouyang') AND NOT EXISTS (SELECT 1 FROM `user` WHERE employee_id='EMP002');
INSERT INTO `user` (`employee_id`, `username`, `password_hash`, `role`, `model_pool_id`)
SELECT * FROM (SELECT 'EMP003', 'wangfang', '$2b$12$bNR0z77cn97if3oQksgAqei/sNCcHMnHrgvaGrFV5rwL02qM3x1pS', 'user', 2) AS t
WHERE NOT EXISTS (SELECT 1 FROM `user` WHERE username='wangfang') AND NOT EXISTS (SELECT 1 FROM `user` WHERE employee_id='EMP003');
INSERT INTO `user` (`employee_id`, `username`, `password_hash`, `role`, `model_pool_id`)
SELECT * FROM (SELECT 'EMP004', 'lilei', '$2b$12$bNR0z77cn97if3oQksgAqei/sNCcHMnHrgvaGrFV5rwL02qM3x1pS', 'user', 2) AS t
WHERE NOT EXISTS (SELECT 1 FROM `user` WHERE username='lilei') AND NOT EXISTS (SELECT 1 FROM `user` WHERE employee_id='EMP004');
INSERT INTO `user` (`employee_id`, `username`, `password_hash`, `role`, `model_pool_id`)
SELECT * FROM (SELECT 'EMP005', 'zhangmin', '$2b$12$bNR0z77cn97if3oQksgAqei/sNCcHMnHrgvaGrFV5rwL02qM3x1pS', 'user', 2) AS t
WHERE NOT EXISTS (SELECT 1 FROM `user` WHERE username='zhangmin') AND NOT EXISTS (SELECT 1 FROM `user` WHERE employee_id='EMP005');
INSERT INTO `user` (`employee_id`, `username`, `password_hash`, `role`, `model_pool_id`)
SELECT * FROM (SELECT 'EMP006', 'liuyang', '$2b$12$bNR0z77cn97if3oQksgAqei/sNCcHMnHrgvaGrFV5rwL02qM3x1pS', 'user', 2) AS t
WHERE NOT EXISTS (SELECT 1 FROM `user` WHERE username='liuyang') AND NOT EXISTS (SELECT 1 FROM `user` WHERE employee_id='EMP006');
INSERT INTO `user` (`employee_id`, `username`, `password_hash`, `role`, `model_pool_id`)
SELECT * FROM (SELECT 'EMP007', 'chenjing', '$2b$12$bNR0z77cn97if3oQksgAqei/sNCcHMnHrgvaGrFV5rwL02qM3x1pS', 'user', 2) AS t
WHERE NOT EXISTS (SELECT 1 FROM `user` WHERE username='chenjing') AND NOT EXISTS (SELECT 1 FROM `user` WHERE employee_id='EMP007');
INSERT INTO `wallet` (`user_id`, `balance`)
SELECT u.id, 100000 FROM `user` u
WHERE u.username IN ('ouyang','wangfang','lilei','zhangmin','liuyang','chenjing')
  AND NOT EXISTS (SELECT 1 FROM wallet w WHERE w.user_id = u.id);
