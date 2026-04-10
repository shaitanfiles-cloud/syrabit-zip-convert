import { useRef, useState, useCallback } from 'react';
import {
  ArrowLeft, Save, Loader2, Eye, Link2, BarChart3,
  Sparkles, RefreshCw, Layers, LayoutTemplate, Upload,
  FileText, Globe, Paperclip, CheckCircle, Smartphone, Monitor,
  ImagePlus,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import axios from 'axios';
import { toast } from 'sonner';
import { TEMPLATES } from '@/utils/editorTemplates';
import { API, autoSlug, authHeaders } from '@/utils/adminHelpers';
import PYQUploadPanel from './PYQUploadPanel';
import {
  MDXEditor,
  headingsPlugin, listsPlugin, quotePlugin, thematicBreakPlugin,
  markdownShortcutPlugin, codeBlockPlugin, codeMirrorPlugin, tablePlugin,
  linkPlugin, diffSourcePlugin, toolbarPlugin, imagePlugin,
  UndoRedo, BoldItalicUnderlineToggles, BlockTypeSelect,
  CreateLink, CodeToggle, InsertTable, InsertThematicBreak,
  ListsToggle, Separator, DiffSourceToggleWrapper, InsertCodeBlock,
  InsertImage,
} from '@mdxeditor/editor';
import '@mdxeditor/editor/style.css';

const CONTENT_TYPES = [
  { value: 'notes', label: 'Notes', color: 'violet' },
  { value: 'pyq', label: 'PYQ', color: 'amber' },
  { value: 'formula', label: 'Formula Sheet', color: 'pink' },
  { value: 'summary', label: 'Summary', color: 'emerald' },
  { value: 'solution', label: 'Solution', color: 'blue' },
  { value: 'reference', label: 'Reference', color: 'slate' },
];

export default function ChapterEditForm({
  editView, editTarget, contentForm, setContentForm,
  subjectData, saving, chapterStats,
  onSave, onCancel, onFileAttach, uploading,
  onAiParse, aiParsing, onLoadChapterStats,
  editorRef, editorKey, setEditorKey,
  showPreview, setShowPreview,
  fileInputRef,
  adminToken, boardId, classId, streamId,
}) {
  const [mobilePreview, setMobilePreview] = useState(true);
  const imgInputRef = useRef(null);

  const [imgUploading, setImgUploading] = useState(false);

  const imageUploadHandler = useCallback(async (image) => {
    const formData = new FormData();
    formData.append('file', image);
    try {
      const res = await axios.post(`${API}/admin/content/upload-image`, formData, {
        ...authHeaders(adminToken),
        headers: { ...authHeaders(adminToken).headers, 'Content-Type': 'multipart/form-data' },
      });
      return res.data.url;
    } catch (e) {
      toast.error('Image upload failed');
      throw e;
    }
  }, [adminToken]);

  const handleAddPages = useCallback(() => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*';
    input.multiple = true;
    input.onchange = async (e) => {
      const files = Array.from(e.target.files || []);
      if (!files.length) return;
      const oversized = files.filter(f => f.size > 10 * 1024 * 1024);
      if (oversized.length) {
        toast.error(`${oversized.length} image(s) exceed 10 MB limit`);
        return;
      }
      setImgUploading(true);
      const toastId = toast.loading(`Uploading ${files.length} page(s)...`);
      try {
        const urls = [];
        for (let i = 0; i < files.length; i++) {
          toast.loading(`Uploading page ${i + 1} of ${files.length}...`, { id: toastId });
          const url = await imageUploadHandler(files[i]);
          urls.push({ name: files[i].name, url });
        }
        const md = editorRef.current?.getMarkdown?.() ?? contentForm.content;
        const pagesMd = urls.map((u, i) => `![Page ${i + 1}](${u.url})`).join('\n\n');
        setContentForm(f => ({ ...f, content: md + (md.trim() ? '\n\n' : '') + pagesMd + '\n' }));
        setEditorKey(k => k + 1);
        toast.success(`${urls.length} page(s) added`, { id: toastId });
      } catch {
        toast.error('Some pages failed to upload', { id: toastId });
      } finally {
        setImgUploading(false);
      }
    };
    input.click();
  }, [imageUploadHandler, editorRef, contentForm, setContentForm, setEditorKey]);

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="px-8 pt-7 pb-4 flex-shrink-0">
        <button onClick={onCancel} className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-900 mb-5"><ArrowLeft size={16} /> Back</button>
        <h3 className="text-2xl font-bold text-gray-900 mb-0.5">{editView === 'edit-chapter' ? 'Edit Chapter' : 'Create Chapter'}</h3>
        <p className="text-gray-500 text-sm">for {subjectData?.name}</p>
      </div>
      <div className="flex-1 flex flex-col min-h-0 px-8 pb-8 gap-4">
        <div className="flex-shrink-0 grid grid-cols-1 lg:grid-cols-2 gap-3">
          <div>
            <label className="text-sm text-gray-500 block mb-1.5">Title *</label>
            <input value={contentForm.title} onChange={(e) => { const title = e.target.value; setContentForm(f => ({ ...f, title, slug: f.slug === autoSlug(f.title) || !f.slug ? autoSlug(title) : f.slug })); }} placeholder="Chapter title" className="w-full h-11 px-4 rounded-xl text-gray-900 bg-gray-50 border border-gray-200 outline-none focus:border-violet-500" />
          </div>
          <div>
            <label className="text-sm text-gray-500 block mb-1.5">URL Slug</label>
            <div className="flex items-center gap-2">
              <div className="flex items-center flex-1 h-11 rounded-xl bg-gray-50 border border-gray-200 overflow-hidden">
                <span className="px-3 text-xs text-gray-400 flex-shrink-0"><Link2 size={12} /></span>
                <input value={contentForm.slug} onChange={(e) => setContentForm({ ...contentForm, slug: e.target.value })} placeholder="auto-generated-slug" className="flex-1 h-full text-sm text-gray-900 bg-transparent outline-none font-mono pr-3" />
              </div>
            </div>
          </div>
        </div>
        <div className="flex-shrink-0 grid grid-cols-1 lg:grid-cols-2 gap-3">
          <div>
            <label className="text-sm text-gray-500 block mb-1.5">Content Type</label>
            <div className="flex flex-wrap gap-1.5">
              {CONTENT_TYPES.map(ct => (
                <button
                  key={ct.value}
                  onClick={() => setContentForm(f => ({ ...f, content_type: ct.value }))}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all border ${contentForm.content_type === ct.value ? 'border-violet-500 bg-violet-500/20 text-violet-300' : 'border-gray-200 bg-gray-50 text-gray-500 hover:text-gray-900 hover:border-gray-200'}`}
                >
                  {ct.label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="text-sm text-gray-500 block mb-1.5">Description</label>
            <input value={contentForm.description} onChange={(e) => setContentForm({ ...contentForm, description: e.target.value })} placeholder="Brief description..." className="w-full h-11 px-4 rounded-xl text-gray-900 bg-gray-50 border border-gray-200 outline-none focus:border-violet-500" />
          </div>
        </div>

        <div className="flex-shrink-0">
          <label className="text-sm text-gray-500 block mb-1.5">Topics <span className="text-gray-400">(used for AI embeddings — comma-separated)</span></label>
          <input
            value={(contentForm.topics || []).join(', ')}
            onChange={(e) => {
              const topics = e.target.value.split(',').map(t => t.trim()).filter(Boolean);
              setContentForm(f => ({ ...f, topics }));
            }}
            placeholder="e.g. Photosynthesis, Carbon cycle, Nitrogen fixation"
            className="w-full h-11 px-4 rounded-xl text-gray-900 bg-gray-50 border border-gray-200 outline-none focus:border-violet-500 text-sm"
          />
          {(contentForm.topics || []).length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-2">
              {contentForm.topics.map((topic, i) => (
                <span key={i} className="px-2 py-0.5 rounded-full text-[11px] bg-violet-500/15 text-violet-300 border border-violet-500/20">
                  {topic}
                  <button onClick={() => setContentForm(f => ({ ...f, topics: f.topics.filter((_, j) => j !== i) }))} className="ml-1 text-gray-400 hover:text-gray-500">×</button>
                </span>
              ))}
            </div>
          )}
        </div>

        {chapterStats && (
          <div className="flex-shrink-0 flex items-center gap-3 px-4 py-2.5 rounded-xl bg-gray-50 border border-gray-200 text-xs flex-wrap">
            <div className="flex items-center gap-1.5 text-gray-500">
              <BarChart3 size={12} className="text-violet-400" />
              <span>{chapterStats.chunk_count} chunks</span>
            </div>
            <div className="text-gray-400">{chapterStats.content_length?.toLocaleString()} chars</div>
            {chapterStats.notes_generated && (
              <div className="flex items-center gap-1 text-emerald-400"><CheckCircle size={11} />Notes</div>
            )}
            {(chapterStats.pyq_count || 0) > 0 && (
              <div className="flex items-center gap-1 text-amber-400"><FileText size={11} />{chapterStats.pyq_count} PYQs</div>
            )}
            {(chapterStats.flashcard_count || 0) > 0 && (
              <div className="flex items-center gap-1 text-emerald-400"><Layers size={11} />{chapterStats.flashcard_count} cards</div>
            )}
            {(chapterStats.geo_blog_count || 0) > 0 && (
              <div className="flex items-center gap-1 text-blue-400"><Globe size={11} />{chapterStats.geo_blog_count} blogs</div>
            )}
            {(chapterStats.attached_files || []).length > 0 && (
              <div className="flex items-center gap-1 text-blue-400"><Paperclip size={11} />{chapterStats.attached_files.length} files</div>
            )}
            <button onClick={() => onLoadChapterStats(editTarget?.id)} className="ml-auto text-gray-400 hover:text-gray-900 p-1"><RefreshCw size={11} /></button>
          </div>
        )}

        {editView === 'edit-chapter' && editTarget?.id && (
          <div className="flex-shrink-0">
            <PYQUploadPanel
              adminToken={adminToken}
              chapterId={editTarget.id}
              subjectId={subjectData?.id || ''}
              boardId={boardId || ''}
              classId={classId || ''}
              streamId={streamId || ''}
            />
          </div>
        )}
        <div className="flex-1 flex flex-col min-h-0">
          <div className="flex items-center gap-1.5 mb-2 flex-shrink-0 flex-wrap">
            <LayoutTemplate size={11} className="text-gray-300 flex-shrink-0" />
            <span className="text-[10px] text-gray-400 flex-shrink-0 mr-0.5">Insert:</span>
            {TEMPLATES.map(t => (
              <button
                key={t.label}
                onClick={() => {
                  const current = editorRef.current?.getMarkdown?.() ?? contentForm.content;
                  setContentForm(f => ({ ...f, content: current + t.shortcode }));
                  setEditorKey(k => k + 1);
                }}
                className="px-2 py-0.5 rounded text-[10px] border border-gray-200 bg-gray-50 text-gray-400 hover:text-violet-300 hover:border-violet-500/40 transition-colors"
              >
                {t.label}
              </button>
            ))}
            <div className="ml-auto flex items-center gap-2">
              <span className="text-[10px] text-gray-300">{contentForm.content.length}ch</span>
              <button
                onClick={() => setMobilePreview(p => !p)}
                className={`flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-medium border transition-colors ${
                  mobilePreview
                    ? 'bg-violet-600/25 text-violet-300 border-violet-500/30'
                    : 'bg-gray-50 text-gray-400 border-gray-200 hover:text-gray-900'
                }`}
                title={mobilePreview ? 'Switch to desktop width' : 'Switch to mobile width'}
              >
                {mobilePreview ? <Smartphone size={10} /> : <Monitor size={10} />}
                {mobilePreview ? 'Mobile' : 'Desktop'}
              </button>
              <button
                onClick={() => setShowPreview(p => !p)}
                className={`flex items-center gap-1 px-2.5 py-1 rounded-lg text-[10px] font-medium border transition-colors ${
                  showPreview
                    ? 'bg-violet-600/25 text-violet-300 border-violet-500/30'
                    : 'bg-gray-50 text-gray-400 border-gray-200 hover:text-gray-900'
                }`}
              >
                <Eye size={10} />
                {showPreview ? 'Hide Preview' : 'Preview'}
              </button>
            </div>
          </div>

          <div className={`flex-1 min-h-0 flex gap-3 ${showPreview ? '' : 'flex-col'}`}>
            <div
              className={`min-h-0 rounded-xl overflow-hidden border cms-light-editor-wrapper flex flex-col transition-all duration-300 ${
                mobilePreview
                  ? 'mx-auto border-2 border-gray-300 shadow-lg'
                  : 'flex-1 border-black/10'
              }`}
              data-color-mode="light"
              style={{
                backgroundColor: '#ffffff',
                color: '#1a1a1a',
                ...(mobilePreview ? {
                  width: 390,
                  maxWidth: '100%',
                  borderRadius: 28,
                  boxShadow: '0 0 0 3px #e5e7eb, 0 8px 32px rgba(0,0,0,0.12)',
                } : {}),
              }}
            >
              {mobilePreview && (
                <div className="flex items-center justify-center py-1.5 bg-gray-100 border-b border-gray-200">
                  <div className="w-16 h-1 rounded-full bg-gray-300" />
                </div>
              )}
              <MDXEditor
                ref={editorRef}
                key={`${editTarget?.id ?? '__new__'}-${editorKey}`}
                markdown={contentForm.content}
                onChange={md => setContentForm(f => ({ ...f, content: md }))}
                className="mdx-editor-light h-full"
                contentEditableClassName="cms-editor-content"
                plugins={[
                  headingsPlugin(),
                  listsPlugin(),
                  quotePlugin(),
                  thematicBreakPlugin(),
                  markdownShortcutPlugin(),
                  codeBlockPlugin({ defaultCodeBlockLanguage: 'text' }),
                  codeMirrorPlugin({
                    codeBlockLanguages: {
                      js: 'JavaScript', ts: 'TypeScript', python: 'Python',
                      text: 'Text', md: 'Markdown', html: 'HTML', css: 'CSS',
                    },
                  }),
                  tablePlugin(),
                  linkPlugin(),
                  imagePlugin({ imageUploadHandler }),
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
                        <InsertImage />
                        <button
                          type="button"
                          onClick={handleAddPages}
                          disabled={imgUploading}
                          title="Add question paper pages (select multiple images)"
                          style={{
                            display: 'flex', alignItems: 'center', gap: 4,
                            padding: '2px 10px', borderRadius: 4, fontSize: 11, fontWeight: 600,
                            color: '#f59e0b', background: 'rgba(245,158,11,0.10)',
                            border: '1px solid rgba(245,158,11,0.20)',
                            cursor: imgUploading ? 'not-allowed' : 'pointer',
                            opacity: imgUploading ? 0.5 : 1,
                          }}
                        >
                          {imgUploading
                            ? <Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} />
                            : <ImagePlus size={12} />}
                          Add Pages
                        </button>
                        <InsertTable />
                        <InsertThematicBreak />
                        <InsertCodeBlock />
                        <Separator />
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
                      </DiffSourceToggleWrapper>
                    ),
                  }),
                ]}
              />
              {mobilePreview && (
                <div className="flex items-center justify-center py-1 bg-gray-100 border-t border-gray-200">
                  <div className="w-24 h-1 rounded-full bg-gray-300" />
                </div>
              )}
            </div>
            {showPreview && (
              <div
                className={`min-h-0 overflow-y-auto transition-all duration-300 ${
                  mobilePreview ? 'mx-auto border-2 border-gray-300 shadow-lg' : 'flex-1 rounded-xl'
                }`}
                style={{
                  background: '#f0f0f1',
                  ...(mobilePreview ? {
                    width: 390,
                    maxWidth: '100%',
                    borderRadius: 28,
                    boxShadow: '0 0 0 3px #e5e7eb, 0 8px 32px rgba(0,0,0,0.12)',
                  } : {}),
                }}
              >
                {mobilePreview && (
                  <div className="flex items-center justify-center py-1.5 bg-gray-100 border-b border-gray-200" style={{ borderRadius: '28px 28px 0 0' }}>
                    <div className="w-16 h-1 rounded-full bg-gray-300" />
                  </div>
                )}
                <div style={{ background: '#ffffff', color: '#1a1a1a', fontSize: '15px', lineHeight: '1.75', padding: '1.5rem 1.25rem', minHeight: '100%' }}>
                  {contentForm.content.trim() ? (
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {contentForm.content}
                    </ReactMarkdown>
                  ) : (
                    <p style={{ color: '#aaa', fontStyle: 'italic' }}>Preview appears here as you type…</p>
                  )}
                </div>
                {mobilePreview && (
                  <div className="flex items-center justify-center py-1 bg-gray-100 border-t border-gray-200" style={{ borderRadius: '0 0 28px 28px' }}>
                    <div className="w-24 h-1 rounded-full bg-gray-300" />
                  </div>
                )}
              </div>
            )}
          </div>

          {editView === 'edit-chapter' && editTarget?.id && (
            <div className="flex items-center gap-3 mt-2 flex-shrink-0">
              <input ref={fileInputRef} type="file" accept=".pdf,.txt,.md" className="hidden" onChange={() => onFileAttach(editTarget.id)} />
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
                className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-blue-400 hover:text-blue-300 hover:bg-blue-500/10 transition-colors text-xs font-medium disabled:opacity-40"
              >
                {uploading ? <Loader2 size={12} className="animate-spin" /> : <Upload size={12} />}
                Attach File (PDF / TXT / MD)
              </button>
              {chapterStats && (
                <span className="text-[11px] text-gray-400">{chapterStats.chunk_count} chunks · {chapterStats.content_length?.toLocaleString()} chars</span>
              )}
            </div>
          )}
        </div>
        <div className="flex gap-3 flex-shrink-0">
          <button onClick={onCancel} className="flex-1 h-12 rounded-xl bg-gray-50 hover:bg-gray-100 text-gray-900 font-medium">Cancel</button>
          <button
            onClick={onSave}
            disabled={saving || !contentForm.title}
            className="flex-1 h-12 rounded-xl bg-violet-600 hover:bg-violet-500 text-gray-900 font-semibold disabled:opacity-40 flex items-center justify-center gap-2"
          >
            {saving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
            {saving ? 'Saving...' : editView === 'edit-chapter' ? 'Update Chapter' : 'Create Chapter'}
          </button>
        </div>
      </div>
    </div>
  );
}
