import { useState, useEffect, useCallback } from 'react';
import { log } from '@/utils/logger';
import { BookOpen, Info } from 'lucide-react';
import { toast } from 'sonner';
import axios from 'axios';
import { API, authHeaders } from '@/utils/adminHelpers';
import { syllabusGetImports, syllabusDeleteImport, syllabusUpdateImport } from '@/utils/api';
import AgenticSyllabusUploader from './AgenticSyllabusUploader';
import NepStatsBanner from './syllabus-manager/NepStatsBanner';
import ManualPdfImport from './syllabus-manager/ManualPdfImport';
import SyllabusSelection from './syllabus-manager/SyllabusSelection';
import EditorForm from './syllabus-manager/EditorForm';
import ImportsHistory from './syllabus-manager/ImportsHistory';

const EMPTY_FORM = { content: '', chapters: [], topics: [], guidelines: '', geo_phrases: [] };

export default function AdminSyllabusManager({ adminToken, boards = [], classes = [], streams = [], subjects = [], onNavigate, onHubContext }) {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [publishedSlug, setPublishedSlug] = useState('');

  const [nepStats, setNepStats] = useState(null);
  const [autoAssigning, setAutoAssigning] = useState(false);
  const [nepStatsRefresh, setNepStatsRefresh] = useState(0);

  const [importsOpen, setImportsOpen] = useState(false);
  const [imports, setImports] = useState([]);
  const [importsLoading, setImportsLoading] = useState(false);
  const [editingImport, setEditingImport] = useState(null);
  const [editChapters, setEditChapters] = useState([]);
  const [editGuidelines, setEditGuidelines] = useState('');
  const [editSaving, setEditSaving] = useState(false);
  const [deletingImport, setDeletingImport] = useState(null);

  const loadImports = useCallback(async () => {
    setImportsLoading(true);
    try {
      const r = await syllabusGetImports(adminToken);
      setImports(r.data.imports || []);
    } catch { toast.error('Failed to load imports'); }
    finally { setImportsLoading(false); }
  }, [adminToken]);

  const startEditImport = (imp) => {
    setEditingImport(imp.import_id);
    setEditChapters([...(imp.chapters || [])]);
    setEditGuidelines(imp.guidelines || '');
  };

  const saveEditImport = async (import_id) => {
    setEditSaving(true);
    try {
      await syllabusUpdateImport(adminToken, import_id, { chapters: editChapters, guidelines: editGuidelines });
      toast.success('Import updated & chapters synced');
      setEditingImport(null);
      loadImports();
    } catch { toast.error('Save failed'); }
    finally { setEditSaving(false); }
  };

  const confirmDeleteImport = async (import_id, removeContent) => {
    try {
      await syllabusDeleteImport(adminToken, import_id, removeContent);
      toast.success(removeContent ? 'Import and content deleted' : 'Import record deleted');
      setDeletingImport(null);
      setImports(prev => prev.filter(i => i.import_id !== import_id));
    } catch { toast.error('Delete failed'); }
  };

  const [selectedBoardId, setSelectedBoardId] = useState('');
  const [selectedClassId, setSelectedClassId] = useState('');
  const [selectedStreamId, setSelectedStreamId] = useState('');
  const [selectedSubjectId, setSelectedSubjectId] = useState('');

  useEffect(() => {
    if (!onHubContext) return;
    onHubContext({
      boardId:     selectedBoardId,
      boardName:   boards.find(b => b.id === selectedBoardId)?.name  || '',
      classId:     selectedClassId,
      className:   classes.find(c => c.id === selectedClassId)?.name || '',
      streamId:    selectedStreamId,
      streamName:  streams.find(s => s.id === selectedStreamId)?.name || '',
      subjectId:   selectedSubjectId,
      subjectName: subjects.find(s => s.id === selectedSubjectId)?.name || '',
    });
  }, [selectedBoardId, selectedClassId, selectedStreamId, selectedSubjectId]);

  const [editingSyllabus, setEditingSyllabus] = useState(null);
  const [isFallback, setIsFallback] = useState(false);
  const [formData, setFormData] = useState(EMPTY_FORM);

  useEffect(() => {
    axios.get(`${API}/admin/syllabus/nep-stats`, { withCredentials: true })
      .then(r => setNepStats(r.data))
      .catch(() => {});
  }, [nepStatsRefresh]);

  const filteredClasses = classes.filter(c => c.board_id === selectedBoardId);
  const filteredStreams = streams.filter(s => s.class_id === selectedClassId);
  const filteredSubjects = selectedStreamId
    ? subjects.filter(s => s.stream_id === selectedStreamId)
    : selectedClassId ? subjects : [];

  const selectedBoard = boards.find(b => b.id === selectedBoardId);
  const selectedClass = classes.find(c => c.id === selectedClassId);
  const selectedStream = streams.find(s => s.id === selectedStreamId);
  const selectedSubject = subjects.find(s => s.id === selectedSubjectId);

  const canLoad = selectedBoardId && selectedClassId;

  const syllabusEndpoint = useCallback(() => {
    if (selectedStreamId && selectedSubjectId) return `${API}/syllabi/${selectedBoardId}/${selectedClassId}/${selectedStreamId}/${selectedSubjectId}`;
    if (selectedStreamId) return `${API}/syllabi/${selectedBoardId}/${selectedClassId}/${selectedStreamId}`;
    return `${API}/syllabi/${selectedBoardId}/${selectedClassId}`;
  }, [selectedBoardId, selectedClassId, selectedStreamId, selectedSubjectId]);

  const adminSyllabusEndpoint = useCallback(() => {
    if (selectedStreamId && selectedSubjectId) return `${API}/admin/syllabi/${selectedBoardId}/${selectedClassId}/${selectedStreamId}/${selectedSubjectId}`;
    if (selectedStreamId) return `${API}/admin/syllabi/${selectedBoardId}/${selectedClassId}/${selectedStreamId}`;
    return `${API}/admin/syllabi/${selectedBoardId}/${selectedClassId}`;
  }, [selectedBoardId, selectedClassId, selectedStreamId, selectedSubjectId]);

  const fetchSyllabus = useCallback(async () => {
    if (!canLoad) return;
    try {
      setLoading(true);
      setIsFallback(false);
      const res = await axios.get(syllabusEndpoint(), { withCredentials: true });
      const data = res.data;
      if (data && data.content) {
        setEditingSyllabus(data);
        setIsFallback(!!data.is_fallback);
        setFormData({
          content: data.content || '', chapters: data.chapters || [],
          topics: data.topics || [], guidelines: data.guidelines || '',
          geo_phrases: data.geo_phrases || [],
        });
      } else {
        setEditingSyllabus(null);
        setFormData(EMPTY_FORM);
      }
    } catch (err) {
      log.error('Fetch syllabus failed', { error: err.message, status: err.response?.status, endpoint: syllabusEndpoint() });
      setEditingSyllabus(null);
      setFormData(EMPTY_FORM);
    } finally { setLoading(false); }
  }, [canLoad, syllabusEndpoint]);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    setPublishedSlug('');
    if (canLoad) { fetchSyllabus(); }
    else { setEditingSyllabus(null); setFormData(EMPTY_FORM); setIsFallback(false); }
  }, [selectedBoardId, selectedClassId, selectedStreamId, selectedSubjectId]);

  const saveSyllabus = async () => {
    if (!canLoad) { toast.error('Please select Board and Class'); return; }
    if (!formData.content.trim()) { toast.error('Syllabus content is required'); return; }
    try {
      setSaving(true);
      await axios.post(adminSyllabusEndpoint(), formData, authHeaders(adminToken));
      toast.success('Syllabus saved successfully!');
      fetchSyllabus();
    } catch (err) {
      log.error('Save syllabus failed', { error: err.message, status: err.response?.status });
      toast.error(err.response?.data?.detail || 'Failed to save syllabus');
    } finally { setSaving(false); }
  };

  const deleteSyllabus = async () => {
    if (!confirm('Delete this syllabus? This cannot be undone.')) return;
    try {
      setSaving(true);
      await axios.delete(adminSyllabusEndpoint(), authHeaders(adminToken));
      toast.success('Syllabus deleted');
      setEditingSyllabus(null); setFormData(EMPTY_FORM); setIsFallback(false); setPublishedSlug('');
    } catch (err) {
      log.error('Delete syllabus failed', { error: err.message, status: err.response?.status });
      toast.error(err.response?.data?.detail || 'Failed to delete syllabus');
    } finally { setSaving(false); }
  };

  const publishSyllabus = async () => {
    if (!selectedStreamId || !selectedSubjectId) { toast.error('Select a Stream and Subject to publish a syllabus card'); return; }
    try {
      setPublishing(true);
      const res = await axios.post(
        `${API}/admin/syllabus/publish/${selectedBoardId}/${selectedClassId}/${selectedStreamId}/${selectedSubjectId}`,
        {}, authHeaders(adminToken)
      );
      setPublishedSlug(res.data.seo_slug);
      toast.success('Syllabus card published to library!');
    } catch (err) {
      log.error('Publish syllabus failed', { error: err.message, status: err.response?.status });
      toast.error(err.response?.data?.detail || 'Failed to publish syllabus card');
    } finally { setPublishing(false); }
  };

  const handleFyugpAutoAssign = async () => {
    setAutoAssigning(true);
    try {
      const res = await axios.post(`${API}/admin/fyugp/auto-assign`, {}, authHeaders(adminToken));
      const { reassigned, skipped, total_scanned } = res.data;
      toast.success(`Auto-assigned ${reassigned} subject${reassigned !== 1 ? 's' : ''} into FYUGP structure (${skipped} skipped, ${total_scanned} scanned)`);
      if (reassigned > 0 && importsOpen) loadImports();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Auto-assign failed');
    } finally { setAutoAssigning(false); }
  };

  const scopeLabel = selectedSubject
    ? `${selectedBoard?.name || ''} · ${selectedClass?.name || ''} · ${selectedStream?.name || ''} · ${selectedSubject.name}`
    : selectedStream
    ? `${selectedBoard?.name || ''} · ${selectedClass?.name || ''} · ${selectedStream.name}`
    : selectedClass
    ? `${selectedBoard?.name || ''} · ${selectedClass?.name || ''}`
    : '';

  const fallbackNotice = isFallback && editingSyllabus ? (
    selectedSubjectId
      ? `Showing a fallback syllabus — no subject-specific syllabus exists yet for "${selectedSubject?.name}". Save below to create one.`
      : `Showing the general board+class syllabus as a preview — no stream-specific syllabus exists yet for ${selectedStream?.name}. Save below to create one.`
  ) : null;

  const saveButtonLabel = saving
    ? 'Saving...'
    : isFallback && selectedSubjectId
    ? `Create Subject Syllabus for ${selectedSubject?.name || ''}`
    : isFallback && selectedStreamId
    ? `Create Stream Syllabus for ${selectedStream?.name || ''}`
    : 'Save Syllabus';

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <BookOpen size={22} className="text-indigo-400" />
        <div>
          <h2 className="text-lg font-bold text-white">Universal Syllabus Manager</h2>
          <p className="text-xs text-white/40 mt-0.5">Create syllabi that auto-inject into every AI answer for a board, class, stream, or specific subject</p>
        </div>
      </div>

      <NepStatsBanner nepStats={nepStats} autoAssigning={autoAssigning} onAutoAssign={handleFyugpAutoAssign} />

      <AgenticSyllabusUploader
        adminToken={adminToken}
        onComplete={(summary) => {
          toast.success(`✅ ${summary.total_subjects} subjects imported — ${summary.total_chapters} chapters, ${summary.total_chunks} RAG chunks`);
          loadImports();
          if (onHubContext) onHubContext({ action: 'refresh_syllabus' });
        }}
      />

      <ManualPdfImport
        adminToken={adminToken}
        selectedBoardId={selectedBoardId}
        selectedClassId={selectedClassId}
        selectedStreamId={selectedStreamId}
        onImportComplete={() => setNepStatsRefresh(n => n + 1)}
      />

      <ImportsHistory
        importsOpen={importsOpen} setImportsOpen={setImportsOpen}
        imports={imports} importsLoading={importsLoading} loadImports={loadImports}
        onStartEdit={startEditImport} onSaveEdit={saveEditImport} onDeleteImport={confirmDeleteImport}
        editingImport={editingImport} setEditingImport={setEditingImport}
        editChapters={editChapters} setEditChapters={setEditChapters}
        editGuidelines={editGuidelines} setEditGuidelines={setEditGuidelines}
        editSaving={editSaving}
        deletingImport={deletingImport} setDeletingImport={setDeletingImport}
      />

      <SyllabusSelection
        boards={boards} filteredClasses={filteredClasses} filteredStreams={filteredStreams} filteredSubjects={filteredSubjects}
        selectedBoardId={selectedBoardId} setSelectedBoardId={setSelectedBoardId}
        selectedClassId={selectedClassId} setSelectedClassId={setSelectedClassId}
        selectedStreamId={selectedStreamId} setSelectedStreamId={setSelectedStreamId}
        selectedSubjectId={selectedSubjectId} setSelectedSubjectId={setSelectedSubjectId}
      />

      {selectedClassId && (
        <div className="flex items-start gap-2 p-3 rounded-xl border border-white/10 bg-white/[0.02]">
          <Info size={14} className="text-indigo-400 mt-0.5 flex-shrink-0" />
          <p className="text-xs text-white/50 leading-relaxed">
            {selectedSubjectId
              ? <>This syllabus applies only to <span className="text-indigo-300 font-medium">{selectedSubject?.name}</span> within {selectedStream?.name}. It takes highest priority — the AI uses it when a student asks about this specific subject.</>
              : selectedStreamId
              ? <>This syllabus applies only to <span className="text-indigo-300 font-medium">{scopeLabel}</span>. The AI will use it when a student from this exact stream asks a question.</>
              : <>This is a <span className="text-indigo-300 font-medium">general syllabus</span> for <span className="text-white/70">{scopeLabel}</span>. The AI uses it as a fallback when no stream- or subject-specific syllabus exists.</>
            }
          </p>
        </div>
      )}

      {selectedSubjectId && onNavigate && (
        <div className="flex items-center gap-2 flex-wrap py-1">
          <span className="text-[10px] text-white/25 font-semibold uppercase tracking-widest">Next step:</span>
          <button onClick={() => onNavigate('editor')}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition hover:opacity-90"
            style={{ background: 'rgba(139,92,246,0.15)', color: '#c4b5fd', border: '1px solid rgba(139,92,246,0.30)' }}>
            Write Content →
          </button>
          <button onClick={() => onNavigate('pyq')}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition hover:opacity-90"
            style={{ background: 'rgba(245,158,11,0.15)', color: '#fcd34d', border: '1px solid rgba(245,158,11,0.30)' }}>
            Upload PYQ →
          </button>
          <button onClick={() => onNavigate('editor')}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition hover:opacity-90"
            style={{ background: 'rgba(139,92,246,0.15)', color: '#c4b5fd', border: '1px solid rgba(139,92,246,0.30)' }}>
            Content Editor →
          </button>
        </div>
      )}

      <EditorForm
        loading={loading} saving={saving} publishing={publishing}
        canLoad={canLoad} isFallback={isFallback} editingSyllabus={editingSyllabus}
        formData={formData} setFormData={setFormData}
        selectedSubjectId={selectedSubjectId} selectedStreamId={selectedStreamId}
        selectedSubject={selectedSubject} selectedStream={selectedStream}
        scopeLabel={scopeLabel} fallbackNotice={fallbackNotice} saveButtonLabel={saveButtonLabel}
        publishedSlug={publishedSlug}
        onSave={saveSyllabus} onDelete={deleteSyllabus} onPublish={publishSyllabus}
      />

      {!canLoad && (
        <div className="p-5 rounded-xl bg-white/[0.02] border border-white/10 text-center">
          <BookOpen size={28} className="mx-auto text-white/15 mb-2" />
          <p className="text-white/50 text-sm">Select a Board and Class to manage their syllabus</p>
          <p className="text-white/25 text-xs mt-1">Stream and Subject are optional — use them for more targeted AI guidance</p>
        </div>
      )}
    </div>
  );
}
