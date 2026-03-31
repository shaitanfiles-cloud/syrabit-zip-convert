import {
  User, Globe, GraduationCap, Layers, Phone, ChevronRight,
} from 'lucide-react';
import { LogoMark } from '@/components/Logo';
import { StarRating, UsageDots } from './shared';

export default function AcademicDetails({ profile, isDegreeProfile, openEdit }) {
  return (
    <>
      <div className="glass-card rounded-2xl overflow-hidden">
        <div className="px-4 py-3 border-b border-border">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Academic Details</p>
        </div>
        {[
          { key: 'name',         label: 'Display Name', value: profile?.name,        icon: User,          placeholder: 'Your full name' },
          { key: 'board_name',   label: 'Board',        value: profile?.board_name,  icon: Globe,         placeholder: 'AssamBoard division (AHSEC, DEGREE or SEBA)' },
          { key: 'class_name',   label: 'Class / Sem',  value: profile?.class_name,  icon: GraduationCap, placeholder: 'e.g. Class 12, 2nd Sem' },
          { key: 'stream_name',  label: isDegreeProfile ? 'Course Type' : 'Stream', value: profile?.stream_name, icon: Layers, placeholder: isDegreeProfile ? 'e.g. Major, Minor, MDC' : 'e.g. Science (PCM), B.Com' },
          { key: 'phone',        label: 'Phone',        value: profile?.phone,       icon: Phone,         placeholder: 'Optional phone number' },
        ].map(({ key, label, value, icon: Icon, placeholder }, i, arr) => (
          <button
            key={key}
            onClick={() => openEdit(key, label, placeholder)}
            className={`w-full flex items-center gap-3 px-4 py-3.5 hover:bg-accent/30 transition-colors text-left ${
              i < arr.length - 1 ? 'border-b border-border/50' : ''
            }`}
            data-testid={`edit-field-${key}`}
          >
            <div className="w-8 h-8 rounded-xl flex items-center justify-center flex-shrink-0"
              style={{ background: 'rgba(124,58,237,0.08)', border: '1px solid rgba(139,92,246,0.15)' }}>
              <Icon size={14} style={{ color: 'hsl(var(--primary))' }} />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs text-muted-foreground">{label}</p>
              <p className="text-sm font-medium text-foreground truncate">{value || `Add ${label.toLowerCase()}`}</p>
            </div>
            <ChevronRight size={14} className="text-muted-foreground/50 flex-shrink-0" />
          </button>
        ))}
      </div>

      <div className="glass-card rounded-2xl overflow-hidden">
        <div className="px-4 py-3 border-b border-border">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Preferred AI Models</p>
        </div>
        <div className="p-4 space-y-3">
          {[
            { name: 'Syrabit SLM Instant', badge: 'Fast', stars: 4, dots: 4, dotColor: 'bg-emerald-500', desc: 'Best for quick Q&A, fastest responses', available: true },
            { name: 'Syrabit MLM Versatile', badge: 'Coming Soon', stars: 5, dots: 0, dotColor: 'bg-muted', desc: 'Advanced model launching soon', available: false },
          ].map((m) => (
            <div key={m.name} className="flex items-center gap-3 p-3 rounded-xl"
              style={{ 
                background: m.available ? 'rgba(124,58,237,0.04)' : 'rgba(100,100,100,0.04)', 
                border: m.available ? '1px solid rgba(139,92,246,0.10)' : '1px solid rgba(150,150,150,0.10)',
                opacity: m.available ? 1 : 0.6
              }}>
              <LogoMark size="xs" />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-foreground">{m.name}</span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded-full"
                    style={{ 
                      background: m.available ? 'rgba(139,92,246,0.12)' : 'rgba(245,158,11,0.12)', 
                      color: m.available ? 'hsl(var(--primary))' : 'rgb(245,158,11)' 
                    }}>
                    {m.badge}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground/60 truncate mt-0.5">{m.desc}</p>
              </div>
              <div className="flex flex-col items-end gap-1.5 flex-shrink-0">
                {m.available && <StarRating value={m.stars} />}
                {m.available && <UsageDots value={m.dots} dotColor={m.dotColor} />}
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
