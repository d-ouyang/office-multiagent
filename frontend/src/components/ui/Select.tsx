// 统一下拉框（p6.28c）：替换管理端里的原生 <select>。
// 原生 select 的样式/交互在各浏览器不一致、也不能放说明文字；这里做一个轻量的：
// 按钮 + 浮层 + 选中态 + 可清除，键盘可达（Esc 关、上下键移动、回车选）。
import { useEffect, useId, useRef, useState } from 'react';

export interface SelectOption {
  value: string;
  label: string;
  hint?: string;
}

export default function Select({
  value,
  options,
  placeholder = '全部',
  onChange,
  width = 150,
  disabled = false,
}: {
  value: string;
  options: SelectOption[];
  placeholder?: string;
  onChange: (value: string) => void;
  width?: number;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const boxRef = useRef<HTMLDivElement>(null);
  const listId = useId();

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!boxRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', onDown);
    return () => document.removeEventListener('pointerdown', onDown);
  }, [open]);

  const current = options.find((o) => o.value === value);

  const commit = (next: string) => {
    onChange(next);
    setOpen(false);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      setOpen(false);
      return;
    }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!open) {
        setOpen(true);
        setActive(Math.max(0, options.findIndex((o) => o.value === value)));
        return;
      }
      setActive((i) => {
        const step = e.key === 'ArrowDown' ? 1 : -1;
        return Math.min(options.length - 1, Math.max(0, i + step));
      });
    }
    if (e.key === 'Enter' && open && active >= 0) {
      e.preventDefault();
      commit(options[active].value);
    }
  };

  return (
    <div className="ui-select" ref={boxRef} style={{ width }} onKeyDown={onKeyDown}>
      <button
        type="button"
        className={`ui-select-trigger ${open ? 'open' : ''} ${current ? '' : 'is-placeholder'}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        disabled={disabled}
        onClick={() => {
          setOpen((v) => !v);
          setActive(Math.max(0, options.findIndex((o) => o.value === value)));
        }}
      >
        <span className="ui-select-label">{current?.label ?? placeholder}</span>
        <span className="ui-select-caret" aria-hidden="true">▾</span>
      </button>
      {open && (
        <ul className="ui-select-menu" role="listbox" id={listId}>
          {options.map((o, i) => (
            <li
              key={o.value || '__all'}
              role="option"
              aria-selected={o.value === value}
              className={`ui-select-option ${o.value === value ? 'on' : ''} ${i === active ? 'active' : ''}`}
              onClick={() => commit(o.value)}
              onMouseEnter={() => setActive(i)}
            >
              <span>{o.label}</span>
              {o.hint && <span className="ui-select-hint">{o.hint}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
