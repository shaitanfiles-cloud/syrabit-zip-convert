import { useState } from 'react';
import { Save, Trash2, Plus, Loader2, CheckCircle, Globe, ExternalLink, Info } from 'lucide-react';
import { Link } from 'react-router-dom';

export default function EditorForm({
  loading, saving, publishing,
  canLoad, isFallback, editingSyllabus,
  formData, setFormData,
  selectedSubjectId, selectedStreamId,
  selectedSubject, selectedStream,
  scopeLabel, fallbackNotice, saveButtonLabel,
  publishedSlug,
  onSave, onDelete, onPublish,
}) {
  const [newChapter, setNewChapter] = useState('');
  const [newTopic, setNewTopic] = useState('');
  const [newGeoPhrase, setNewGeoPhrase] = useState('');

  const addChapter = () => {
    if (newChapter.trim()) {
      setFormData({ ...formData, chapters: [...formData.chapters, newChapter.trim()] });
      setNewChapter('');
    }
  };
  const removeChapter = (i) => setFormData({ ...formData, chapters: formData.chapters.filter((_, idx) => idx !== i) });

  const addTopic = () => {
    if (newTopic.trim()) {
      setFormData({ ...formData, topics: [...formData.topics, newTopic.trim()] });
      setNewTopic('');
    }
  };
  const removeTopic = (i) => setFormData({ ...formData, topics: formData.topics.filter((_, idx) => idx !== i) });

  const addGeoPhrase = () => {
    if (newGeoPhrase.trim()) {
      setFormData({ ...formData, geo_phrases: [...(formData.geo_phrases || []), newGeoPhrase.trim()] });
      setNewGeoPhrase('');
    }
  };
  const removeGeoPhrase = (i) => setFormData({ ...formData, geo_phrases: (formData.geo_phrases || []).filter((_, idx) => idx !== i) });

  return (
    <>
      {loading && (
        <div className="flex items-center gap-2 text-white/50 text-sm py-4">
          <Loader2 size={16} className="animate-spin" />
          Loading syllabus...
        </div>
      )}

      {!loading && fallbackNotice && (
        <div className="flex items-center gap-2 p-3 rounded-xl border border-amber-500/20 bg-amber-500/5 text-amber-200 text-xs">
          <Info size={14} className="flex-shrink-0" />
          {fallbackNotice}
        </div>
      )}

      {canLoad && !loading && (
        <>
          <div className="space-y-2">
            <label className="text-xs font-semibold text-white/60 uppercase tracking-wide">Syllabus Description *</label>
            <textarea
              value={formData.content}
              onChange={(e) => setFormData({ ...formData, content: e.target.value })}
              placeholder={
                selectedSubjectId
                  ? `e.g., ${selectedSubject?.name || 'Physics'} for AssamBoard covers mechanics, thermodynamics, and optics. Emphasis on board exam patterns and numerical problem-solving...`
                  : selectedStreamId
                  ? `e.g., AssamBoard ${selectedStream?.name || 'Science'} covers Physics, Chemistry, and ${selectedStream?.name?.includes('PCM') ? 'Mathematics' : 'Biology'}. Focus on conceptual understanding and AssamBoard exam patterns...`
                  : 'e.g., AssamBoard AHSEC covers Science, Arts, and Commerce streams. This syllabus serves as the general curriculum guide for all AI responses...'
              }
              className="w-full px-4 py-3 rounded-xl border border-white/10 bg-white/5 text-white placeholder-white/20 text-sm focus:border-indigo-500 outline-none transition-colors resize-none"
              rows={6}
            />
            <p className="text-[11px] text-white/30 text-right">{formData.content.length} chars</p>
          </div>

          <div className="space-y-2">
            <label className="text-xs font-semibold text-white/60 uppercase tracking-wide">Learning Guidelines <span className="text-white/30 font-normal normal-case">(optional)</span></label>
            <textarea
              value={formData.guidelines}
              onChange={(e) => setFormData({ ...formData, guidelines: e.target.value })}
              placeholder="e.g., Students should focus on deriving formulas, solving numeric problems, and understanding real-world applications. Emphasise AssamBoard exam patterns..."
              className="w-full px-4 py-3 rounded-xl border border-white/10 bg-white/5 text-white placeholder-white/20 text-sm focus:border-indigo-500 outline-none transition-colors resize-none"
              rows={3}
            />
          </div>

          <div className="space-y-2">
            <label className="text-xs font-semibold text-white/60 uppercase tracking-wide">
              GEO Authority Phrases <span className="text-white/30 font-normal normal-case">(injected into AI answers)</span>
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={newGeoPhrase}
                onChange={(e) => setNewGeoPhrase(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && addGeoPhrase()}
                placeholder='e.g., "As per AssamBoard 2024 syllabus, this topic carries 5 marks"'
                className="flex-1 px-3 py-2 rounded-lg border border-white/10 bg-white/5 text-white placeholder-white/25 text-sm focus:border-emerald-500 outline-none"
              />
              <button
                onClick={addGeoPhrase}
                className="px-3 py-2 rounded-lg bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 transition-colors"
              >
                <Plus size={16} />
              </button>
            </div>
            {(formData.geo_phrases || []).length > 0 && (
              <div className="flex flex-wrap gap-2 pt-1">
                {formData.geo_phrases.map((phrase, i) => (
                  <div key={i} className="px-3 py-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-200 text-xs flex items-center gap-2">
                    {phrase}
                    <button onClick={() => removeGeoPhrase(i)} className="hover:text-white transition-colors">
                      <Trash2 size={11} />
                    </button>
                  </div>
                ))}
              </div>
            )}
            <p className="text-[10px] text-white/25">These phrases get woven into every AI answer for this syllabus scope. Use exam stats, textbook citations, and board-authority language.</p>
          </div>

          <div className="space-y-2">
            <label className="text-xs font-semibold text-white/60 uppercase tracking-wide">Key Topics</label>
            <div className="flex gap-2">
              <input
                type="text"
                value={newTopic}
                onChange={(e) => setNewTopic(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && addTopic()}
                placeholder="Type a topic and press Enter..."
                className="flex-1 px-3 py-2 rounded-lg border border-white/10 bg-white/5 text-white placeholder-white/25 text-sm focus:border-indigo-500 outline-none"
              />
              <button
                onClick={addTopic}
                className="px-3 py-2 rounded-lg bg-indigo-500/20 hover:bg-indigo-500/30 text-indigo-300 transition-colors"
              >
                <Plus size={16} />
              </button>
            </div>
            {formData.topics.length > 0 && (
              <div className="flex flex-wrap gap-2 pt-1">
                {formData.topics.map((topic, i) => (
                  <div key={i} className="px-3 py-1.5 rounded-lg bg-indigo-500/10 border border-indigo-500/20 text-indigo-200 text-xs flex items-center gap-2">
                    {topic}
                    <button onClick={() => removeTopic(i)} className="hover:text-white transition-colors">
                      <Trash2 size={11} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="space-y-2">
            <label className="text-xs font-semibold text-white/60 uppercase tracking-wide">
              Chapters <span className="text-white/30 font-normal normal-case">(optional)</span>
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={newChapter}
                onChange={(e) => setNewChapter(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && addChapter()}
                placeholder="Chapter name and press Enter..."
                className="flex-1 px-3 py-2 rounded-lg border border-white/10 bg-white/5 text-white placeholder-white/25 text-sm focus:border-indigo-500 outline-none"
              />
              <button
                onClick={addChapter}
                className="px-3 py-2 rounded-lg bg-violet-500/20 hover:bg-violet-500/30 text-violet-300 transition-colors"
              >
                <Plus size={16} />
              </button>
            </div>
            {formData.chapters.length > 0 && (
              <div className="space-y-1.5 pt-1">
                {formData.chapters.map((ch, i) => (
                  <div key={i} className="px-3 py-2 rounded-lg bg-violet-500/10 border border-violet-500/20 text-violet-200 text-sm flex items-center justify-between">
                    <span className="flex items-center gap-2">
                      <span className="text-violet-400/50 text-xs font-mono">{String(i + 1).padStart(2, '0')}.</span>
                      {ch}
                    </span>
                    <button onClick={() => removeChapter(i)} className="hover:text-violet-100 transition-colors ml-4 flex-shrink-0">
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {editingSyllabus && !isFallback && (
            <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center gap-2 text-emerald-200 text-sm">
              <CheckCircle size={15} className="flex-shrink-0" />
              <span>
                Syllabus saved for <strong>{scopeLabel}</strong>
                {editingSyllabus.updated_at && (
                  <span className="text-emerald-300/50 text-xs ml-2">
                    · Updated {new Date(editingSyllabus.updated_at).toLocaleDateString()}
                  </span>
                )}
              </span>
            </div>
          )}

          <div className="flex gap-2 pt-1">
            <button
              onClick={onSave}
              disabled={saving || loading || !formData.content.trim()}
              className="flex-1 px-4 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:bg-indigo-600/40 text-white font-medium text-sm transition-colors flex items-center justify-center gap-2"
            >
              {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
              {saveButtonLabel}
            </button>
            {editingSyllabus && !isFallback && (
              <button
                onClick={onDelete}
                disabled={saving || loading}
                className="px-4 py-2.5 rounded-xl bg-red-600/15 hover:bg-red-600/25 disabled:opacity-40 text-red-300 font-medium text-sm transition-colors flex items-center gap-2"
              >
                <Trash2 size={15} />
                Delete
              </button>
            )}
          </div>

          {editingSyllabus && !isFallback && selectedSubjectId && selectedStreamId && (
            <div className="pt-2 border-t border-white/10">
              <div className="flex items-center gap-2">
                <button
                  onClick={onPublish}
                  disabled={publishing || saving}
                  className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-emerald-600/20 hover:bg-emerald-600/30 disabled:opacity-40 text-emerald-300 font-medium text-sm transition-colors border border-emerald-500/20"
                >
                  {publishing ? <Loader2 size={15} className="animate-spin" /> : <Globe size={15} />}
                  {publishing ? 'Publishing...' : 'Publish as Syllabus Card'}
                </button>
                {publishedSlug && (
                  <Link
                    to={`/learn/${publishedSlug}`}
                    target="_blank"
                    className="flex items-center gap-1.5 px-3 py-2.5 rounded-xl text-xs text-emerald-400 hover:text-emerald-300 transition-colors"
                  >
                    <ExternalLink size={13} />
                    View Card
                  </Link>
                )}
              </div>
              <p className="text-[10px] text-white/25 mt-2">
                Creates a discoverable library card at <span className="text-white/40">/learn/…</span> tagged "Syllabus" — visible to all students.
              </p>
            </div>
          )}
        </>
      )}
    </>
  );
}
