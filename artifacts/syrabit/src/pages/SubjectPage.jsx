import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import PageMeta from '@/components/seo/PageMeta';
import { BookOpen, MessageSquare, Loader2, ArrowLeft, FileText, Calculator, BookMarked, HelpCircle, List } from 'lucide-react';
import { Button } from '@/components/ui/button';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Skeleton } from '@/components/ui/skeleton';
import { AppLayout } from '@/components/layout/AppLayout';
import { getSubject, getChapters, getChunks } from '@/utils/api';
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion';

function JsonLdCourse({ subject, subjectDesc, subjectUrl }) {
  useEffect(() => {
    const script = document.createElement('script');
    script.type = 'application/ld+json';
    script.id = 'subject-jsonld';
    script.text = JSON.stringify({
      '@context': 'https://schema.org',
      '@type': 'Course',
      name: subject.name,
      description: subjectDesc,
      provider: {
        '@type': 'Organization',
        name: 'Syrabit.ai',
        sameAs: 'https://syrabit.ai',
      },
      educationalLevel: ((subject.class_name || 'AHSEC') + ' ' + (subject.stream_name || '')).trim(),
      url: subjectUrl,
    });
    const existing = document.getElementById('subject-jsonld');
    if (existing) existing.remove();
    document.head.appendChild(script);
    return () => { const el = document.getElementById('subject-jsonld'); if (el) el.remove(); };
  }, [subject, subjectDesc, subjectUrl]);
  return null;
}

const CONTENT_TYPE_ICONS = {
  notes: FileText,
  example: BookMarked,
  formula: Calculator,
  pyq: HelpCircle,
  summary: List,
};

const CONTENT_TYPE_COLORS = {
  notes: 'bg-blue-500/15 text-blue-400 border-blue-500/25',
  example: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/25',
  formula: 'bg-violet-500/15 text-violet-400 border-violet-500/25',
  pyq: 'bg-amber-500/15 text-amber-400 border-amber-500/25',
  summary: 'bg-pink-500/15 text-pink-400 border-pink-500/25',
};

