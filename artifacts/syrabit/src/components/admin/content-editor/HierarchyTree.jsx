import {
  ChevronRight, ChevronDown, Trash2,
  Building2, GraduationCap, GitBranch,
} from 'lucide-react';
import InlineCreator from './InlineCreator';
import StatusBadge from './StatusBadge';

export default function HierarchyTree({
  boards, filteredClasses, filteredStreams,
  selBoard, setSelBoard, selClass, setSelClass,
  selStream, setSelStream, setSelSubject, setEditView,
  streamNodeLabel, streamPlaceholder,
  onDelete, onCreateBoard, onCreateClass, onCreateStream,
}) {
  return (
    <div className="w-72 border-r border-gray-200 flex flex-col overflow-y-auto" style={{ background: '#ffffff' }}>
      <div className="p-3 space-y-1">
        <p className="text-[10px] uppercase tracking-wider text-gray-400 px-2 mb-2 font-semibold">Boards</p>
        {boards.map(b => (
          <div key={b.id}>
            <div className="flex items-center group">
              <button
                onClick={() => { setSelBoard(selBoard === b.id ? null : b.id); setSelClass(null); setSelStream(null); setSelSubject(null); }}
                className={`flex-1 flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${selBoard === b.id ? 'bg-violet-500/15 text-violet-300' : 'text-gray-600 hover:bg-gray-50'}`}
              >
                {selBoard === b.id ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                <Building2 size={14} />
                <span className="truncate">{b.name}</span>
                <StatusBadge status={b.status} size="xs" className="ml-auto flex-shrink-0" />
              </button>
              <button onClick={() => onDelete('board', b.id)} className="p-1 rounded opacity-0 group-hover:opacity-100 text-gray-300 hover:text-red-400"><Trash2 size={12} /></button>
            </div>

            {selBoard === b.id && (
              <div className="ml-5 mt-1 space-y-1 border-l border-gray-100 pl-3">
                <p className="text-[10px] uppercase tracking-wider text-gray-300 px-1 font-semibold">Classes</p>
                {filteredClasses.map(c => (
                  <div key={c.id}>
                    <div className="flex items-center group">
                      <button
                        onClick={() => { setSelClass(selClass === c.id ? null : c.id); setSelStream(null); setSelSubject(null); }}
                        className={`flex-1 flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs transition-colors ${selClass === c.id ? 'bg-blue-500/15 text-blue-300' : 'text-gray-500 hover:bg-gray-50'}`}
                      >
                        {selClass === c.id ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                        <GraduationCap size={12} />
                        <span className="truncate">{c.name}</span>
                        <StatusBadge status={c.status} size="xs" className="ml-auto flex-shrink-0" />
                      </button>
                      <button onClick={() => onDelete('classe', c.id)} className="p-1 rounded opacity-0 group-hover:opacity-100 text-gray-300 hover:text-red-400"><Trash2 size={10} /></button>
                    </div>

                    {selClass === c.id && (
                      <div className="ml-4 mt-1 space-y-1 border-l border-gray-100 pl-3">
                        <p className="text-[10px] uppercase tracking-wider text-gray-300 px-1 font-semibold">{streamNodeLabel}</p>
                        {filteredStreams.map(st => (
                          <div key={st.id} className="flex items-center group">
                            <button
                              onClick={() => { setSelStream(selStream === st.id ? null : st.id); setSelSubject(null); }}
                              className={`flex-1 flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs transition-colors ${selStream === st.id ? 'bg-emerald-500/15 text-emerald-300' : 'text-gray-500 hover:bg-gray-50'}`}
                            >
                              <GitBranch size={11} />
                              <span className="truncate">{st.icon || ''} {st.name}</span>
                              <StatusBadge status={st.status} size="xs" className="ml-auto flex-shrink-0" />
                            </button>
                            <button onClick={() => onDelete('stream', st.id)} className="p-1 rounded opacity-0 group-hover:opacity-100 text-gray-300 hover:text-red-400"><Trash2 size={10} /></button>
                          </div>
                        ))}
                        <InlineCreator placeholder={streamPlaceholder} onCreate={onCreateStream} icon={GitBranch} color="emerald" />
                      </div>
                    )}
                  </div>
                ))}
                <InlineCreator placeholder="Class" onCreate={onCreateClass} icon={GraduationCap} color="blue" />
              </div>
            )}
          </div>
        ))}
        <InlineCreator placeholder="Board" onCreate={onCreateBoard} icon={Building2} color="violet" />
      </div>
    </div>
  );
}
