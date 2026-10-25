/**
 * 管理端按需引用 antd 6 ESM（antd/es/*）。
 * 不走 `import { X } from 'antd'` 桶文件，避免把未用组件打进管理端包。
 * 样式走 CSS-in-JS，不引入 antd/dist/*.css。
 */
export { default as Alert } from 'antd/es/alert';
export { default as App } from 'antd/es/app';
export { default as Avatar } from 'antd/es/avatar';
export { default as Button } from 'antd/es/button';
export { default as Card } from 'antd/es/card';
export { default as Col } from 'antd/es/col';
export { default as ConfigProvider } from 'antd/es/config-provider';
export { default as DatePicker } from 'antd/es/date-picker';
export { default as Descriptions } from 'antd/es/descriptions';
export { default as Drawer } from 'antd/es/drawer';
export { default as Empty } from 'antd/es/empty';
export { default as Form } from 'antd/es/form';
export { default as Input } from 'antd/es/input';
export { default as InputNumber } from 'antd/es/input-number';
export { default as Layout } from 'antd/es/layout';
export { default as Menu } from 'antd/es/menu';
export { default as message } from 'antd/es/message';
export { default as Modal } from 'antd/es/modal';
export { default as Pagination } from 'antd/es/pagination';
export { default as Row } from 'antd/es/row';
export { default as Segmented } from 'antd/es/segmented';
export { default as Select } from 'antd/es/select';
export { default as Space } from 'antd/es/space';
export { default as Spin } from 'antd/es/spin';
export { default as Statistic } from 'antd/es/statistic';
export { default as Switch } from 'antd/es/switch';
export { default as Table } from 'antd/es/table';
export { default as Tag } from 'antd/es/tag';
export { default as Tooltip } from 'antd/es/tooltip';
export { default as Typography } from 'antd/es/typography';
export { default as theme } from 'antd/es/theme';
