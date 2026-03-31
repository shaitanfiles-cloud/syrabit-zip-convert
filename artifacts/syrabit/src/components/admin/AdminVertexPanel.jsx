import { useState } from 'react';
import {
  Search, Languages, BarChart2, Lightbulb, TrendingUp, FileSearch,
  Eye, Brain, CreditCard, ListChecks,
} from 'lucide-react';
import StatusHeader from './vertex-panel/StatusHeader';
import SemanticSearchCard from './vertex-panel/SemanticSearchCard';
import TranslationCard from './vertex-panel/TranslationCard';
import QualityScoreCard from './vertex-panel/QualityScoreCard';
import TopicSuggesterCard from './vertex-panel/TopicSuggesterCard';
import SeoMetaCard from './vertex-panel/SeoMetaCard';
import ContentGapsCard from './vertex-panel/ContentGapsCard';
import VisionOcrCard from './vertex-panel/VisionOcrCard';
import NlpConceptsCard from './vertex-panel/NlpConceptsCard';
import FlashcardGeneratorCard from './vertex-panel/FlashcardGeneratorCard';
import McqGeneratorCard from './vertex-panel/McqGeneratorCard';
import AdminQuickLinks from './AdminQuickLinks';

const SERVICE_CARDS = [
  { id: 'semantic',   label: 'Semantic Search',    icon: Search,      color: '#3b82f6',  component: SemanticSearchCard },
  { id: 'translate',  label: 'Translation',         icon: Languages,   color: '#10b981',  component: TranslationCard },
  { id: 'quality',    label: 'Quality Scorer',      icon: BarChart2,   color: '#f59e0b',  component: QualityScoreCard },
  { id: 'topics',     label: 'Topic Suggester',     icon: Lightbulb,   color: '#a855f7',  component: TopicSuggesterCard },
  { id: 'seo',        label: 'SEO Meta Generator',  icon: TrendingUp,  color: '#06b6d4',  component: SeoMetaCard },
  { id: 'gaps',       label: 'Content Gaps',        icon: FileSearch,  color: '#ef4444',  component: ContentGapsCard },
  { id: 'ocr',        label: 'Vision OCR',          icon: Eye,         color: '#f97316',  component: VisionOcrCard },
  { id: 'nlp',        label: 'NLP Concepts',        icon: Brain,       color: '#a855f7',  component: NlpConceptsCard },
  { id: 'flashcards', label: 'Flashcard Generator', icon: CreditCard,  color: '#06b6d4',  component: FlashcardGeneratorCard },
  { id: 'mcq',        label: 'MCQ Generator',       icon: ListChecks,  color: '#10b981',  component: McqGeneratorCard },
];

export default function AdminVertexPanel({ token, adminToken, onNavigate }) {
  const tk = adminToken || token;
  const [active, setActive] = useState('semantic');

  const ActiveCard = SERVICE_CARDS.find(s => s.id === active)?.component;

  return (
    <div style={{ padding: '0 2px' }}>
      <StatusHeader token={tk} />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 6, marginBottom: 24 }}>
        {SERVICE_CARDS.map(s => {
          const Icon = s.icon;
          const isActive = active === s.id;
          return (
            <button key={s.id} onClick={() => setActive(s.id)}
              style={{
                background: isActive ? `${s.color}18` : 'rgba(255,255,255,0.025)',
                border: `1px solid ${isActive ? s.color + '55' : 'rgba(255,255,255,0.08)'}`,
                borderRadius: 12, padding: '10px 14px', cursor: 'pointer',
                display: 'flex', alignItems: 'center', gap: 8, transition: 'all 0.15s',
                textAlign: 'left',
              }}>
              <Icon size={15} color={isActive ? s.color : 'rgba(232,232,232,0.4)'} />
              <span style={{ fontSize: 12, fontWeight: 700, color: isActive ? s.color : 'rgba(232,232,232,0.55)' }}>
                {s.label}
              </span>
            </button>
          );
        })}
      </div>

      {ActiveCard && <ActiveCard token={tk} onNavigate={onNavigate} />}

      <div style={{ marginTop: 24, padding: 16, background: 'rgba(139,92,246,0.05)', border: '1px solid rgba(139,92,246,0.15)', borderRadius: 12 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: '#8b5cf6', marginBottom: 8, textTransform: 'uppercase' }}>Also Available In Other Panels</div>
        <div style={{ fontSize: 12, color: 'rgba(232,232,232,0.5)', lineHeight: 1.8 }}>
          • <strong style={{ color: '#e8e8e8' }}>CMS Editor</strong> — Translate button on any document<br />
          • <strong style={{ color: '#e8e8e8' }}>Content Studio</strong> — Enhance + Quality Score on generated blocks<br />
          • <strong style={{ color: '#e8e8e8' }}>Thumbnail Studio</strong> — Gemini Vision analysis (replaces Groq)<br />
          • <strong style={{ color: '#e8e8e8' }}>Document Upload</strong> — Extract topics/MCQs from AHSEC PDFs<br />
          • <strong style={{ color: '#e8e8e8' }}>Vision OCR</strong> — Scan question paper images (Cloud Vision)<br />
          • <strong style={{ color: '#e8e8e8' }}>NLP Concepts</strong> — Entity &amp; keyword extraction (Cloud Natural Language)<br />
          • <strong style={{ color: '#e8e8e8' }}>Flashcard + MCQ</strong> — Generate student revision material from any chapter
        </div>
      </div>
      <AdminQuickLinks links={['seomanager','content','analytics','dashboard']} onNavigate={onNavigate} />
    </div>
  );
}
