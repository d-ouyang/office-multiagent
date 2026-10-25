import zhCN from 'antd/locale/zh_CN';
import type { ReactNode } from 'react';

import { ConfigProvider, theme } from './ui';

/** 管理端专用深色主题；不包工作台，避免污染对话 UI。 */
export default function AdminTheme({ children }: { children: ReactNode }) {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: theme.darkAlgorithm,
        token: {
          fontSize: 17,
          borderRadius: 8,
          colorPrimary: '#4f6ef7',
          colorBgLayout: '#0f1420',
          colorBgContainer: '#151b2b',
          colorBgElevated: '#1b2234',
          colorBorder: '#232c40',
          colorText: '#e6eaf2',
          colorTextSecondary: '#a2acc2',
        },
        components: {
          Menu: {
            itemHeight: 52,
            itemMarginBlock: 6,
            itemMarginInline: 10,
            iconSize: 18,
            fontSize: 17,
          },
          Table: {
            cellFontSize: 16,
            cellPaddingBlock: 14,
            cellPaddingInline: 16,
          },
          Pagination: {
            itemSize: 36,
          },
        },
      }}
    >
      {children}
    </ConfigProvider>
  );
}
