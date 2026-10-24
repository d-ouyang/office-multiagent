// 官方 echarts 画在主线程的 canvas 上。办公图表是汇总后的几十个点，初始化是毫秒级，
// 不放进 Worker：ECharts 要碰 DOM，Worker 里没有 document。OffscreenCanvas 也盖不住交互。
// 这里只在 spec 变化时 setOption 一次，流式打字不会把图反复建掉。
import { memo, useEffect, useRef } from 'react';
import { BarChart, HeatmapChart, LineChart, PieChart, ScatterChart } from 'echarts/charts';
import {
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components';
import * as echarts from 'echarts/core';
import type { ECharts, EChartsCoreOption } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([
  BarChart,
  HeatmapChart,
  LineChart,
  PieChart,
  ScatterChart,
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
  VisualMapComponent,
  CanvasRenderer,
]);

export interface ChartSpec {
  kind: 'chart';
  chart: string;
  title?: string;
  labels?: string[];
  values?: number[];
  series?: { name: string; data: number[] }[];
  xlabel?: string;
  ylabel?: string;
  points?: number[][];
  bins?: number;
  xlabels?: string[];
  ylabels?: string[];
  grid?: Array<Array<number | null>>;
}

const COLORS = ['#5B8FF9', '#5AD8A6', '#5D7092', '#F6BD16', '#E8684A', '#6DC8EC', '#9270CA', '#FF9D4D'];

function pointCount(spec: ChartSpec): number {
  if (spec.points) return spec.points.length;
  if (spec.values) return spec.values.length;
  if (spec.grid) return spec.grid.reduce((sum, row) => sum + row.length, 0);
  return (spec.series || []).reduce((sum, item) => sum + item.data.length, 0);
}

export function toOption(spec: ChartSpec): EChartsCoreOption {
  const animate = pointCount(spec) <= 300;
  const base = {
    color: COLORS,
    animation: animate,
    backgroundColor: 'transparent',
    title: { text: spec.title || '', left: 'center', textStyle: { color: '#1F2937', fontSize: 14, fontWeight: 600 } },
    tooltip: { trigger: spec.chart === 'pie' ? 'item' : 'axis' },
    grid: { left: 48, right: 24, top: 48, bottom: 36 },
  } as EChartsCoreOption;
  if (spec.chart === 'pie') {
    return {
      ...base,
      series: [{
        type: 'pie',
        radius: ['36%', '68%'],
        data: (spec.labels || []).map((name, index) => ({ name, value: spec.values?.[index] ?? 0 })),
      }],
    };
  }
  if (spec.chart === 'scatter') {
    return {
      ...base,
      xAxis: { name: spec.xlabel, type: 'value' },
      yAxis: { name: spec.ylabel, type: 'value' },
      series: [{ type: 'scatter', data: spec.points || [] }],
    };
  }
  if (spec.chart === 'hist') {
    const values = spec.values || [];
    const count = Math.max(3, spec.bins || 10);
    const min = values.length ? Math.min(...values) : 0;
    const max = values.length ? Math.max(...values) : 1;
    const step = (max - min) / count || 1;
    const data = new Array(count).fill(0);
    values.forEach((value) => {
      let index = Math.floor((value - min) / step);
      if (index >= count) index = count - 1;
      data[index] += 1;
    });
    const labels = data.map((_, index) => (min + index * step).toFixed(1));
    return {
      ...base,
      xAxis: { type: 'category', data: labels, name: spec.xlabel },
      yAxis: { type: 'value' },
      series: [{ type: 'bar', data, barWidth: '92%' }],
    };
  }
  if (spec.chart === 'heatmap') {
    const data: Array<[number, number, number | null]> = [];
    (spec.grid || []).forEach((row, y) => row.forEach((value, x) => data.push([x, y, value])));
    return {
      ...base,
      tooltip: { position: 'top' },
      xAxis: { type: 'category', data: spec.xlabels || [] },
      yAxis: { type: 'category', data: spec.ylabels || [] },
      visualMap: { min: 0, max: Math.max(1, ...data.map((item) => item[2] || 0)), orient: 'horizontal', left: 'center', bottom: 0 },
      series: [{ type: 'heatmap', data }],
    };
  }
  const horizontal = spec.chart === 'barh';
  const categories = spec.labels || [];
  const valueAxis = { type: 'value' as const, name: spec.ylabel };
  const categoryAxis = { type: 'category' as const, data: categories };
  return {
    ...base,
    legend: { top: 26 },
    xAxis: horizontal ? valueAxis : categoryAxis,
    yAxis: horizontal ? categoryAxis : valueAxis,
    series: (spec.series || []).map((item) => ({
      name: item.name,
      type: spec.chart === 'line' || spec.chart === 'area' ? 'line' : 'bar',
      areaStyle: spec.chart === 'area' ? {} : undefined,
      smooth: spec.chart === 'line' || spec.chart === 'area',
      data: item.data,
    })),
  };
}

function ChartViewInner({ spec }: { spec: ChartSpec }) {
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<ECharts | null>(null);
  const signature = JSON.stringify(spec);

  useEffect(() => {
    if (!host.current) return;
    if (!chart.current) {
      chart.current = echarts.init(host.current, undefined, { renderer: 'canvas' });
    }
    chart.current.setOption(toOption(spec), true);
  }, [signature, spec]);

  useEffect(() => {
    const onResize = () => chart.current?.resize();
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);

  return (
    <div className="chart-card">
      <div ref={host} className="chart-host" />
    </div>
  );
}

export const ChartView = memo(ChartViewInner);
