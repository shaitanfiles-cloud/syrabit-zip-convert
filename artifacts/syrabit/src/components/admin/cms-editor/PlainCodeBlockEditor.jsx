import { useRef, useEffect } from 'react';
import { useCodeBlockEditorContext } from '@mdxeditor/editor';

const LANGUAGE_OPTIONS = [
  { value: 'text', label: 'Text' },
  { value: 'js', label: 'JavaScript' },
  { value: 'ts', label: 'TypeScript' },
  { value: 'json', label: 'JSON' },
  { value: 'md', label: 'Markdown' },
  { value: 'html', label: 'HTML' },
  { value: 'css', label: 'CSS' },
  { value: 'sql', label: 'SQL' },
];

function PlainCodeBlockEditor({ language, code, nodeKey }) {
  const { parentEditor, lexicalNode, setCode } = useCodeBlockEditorContext();
  const taRef = useRef(null);

  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    const fit = () => {
      ta.style.height = 'auto';
      ta.style.height = Math.max(ta.scrollHeight, 48) + 'px';
    };
    fit();
  }, [code]);

  return (
    <div
      className="mdx-plain-code-block"
      style={{
        border: '1px solid #e2e8f0',
        borderRadius: 8,
        background: '#0f172a',
        margin: '12px 0',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '6px 10px',
          background: '#1e293b',
          borderBottom: '1px solid #334155',
        }}
      >
        <select
          value={language || 'text'}
          onChange={(e) => {
            const next = e.target.value;
            parentEditor.update(() => {
              lexicalNode.setLanguage(next);
            });
          }}
          style={{
            background: '#0f172a',
            color: '#e2e8f0',
            border: '1px solid #334155',
            borderRadius: 4,
            fontSize: 11,
            padding: '2px 6px',
            outline: 'none',
          }}
        >
          {LANGUAGE_OPTIONS.find((o) => o.value === language) ? null : (
            <option value={language || ''}>{language || 'text'}</option>
          )}
          {LANGUAGE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>
      <textarea
        ref={taRef}
        defaultValue={code}
        spellCheck={false}
        wrap="off"
        onChange={(e) => {
          setCode(e.target.value);
        }}
        onKeyDown={(e) => {
          if (e.key === 'Tab') {
            e.preventDefault();
            const ta = e.currentTarget;
            const start = ta.selectionStart;
            const end = ta.selectionEnd;
            const v = ta.value;
            const next = v.slice(0, start) + '  ' + v.slice(end);
            ta.value = next;
            ta.selectionStart = ta.selectionEnd = start + 2;
            setCode(next);
          }
          e.stopPropagation();
        }}
        style={{
          display: 'block',
          width: '100%',
          minHeight: 48,
          padding: '10px 12px',
          background: '#0f172a',
          color: '#e2e8f0',
          border: 'none',
          outline: 'none',
          resize: 'vertical',
          fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
          fontSize: 12.5,
          lineHeight: 1.55,
          tabSize: 2,
          whiteSpace: 'pre',
          overflowX: 'auto',
        }}
        data-node-key={nodeKey}
      />
    </div>
  );
}

export const plainCodeBlockDescriptor = {
  priority: 1000,
  match: () => true,
  Editor: PlainCodeBlockEditor,
};