export default function SubjectPage() {
  const { subjectId } = useParams();
  const [subject, setSubject] = useState(null);
  const [chapters, setChapters] = useState([]);
  const [chunks, setChunks] = useState({});
  const [loading, setLoading] = useState(true);
  const [loadingChapter, setLoadingChapter] = useState(null);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const [subRes, chapRes] = await Promise.all([
          getSubject(subjectId),
          getChapters(subjectId),
        ]);
        setSubject(subRes.data);
        setChapters(chapRes.data);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [subjectId]);

  const loadChunks = async (chapterId) => {
    if (chunks[chapterId]) return;
    setLoadingChapter(chapterId);
    try {
      const res = await getChunks(chapterId);
      setChunks((prev) => ({ ...prev, [chapterId]: res.data }));
    } finally {
      setLoadingChapter(null);
    }
  };

  if (loading) {
    return (
      <AppLayout>
        <div className="p-4 sm:p-6 space-y-4">
          <Skeleton className="h-8 w-1/2" />
          <Skeleton className="h-4 w-2/3" />
          {[...Array(5)].map((_, i) => <Skeleton key={i} className="h-14 w-full" />)}
        </div>
      </AppLayout>
    );
  }

  if (!subject) {
    return (
      <AppLayout>
        <div className="p-6 text-center">
          <p className="text-muted-foreground">Subject not found</p>
          <Link to="/library"><Button className="mt-4">Back to Library</Button></Link>
        </div>
      </AppLayout>
    );
  }

  const subjectUrl = subject.board_slug && subject.class_slug && subject.stream_slug && subject.slug
    ? `https://syrabit.ai/${subject.board_slug}/${subject.class_slug}/${subject.stream_slug}/${subject.slug}`
    : `https://syrabit.ai/subject/${subjectId}`;

  const subjectTitle = subject.name + ' Notes — ' + (subject.class_name || 'AHSEC') + ' ' + (subject.stream_name || '');
  const subjectDesc = subject.description
    || ('Complete ' + subject.name + ' notes, chapters, and AI explanations for ' + (subject.class_name || 'AHSEC') + ' ' + (subject.stream_name || '') + ' students.');

  return (
    <AppLayout pageTitle={subject.name}>
      <PageMeta
        title={subjectTitle.trim()}
        description={subjectDesc.trim()}
        url={subjectUrl}
      />
      <JsonLdCourse subject={subject} subjectDesc={subjectDesc} subjectUrl={subjectUrl} />
      <div className="p-4 sm:p-6 space-y-6" data-testid="subject-detail">
        {/* Back */}
        <Link to="/library" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft size={14} /> Library
        </Link>

        {/* Header */}
        <div className="glass-card rounded-2xl p-6">
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-center gap-4">
              <div className="w-14 h-14 rounded-2xl bg-primary/10 flex items-center justify-center text-3xl">
                {subject.icon || '📚'}
              </div>
              <div>
                <h1 className="text-xl font-semibold text-foreground">{subject.name}</h1>
                <p className="text-sm text-muted-foreground mt-0.5">{subject.description}</p>
                <div className="flex items-center gap-3 mt-2">
                  <span className="text-xs text-muted-foreground">
                    <BookOpen size={12} className="inline mr-1" />{chapters.length} chapters
                  </span>
                </div>
              </div>
            </div>
            <Link to={`/chat?subject=${subjectId}`}>
              <Button className="bg-primary hover:bg-primary/90 text-primary-foreground flex-shrink-0">
                Ask AI
              </Button>
            </Link>
          </div>

          {subject.tags?.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-4">
              {subject.tags.map((tag) => (
                <span key={tag} className="text-xs bg-primary/8 text-primary/80 px-2.5 py-1 rounded-full border border-primary/15">
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Chapters */}
        <div>
          <h2 className="text-lg font-semibold mb-4">Chapters</h2>
          {chapters.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <BookOpen size={32} className="mx-auto mb-2 opacity-30" />
              <p>No chapters available yet</p>
            </div>
          ) : (
            <Accordion type="multiple" className="space-y-2">
              {chapters.map((chapter) => (
                <AccordionItem
                  key={chapter.id}
                  value={chapter.id}
                  className="glass-card rounded-xl border-0 px-4"
                >
                  <AccordionTrigger
                    className="hover:no-underline py-4"
                    onClick={() => loadChunks(chapter.id)}
                  >
                    <div className="flex items-center gap-3">
                      <span className="w-7 h-7 rounded-lg bg-primary/10 flex items-center justify-center text-xs font-semibold text-primary flex-shrink-0">
                        {chapter.chapter_number}
                      </span>
                      <span className="text-sm font-medium text-foreground text-left">{chapter.title}</span>
                    </div>
                  </AccordionTrigger>
                  <AccordionContent className="pb-4">
                    {loadingChapter === chapter.id ? (
                      <div className="flex justify-center py-4">
                        <Loader2 size={20} className="animate-spin text-primary" />
                      </div>
                    ) : chapter.content ? (
                      <div className="px-4 py-2">
                        <div className="md-content-light text-sm">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {chapter.content}
                          </ReactMarkdown>
                        </div>
                      </div>
                    ) : (
                      <div className="text-center py-4">
                        <p className="text-sm text-muted-foreground">No content added yet</p>
                      </div>
                    )}
                    <div className="mt-3">
                      <Link to={`/chat?subject=${subjectId}`}>
                        <Button size="sm" className="text-xs bg-primary hover:bg-primary/90 text-primary-foreground">
                          Ask AI about this chapter
                        </Button>
                      </Link>
                    </div>
                  </AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          )}
        </div>
      </div>
    </AppLayout>
  );
}
