import { forwardRef, useRef, useImperativeHandle } from 'react';
import {
  MDXEditor,
  headingsPlugin, listsPlugin, quotePlugin, thematicBreakPlugin,
  markdownShortcutPlugin, codeBlockPlugin, tablePlugin,
  linkPlugin, diffSourcePlugin, toolbarPlugin,
  UndoRedo, BoldItalicUnderlineToggles, BlockTypeSelect,
  CreateLink, CodeToggle, InsertTable, InsertThematicBreak,
  ListsToggle, Separator, DiffSourceToggleWrapper, InsertCodeBlock,
} from '@mdxeditor/editor';
import '@mdxeditor/editor/style.css';
import { Sparkles, Loader2 } from 'lucide-react';
import { plainCodeBlockDescriptor } from '@/components/admin/cms-editor/PlainCodeBlockEditor';
export { TEMPLATES } from '@/utils/editorTemplates';

function AiBtn({ onAiParse, aiParsing }) {
  return (
    <button
      type="button"
      onClick={onAiParse}
      disabled={aiParsing}
      style={{
        display: 'flex', alignItems: 'center', gap: 4,
        padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600,
        color: '#a78bfa', background: 'rgba(167,139,250,0.10)',
        border: '1px solid rgba(167,139,250,0.20)',
        cursor: aiParsing ? 'not-allowed' : 'pointer',
        opacity: aiParsing ? 0.5 : 1,
      }}
    >
      {aiParsing
        ? <Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} />
        : <Sparkles size={12} />}
      AI
    </button>
  );
}

const SharedMdxEditor = forwardRef(function SharedMdxEditor(
  { markdown, onChange, onAiParse, aiParsing, editorKey },
  ref
) {
  const editorRef = useRef(null);

  useImperativeHandle(ref, () => ({
    getMarkdown: () => editorRef.current?.getMarkdown() ?? markdown ?? '',
    insertText: (text) => {
      const current = editorRef.current?.getMarkdown() ?? '';
      onChange?.(current + text);
    },
  }));

  return (
    <div
      className="flex-1 h-full cms-light-editor-wrapper"
      data-color-mode="light"
      style={{ backgroundColor: '#ffffff', color: '#1a1a1a' }}
    >
      <MDXEditor
        ref={editorRef}
        key={editorKey ?? 'shared-editor'}
        markdown={markdown || ''}
        onChange={onChange}
        plugins={[
          headingsPlugin(),
          listsPlugin(),
          quotePlugin(),
          thematicBreakPlugin(),
          markdownShortcutPlugin(),
          codeBlockPlugin({
            defaultCodeBlockLanguage: 'text',
            codeBlockEditorDescriptors: [plainCodeBlockDescriptor],
          }),
          tablePlugin(),
          linkPlugin(),
          diffSourcePlugin({ viewMode: 'rich-text', diffMarkdown: '' }),
          toolbarPlugin({
            toolbarContents: () => (
              <DiffSourceToggleWrapper>
                <UndoRedo />
                <Separator />
                <BoldItalicUnderlineToggles />
                <CodeToggle />
                <Separator />
                <ListsToggle />
                <Separator />
                <BlockTypeSelect />
                <Separator />
                <CreateLink />
                <InsertTable />
                <InsertThematicBreak />
                <InsertCodeBlock />
                {onAiParse && (
                  <>
                    <Separator />
                    <AiBtn onAiParse={onAiParse} aiParsing={aiParsing} />
                  </>
                )}
              </DiffSourceToggleWrapper>
            ),
          }),
        ]}
        className="mdx-editor-light h-full"
        contentEditableClassName="cms-editor-content"
      />
    </div>
  );
});

export default SharedMdxEditor;
