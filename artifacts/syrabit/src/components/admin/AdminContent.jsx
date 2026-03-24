import { useState, useEffect } from 'react';
import { Trash2, Loader2, ChevronRight, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { adminDeleteSubject, adminDeleteChapter, getChapters, adminReseed } from '@/utils/api';
import { getAllSubjects } from '@/utils/api';
import { toast } from 'sonner';

export default function AdminContent({ adminToken }) {
  const [subjects, setSubjects] = useState([]);
  const [chapters, setChapters] = useState({});
  const [expandedSubject, setExpandedSubject] = useState(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [newSubjectName, setNewSubjectName] = useState('');
  const [reseeding, setReseeding] = useState(false);

  useEffect(() => {
    getAllSubjects()
      .then((res) => setSubjects(res.data))
      .catch(() => toast.error('Failed to load subjects'))
      .finally(() => setLoading(false));
  }, []);

  const loadChapters = async (subjectId) => {
    if (chapters[subjectId]) return;
    try {
      const res = await getChapters(subjectId);
      setChapters((prev) => ({ ...prev, [subjectId]: res.data }));
    } catch {}
  };

  const handleToggleSubject = (subjectId) => {
    if (expandedSubject === subjectId) {
      setExpandedSubject(null);
    } else {
      setExpandedSubject(subjectId);
      loadChapters(subjectId);
    }
  };

  const handleDeleteSubject = async (subjectId) => {
    if (!window.confirm('Delete this subject and all its chapters?')) return;
    try {
      await adminDeleteSubject(adminToken, subjectId);
      setSubjects((prev) => prev.filter((s) => s.id !== subjectId));
      toast.success('Subject deleted');
    } catch {
      toast.error('Failed to delete');
    }
  };

  const handleDeleteChapter = async (chapterId, subjectId) => {
    try {
      await adminDeleteChapter(adminToken, chapterId);
      setChapters((prev) => ({
        ...prev,
        [subjectId]: prev[subjectId]?.filter((c) => c.id !== chapterId) || [],
      }));
      toast.success('Chapter deleted');
    } catch {
      toast.error('Failed to delete chapter');
    }
  };

  const handleReseed = async () => {
    setReseeding(true);
    try {
      await adminReseed(adminToken);
      const res = await getAllSubjects();
      setSubjects(res.data);
      setChapters({});
      toast.success('Content reseeded successfully');
    } catch {
      toast.error('Failed to reseed');
    } finally {
      setReseeding(false);
    }
  };

  if (loading) return <div className="flex justify-center p-10"><Loader2 size={24} className="animate-spin text-slate-400" /></div>;

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-slate-200 font-semibold">Subjects & Content ({subjects.length})</h2>
        <Button
          variant="outline"
          size="sm"
          onClick={handleReseed}
          disabled={reseeding}
          className="border-slate-700 text-slate-400 hover:text-slate-200 text-xs"
        >
          {reseeding ? <Loader2 size={14} className="animate-spin mr-1" /> : <RefreshCw size={14} className="mr-1" />}
          Reseed Content
        </Button>
      </div>

      <div className="space-y-2">
        {subjects.map((subject) => (
          <div key={subject.id} className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
            <div
              className="flex items-center justify-between p-4 cursor-pointer hover:bg-slate-800/50"
              onClick={() => handleToggleSubject(subject.id)}
            >
              <div className="flex items-center gap-3">
                <span className="text-2xl">{subject.icon || '📚'}</span>
                <div>
                  <p className="text-slate-200 font-medium">{subject.name}</p>
                  <p className="text-slate-500 text-xs">{subject.chapter_count} chapters</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={(e) => { e.stopPropagation(); handleDeleteSubject(subject.id); }}
                  className="p-1.5 rounded-lg text-slate-500 hover:text-red-400 hover:bg-red-500/10"
                >
                  <Trash2 size={14} />
                </button>
                <ChevronRight
                  size={16}
                  className={`text-slate-500 transition-transform ${
                    expandedSubject === subject.id ? 'rotate-90' : ''
                  }`}
                />
              </div>
            </div>

            {expandedSubject === subject.id && (
              <div className="border-t border-slate-800 p-4">
                {(chapters[subject.id] || []).map((chapter) => (
                  <div key={chapter.id} className="flex items-center justify-between py-2.5 border-b border-slate-800/50 last:border-0">
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-slate-600 w-6">{chapter.chapter_number}.</span>
                      <span className="text-slate-300 text-sm">{chapter.title}</span>
                    </div>
                    <button
                      onClick={() => handleDeleteChapter(chapter.id, subject.id)}
                      className="text-slate-600 hover:text-red-400 p-1"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                ))}
                {(chapters[subject.id] || []).length === 0 && (
                  <p className="text-slate-600 text-xs text-center py-3">No chapters</p>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
