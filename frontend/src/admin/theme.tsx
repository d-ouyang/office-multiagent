import zhCN from 'antd/locale/zh_CN';
import type { ReactNode } from 'react';

import { ConfigProvider, theme } from './ui';

/**
 * 管理端专用深色主题；不包工作台，避免污染对话 UI。
 * 尺寸基准对齐 rag admin-console（正文 14px / 控件高 ~34 / 表格单元格 10×12），
 * 管理端是"读密集表格"的界面，紧凑优先。
 */
export default function AdminTheme({ children }: { children: ReactNode }) {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: theme.darkAlgorithm,
        token: {
          fontSize: 14,
          controlHeight: 32,
          controlHeightLG: 36,
          borderRadius: 6,
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
            itemHeight: 42,
            itemMarginBlock: 4,
            itemMarginInline: 8,
            iconSize: 16,
            fontSize: 14,
          },
          Table: {
            cellFontSize: 14,
            cellPaddingBlock: 10,
            cellPaddingInline: 12,
            headerSplitColor: 'transparent',
          },
          Form: {
            itemMarginBottom: 16,
            verticalLabelPadding: '0 0 6px',
          },
          Input: {
            controlHeight: 34,
            paddingBlock: 6,
          },
          Select: {
            controlHeight: 34,
          },
          DatePicker: {
            controlHeight: 34,
          },
          Modal: {
            titleFontSize: 16,
          },
          Pagination: {
            itemSize: 28,
          },
        },
      }}
    >
      {children}
    </ConfigProvider>
  );
}
