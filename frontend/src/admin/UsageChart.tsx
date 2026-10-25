import { useEffect, useRef } from 'react';
import { BarChart } from 'echarts/charts';
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components';
import * as echarts from 'echarts/core';
import type { ECharts } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';

import type { UsagePoint } from '../lib/api';
import { fmtTokens } from './format';

echarts.use([BarChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

const COLORS = ['#3dd68c', '#f5a524', '#4f6ef7', '#5dcaa5', '#c084fc', '#fb923c', '#38bdf8', '#f472b6', '#a3e635', '#e7c26a'];

/** 竖向堆叠柱：每天一根，按模型分色，图例在下方。 */
export default function UsageChart({ models, series }: { models: string[]; series: UsagePoint[] }) {
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<ECharts | null>(null);

  useEffect(() => {
    const node = host.current;
    if (!node) return;
    const instance = echarts.init(node, undefined, { renderer: 'canvas' });
    chart.current = instance;
    const onResize = () => instance.resize();
    window.addEventListener('resize', onResize);
    const observer = new ResizeObserver(onResize);
    observer.observe(node);
    return () => {
      window.removeEventListener('resize', onResize);
      observer.disconnect();
      instance.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    const instance = chart.current;
    if (!instance) return;
    const names = models.length ? models : ['未记模型'];
    instance.setOption({
      backgroundColor: 'transparent',
      color: COLORS,
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: '#1b2234',
        borderColor: '#232c40',
        textStyle: { color: '#e6eaf2', fontSize: 14 },
        formatter: (items: Array<{ axisValue: string; marker: string; seriesName: string; value: number }>) => {
          const head = items[0]?.axisValue ?? '';
          const lines = items
            .filter((item) => item.value)
            .map((item) => `${item.marker}${item.seriesName}　${fmtTokens(item.value)}`);
          const total = items.reduce((sum, item) => sum + (Number(item.value) || 0), 0);
          return [`${head}`, ...lines, `合计　${fmtTokens(total)}`].join('<br/>');
        },
      },
      legend: {
        bottom: 0,
        icon: 'circle',
        itemWidth: 10,
        itemHeight: 10,
        textStyle: { color: '#a2acc2', fontSize: 14 },
      },
      grid: { left: 56, right: 12, top: 16, bottom: names.length > 4 ? 72 : 48 },
      xAxis: {
        type: 'category',
        data: series.map((point) => point.date.slice(5)),
        axisLabel: { color: '#a2acc2', fontSize: 13 },
        axisLine: { lineStyle: { color: '#232c40' } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: '#a2acc2', fontSize: 13, formatter: (value: number) => fmtTokens(value) },
        splitLine: { lineStyle: { color: '#232c40' } },
      },
      series: names.map((name, index) => ({
        name,
        type: 'bar',
        stack: 'usage',
        barMaxWidth: 28,
        itemStyle: { color: COLORS[index % COLORS.length] },
        data: series.map((point) => point.by_model?.[name] ?? (names.length === 1 && name === '未记模型' ? point.tokens : 0)),
      })),
    }, true);
  }, [models, series]);

  return <div className="admin-usage-chart" ref={host} />;
}
