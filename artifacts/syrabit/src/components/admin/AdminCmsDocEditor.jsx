import '@mdxeditor/editor/style.css';
import { Plus, BookOpen, Edit2, Tag, Globe, ExternalLink } from 'lucide-react';
import useCmsEditor from './cms-editor/useCmsEditor';
import DocumentList from './cms-editor/DocumentList';
import EditorToolbar from './cms-editor/EditorToolbar';
import ContentTab from './cms-editor/ContentTab';
import SeoMetaTab from './cms-editor/SeoMetaTab';
import GeoTagsTab from './cms-editor/GeoTagsTab';

export default function AdminCmsDocEditor({ adminToken, onNavigate, hubContext }) {
  const ctx = useCmsEditor(adminToken, onNavigate, hubContext);

  return (
    <div className="h-full flex overflow-hidden" style={{ background: '#121212' }}>
      <DocumentList
        docs={ctx.docs} loading={ctx.loading} filtered={ctx.filtered}
        searchQ={ctx.searchQ} setSearchQ={ctx.setSearchQ}
        filterType={ctx.filterType} setFilterType={ctx.setFilterType}
        editDoc={ctx.editDoc} openNew={ctx.openNew} openEdit={ctx.openEdit} handleDelete={ctx.handleDelete}
      />

      {!ctx.inEditor ? (
        <div className="flex-1 flex items-center justify-center" style={{ color: 'rgba(232,232,232,0.40)' }}>
          <div className="text-center">
            <BookOpen size={36} className="mx-auto mb-4" style={{ color: 'rgba(255,255,255,0.10)' }} />
            <p className="text-sm mb-1">Select a document or create a new one</p>
            <button onClick={ctx.openNew} className="mt-3 h-9 px-4 rounded-xl text-sm font-medium flex items-center gap-2 mx-auto" style={{ background: '#9575e0', color: 'white' }}>
              <Plus size={14} /> New Document
            </button>
          </div>
        </div>
      ) : (
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          <EditorToolbar
            form={ctx.form} editDoc={ctx.editDoc} linkedScopeLabel={ctx.linkedScopeLabel}
            handleTitleChange={ctx.handleTitleChange} handleSave={ctx.handleSave}
            handlePublishToggle={ctx.handlePublishToggle}
            handleSaveRevision={ctx.handleSaveRevision} handleHandOff={ctx.handleHandOff}
            saving={ctx.saving} publishing={ctx.publishing} savingRevision={ctx.savingRevision}
            pdfLoading={ctx.pdfLoading} showPreview={ctx.showPreview} setShowPreview={ctx.setShowPreview}
            pdfRef={ctx.pdfRef} handlePdfUpload={ctx.handlePdfUpload}
            aiPaletteOpen={ctx.aiPaletteOpen} setAiPaletteOpen={ctx.setAiPaletteOpen} setAiPaletteResult={ctx.setAiPaletteResult}
            translateOpen={ctx.translateOpen} setTranslateOpen={ctx.setTranslateOpen} setTranslateResult={ctx.setTranslateResult}
          />

          <div className="flex-shrink-0 border-b flex gap-0" style={{ background: 'rgba(255,255,255,0.012)', borderColor: 'rgba(255,255,255,0.07)' }}>
            {[
              { id: 'content', label: 'Content',    icon: Edit2 },
              { id: 'seo',     label: 'SEO & Meta', icon: Tag },
              { id: 'geo',     label: 'GEO Tags',   icon: Globe },
            ].map(t => (
              <button key={t.id} onClick={() => ctx.setSeoTab(t.id)}
                className="flex items-center gap-1.5 px-5 py-3 text-xs font-medium border-b-2 transition-colors"
                style={{ borderBottomColor: ctx.seoTab === t.id ? '#9575e0' : 'transparent', color: ctx.seoTab === t.id ? '#c4b0f0' : 'rgba(255,255,255,0.35)' }}>
                <t.icon size={12} />
                {t.label}
              </button>
            ))}
            <div className="ml-auto flex items-center px-4 gap-3">
              {ctx.form.content && (
                <span className="text-[10px]" style={{ color: 'rgba(255,255,255,0.20)' }}>
                  {ctx.form.content.split(/\s+/).filter(Boolean).length}w · {ctx.form.content.length}ch
                </span>
              )}
              {ctx.editDoc && ctx.form.seo_slug && (
                <a href={`/learn/${ctx.form.seo_slug}`} target="_blank" rel="noreferrer"
                  className="flex items-center gap-1 text-[10px] transition-colors"
                  style={{ color: 'rgba(255,255,255,0.25)' }}
                  onMouseEnter={e => e.currentTarget.style.color = '#c4b0f0'}
                  onMouseLeave={e => e.currentTarget.style.color = 'rgba(255,255,255,0.25)'}>
                  <ExternalLink size={10} /> View
                </a>
              )}
            </div>
          </div>

          {ctx.seoTab === 'content' && (
            <ContentTab
              form={ctx.form} setForm={ctx.setForm} editDoc={ctx.editDoc} editorRef={ctx.editorRef}
              handleAiParse={ctx.handleAiParse} aiParsing={ctx.aiParsing} canPreview={ctx.canPreview}
              syllabusOpen={ctx.syllabusOpen} setSyllabusOpen={ctx.setSyllabusOpen}
              spBoard={ctx.spBoard} setSpBoard={ctx.setSpBoard} spBoards={ctx.spBoards}
              spClass={ctx.spClass} setSpClass={ctx.setSpClass} spClasses={ctx.spClasses}
              spStream={ctx.spStream} setSpStream={ctx.setSpStream} spStreams={ctx.spStreams}
              spSubject={ctx.spSubject} setSpSubject={ctx.setSpSubject} spSubjects={ctx.spSubjects}
              syllabusInserting={ctx.syllabusInserting} handleInsertSyllabus={ctx.handleInsertSyllabus}
              translateOpen={ctx.translateOpen} setTranslateOpen={ctx.setTranslateOpen}
              translateLang={ctx.translateLang} setTranslateLang={ctx.setTranslateLang}
              translating={ctx.translating} handleTranslate={ctx.handleTranslate}
              translateResult={ctx.translateResult} setTranslateResult={ctx.setTranslateResult}
              aiPaletteOpen={ctx.aiPaletteOpen} setAiPaletteOpen={ctx.setAiPaletteOpen}
              aiPaletteText={ctx.aiPaletteText} setAiPaletteText={ctx.setAiPaletteText}
              aiPaletteAction={ctx.aiPaletteAction} setAiPaletteAction={ctx.setAiPaletteAction}
              aiPaletteResult={ctx.aiPaletteResult} setAiPaletteResult={ctx.setAiPaletteResult}
              aiPaletteLoading={ctx.aiPaletteLoading} handleAiPalette={ctx.handleAiPalette}
              applyAiPaletteResult={ctx.applyAiPaletteResult} selectStyle={ctx.selectStyle}
            />
          )}

          {ctx.seoTab === 'seo' && (
            <SeoMetaTab
              form={ctx.form} setForm={ctx.setForm} editDoc={ctx.editDoc}
              seoGenerating={ctx.seoGenerating} handleGenerateSeoMeta={ctx.handleGenerateSeoMeta}
              seoResult={ctx.seoResult} setSeoResult={ctx.setSeoResult} applySeoResult={ctx.applySeoResult}
              handleAutoKeyword={ctx.handleAutoKeyword}
            />
          )}

          {ctx.seoTab === 'geo' && (
            <GeoTagsTab
              form={ctx.form} setForm={ctx.setForm} editDoc={ctx.editDoc}
              handleAutoGeoTags={ctx.handleAutoGeoTags} handleLinkSyllabus={ctx.handleLinkSyllabus}
              linkedScopeLabel={ctx.linkedScopeLabel} linkingScope={ctx.linkingScope}
              scopePickerOpen={ctx.scopePickerOpen} setScopePickerOpen={ctx.setScopePickerOpen}
              spBoard={ctx.spBoard} setSpBoard={ctx.setSpBoard} spBoards={ctx.spBoards}
              spClass={ctx.spClass} setSpClass={ctx.setSpClass} spClasses={ctx.spClasses}
              spStream={ctx.spStream} setSpStream={ctx.setSpStream} spStreams={ctx.spStreams}
              spSubject={ctx.spSubject} setSpSubject={ctx.setSpSubject} spSubjects={ctx.spSubjects}
              selectStyle={ctx.selectStyle}
            />
          )}
        </div>
      )}

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
