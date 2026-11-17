import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from 'react';
import { Modal } from 'antd';

export interface SettingsSection {
  id: string;
  label: string;
  content: ReactNode;
}

interface Props {
  open: boolean;
  sections: SettingsSection[];
  footer: ReactNode;
  onClose: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}

export function SettingsDialog({ open, sections, footer, onClose, onSubmit }: Props) {
  const [activeId, setActiveId] = useState(sections[0]?.id || '');
  const [compact, setCompact] = useState(() => typeof window !== 'undefined' && window.matchMedia('(max-width: 640px)').matches);
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const current = sections.find(section => section.id === activeId) ?? sections[0];

  useEffect(() => {
    if (!open) return;
    setActiveId(sections[0]?.id || '');
  }, [open]);

  useEffect(() => {
    const media = window.matchMedia('(max-width: 640px)');
    const update = () => setCompact(media.matches);
    update();
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);

  if (!current) return null;

  const selectTab = (id: string) => {
    setActiveId(id);
    tabRefs.current[id]?.focus();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let nextIndex: number | null = null;
    if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') nextIndex = (index - 1 + sections.length) % sections.length;
    if (event.key === 'ArrowDown' || event.key === 'ArrowRight') nextIndex = (index + 1) % sections.length;
    if (event.key === 'Home') nextIndex = 0;
    if (event.key === 'End') nextIndex = sections.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    selectTab(sections[nextIndex].id);
  };

  return <Modal open={open} title="设置" onCancel={onClose} footer={null} centered destroyOnHidden width={760} className="settings-dialog">
    <form className="settings-form" onSubmit={onSubmit}>
      <div className="settings-layout">
        <div className="settings-sidebar">
          <div className="settings-tabs" role="tablist" aria-label="设置分区" aria-orientation={compact ? 'horizontal' : 'vertical'}>
            {sections.map((section, index) => <button
              id={`settings-tab-${section.id}`}
              key={section.id}
              ref={node => { tabRefs.current[section.id] = node; }}
              type="button"
              role="tab"
              aria-selected={section.id === current.id}
              aria-controls={`settings-panel-${section.id}`}
              tabIndex={section.id === current.id ? 0 : -1}
              className={`settings-tab${section.id === current.id ? ' active' : ''}`}
              onClick={() => setActiveId(section.id)}
              onKeyDown={event => handleKeyDown(event, index)}
            >{section.label}</button>)}
          </div>
        </div>
        <div className="settings-main">
          <div
            id={`settings-panel-${current.id}`}
            className="settings-panel"
            role="tabpanel"
            aria-labelledby={`settings-tab-${current.id}`}
            tabIndex={0}
          >{current.content}</div>
          <div className="settings-footer">{footer}</div>
        </div>
      </div>
    </form>
  </Modal>;
}
