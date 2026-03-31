import { GitBranch, BookOpen } from 'lucide-react';

export default function SyllabusSelection({
  boards, filteredClasses, filteredStreams, filteredSubjects,
  selectedBoardId, setSelectedBoardId,
  selectedClassId, setSelectedClassId,
  selectedStreamId, setSelectedStreamId,
  selectedSubjectId, setSelectedSubjectId,
}) {
  return (
    <div className="grid grid-cols-2 gap-3">
      <div>
        <label className="text-[10px] font-semibold text-white/50 uppercase tracking-wide mb-1.5 block">Board</label>
        <select
          value={selectedBoardId}
          onChange={(e) => {
            setSelectedBoardId(e.target.value);
            setSelectedClassId('');
            setSelectedStreamId('');
            setSelectedSubjectId('');
          }}
          className="w-full px-3 py-2.5 rounded-xl border border-white/10 bg-white/5 text-white text-sm focus:border-indigo-500 outline-none transition-colors"
        >
          <option value="">Select Board</option>
          {boards.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
        </select>
      </div>

      <div>
        <label className="text-[10px] font-semibold text-white/50 uppercase tracking-wide mb-1.5 block">Class</label>
        <select
          value={selectedClassId}
          onChange={(e) => {
            setSelectedClassId(e.target.value);
            setSelectedStreamId('');
            setSelectedSubjectId('');
          }}
          disabled={!selectedBoardId}
          className="w-full px-3 py-2.5 rounded-xl border border-white/10 bg-white/5 text-white text-sm focus:border-indigo-500 outline-none transition-colors disabled:opacity-40"
        >
          <option value="">Select Class</option>
          {filteredClasses.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </div>

      <div>
        <label className="text-[10px] font-semibold text-white/50 uppercase tracking-wide mb-1.5 flex items-center gap-1">
          <GitBranch size={10} />
          Stream
          <span className="text-white/25 font-normal normal-case tracking-normal ml-1">(optional)</span>
        </label>
        <select
          value={selectedStreamId}
          onChange={(e) => {
            setSelectedStreamId(e.target.value);
            setSelectedSubjectId('');
          }}
          disabled={!selectedClassId}
          className="w-full px-3 py-2.5 rounded-xl border border-white/10 bg-white/5 text-white text-sm focus:border-indigo-500 outline-none transition-colors disabled:opacity-40"
        >
          <option value="">All Streams (General)</option>
          {filteredStreams.map(s => <option key={s.id} value={s.id}>{s.icon ? `${s.icon} ` : ''}{s.name}</option>)}
        </select>
      </div>

      <div>
        <label className="text-[10px] font-semibold text-white/50 uppercase tracking-wide mb-1.5 flex items-center gap-1">
          <BookOpen size={10} />
          Subject
          <span className="text-white/25 font-normal normal-case tracking-normal ml-1">(optional)</span>
        </label>
        <select
          value={selectedSubjectId}
          onChange={(e) => setSelectedSubjectId(e.target.value)}
          disabled={!selectedStreamId}
          className="w-full px-3 py-2.5 rounded-xl border border-white/10 bg-white/5 text-white text-sm focus:border-indigo-500 outline-none transition-colors disabled:opacity-40"
        >
          <option value="">All Subjects</option>
          {filteredSubjects.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      </div>
    </div>
  );
}
