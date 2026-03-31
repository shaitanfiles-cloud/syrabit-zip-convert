import React from 'react';
import AdminQuickLinks from './AdminQuickLinks';
import { Loader2, RefreshCw, Play } from 'lucide-react';
import StatCard from './seo-manager/StatCard';
import JobProgress from './seo-manager/JobProgress';
import ReviewTab from './seo-manager/ReviewTab';
import PagesTab from './seo-manager/PagesTab';
import TopicsTab from './seo-manager/TopicsTab';
import InsightsTab from './seo-manager/InsightsTab';
import GenerateTab from './seo-manager/GenerateTab';
import PilotTab from './seo-manager/PilotTab';
import LinksTab from './seo-manager/LinksTab';
import SchemaTab from './seo-manager/SchemaTab';
import SitemapTab from './seo-manager/SitemapTab';
import PipelineTab from './seo-manager/PipelineTab';
import useSeoManager from './seo-manager/useSeoManager';

export default function AdminSeoManager({ adminToken, onNavigate }) {
  const s = useSeoManager(adminToken);

  const TABS = [
    { id: 'pipeline', label: '⚡ Pipeline', count: s.subjectCoverage.length || null },
    { id: 'review',   label: '🔍 Review',  count: s.reviewQueue.length || null },
    { id: 'pages',    label: 'SEO Pages',  count: s.pages.length },
    { id: 'topics',   label: 'Topics',     count: s.topics.length },
    { id: 'insights', label: '✦ Insights', count: s.insights?.insights?.length ?? null },
    { id: 'generate', label: 'Generate',   count: null },
    { id: 'pilot',    label: 'Pilot',      count: null },
    { id: 'links',    label: '🔗 Int. Links', count: null },
    { id: 'schema',   label: '🧬 Schema',  count: null },
    { id: 'sitemap',  label: '🗺 Sitemap', count: null },
  ];

  return (
    <div className="space-y-5 max-w-5xl">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-lg font-bold text-white">SEO Content Manager</h2>
          <p className="text-sm mt-0.5" style={{ color: 'rgba(255,255,255,0.35)' }}>Manage topic pages, generate AI content, and control what Googlebot crawls</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => s.load()} disabled={s.loading}
            className="p-1.5 rounded-lg border hover:bg-white/5 transition-colors" style={{ borderColor: 'rgba(255,255,255,0.1)' }}>
            <RefreshCw size={14} className={s.loading ? 'animate-spin' : ''} />
          </button>
          <button
            onClick={() => s.handleAutoRun()}
            disabled={s.activeJob?.status === 'queued' || s.activeJob?.status === 'running'}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-white/5 border border-white/10 hover:bg-white/10 transition-colors"
            style={{ color: '#a78bfa' }}>
            {s.activeJob?.status === 'running' ? <Loader2 size={13} className="animate-spin" />
              : <><Play size={13} /> Auto-Run All</>}
          </button>
        </div>
      </div>

      {s.activeJob && (
        <JobProgress job={s.activeJob} onDismiss={() => s.setActiveJob(null)} />
      )}

      {s.loading ? (
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="rounded-xl p-4 border h-24 animate-pulse" style={{ background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.06)' }} />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          <StatCard icon={s.BookOpen}     label="Topics"          value={s.topics.length}      color="rgba(255,255,255,0.70)" />
          <StatCard icon={s.CheckCircle2} label="Published"       value={s.publishedCount}     color="#34d399" />
          <StatCard icon={s.FileText}     label="Drafts"          value={s.draftCount}         color="#fbbf24" />
          <StatCard icon={s.Globe}        label="Sitemap URLs"    value={s.stats?.sitemap_urls ?? s.publishedCount} color="#a78bfa" />
          <StatCard icon={s.Activity}     label="Coverage"        value={`${s.coverage}%`}     color={s.coverage >= 80 ? '#34d399' : s.coverage >= 40 ? '#fbbf24' : '#f87171'}
            sub={`${s.topics.length} topics × 5 types`} />
        </div>
      )}

      <div className="flex gap-1 p-1 rounded-xl overflow-x-auto" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }}>
        {TABS.map(({ id, label, count }) => (
          <button key={id} onClick={() => s.setTab(id)}
            className={`flex-shrink-0 h-8 px-3 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5 ${
              s.tab === id ? 'text-white shadow' : 'hover:text-white/70'
            }`}
            style={s.tab === id ? { background: '#7c3aed', color: '#fff' } : { color: 'rgba(255,255,255,0.40)' }}>
            {label}
            {count !== null && (
              <span className="px-1.5 py-0.5 rounded-full text-[10px]"
                style={{ background: s.tab === id ? 'rgba(255,255,255,0.20)' : 'rgba(255,255,255,0.06)', color: s.tab === id ? '#fff' : 'rgba(255,255,255,0.30)' }}>
                {count}
              </span>
            )}
          </button>
        ))}
      </div>

      {s.tab === 'review' && (
        <ReviewTab adminToken={adminToken} reviewQueue={s.reviewQueue} setReviewQueue={s.setReviewQueue}
          reviewLoading={s.reviewLoading} reviewSelected={s.reviewSelected} setReviewSelected={s.setReviewSelected}
          flagging={s.flagging} setFlagging={s.setFlagging} bulkThreshold={s.bulkThreshold}
          setBulkThreshold={s.setBulkThreshold} loadReviewQueue={s.loadReviewQueue} />
      )}

      {s.tab === 'pages' && (
        <PagesTab loading={s.loading} filteredPages={s.filteredPages} pages={s.pages}
          publishedCount={s.publishedCount} draftCount={s.draftCount}
          pageSearch={s.pageSearch} setPageSearch={s.setPageSearch}
          pageFilter={s.pageFilter} setPageFilter={s.setPageFilter}
          handleToggleStatus={s.handleToggleStatus} handleAutoRun={s.handleAutoRun} />
      )}

      {s.tab === 'topics' && (
        <TopicsTab loading={s.loading} filteredTopics={s.filteredTopics} topics={s.topics}
          topicSearch={s.topicSearch} setTopicSearch={s.setTopicSearch}
          selectedTopics={s.selectedTopics} toggleTopic={s.toggleTopic}
          extracting={s.extracting} handleExtract={s.handleExtract}
          handleDeleteTopic={s.handleDeleteTopic} hubCtx={s.hubCtx}
          scopeSubjectOnly={s.scopeSubjectOnly} setScopeSubjectOnly={s.setScopeSubjectOnly}
          onNavigate={onNavigate} setTab={s.setTab} />
      )}

      {s.tab === 'insights' && (
        <InsightsTab insights={s.insights} insightsLoading={s.insightsLoading}
          loadInsights={s.loadInsights} handleInsightAction={s.handleInsightAction}
          actionLoading={s.actionLoading} />
      )}

      {s.tab === 'generate' && (
        <GenerateTab selectedTopics={s.selectedTopics} selectedTypes={s.selectedTypes}
          topics={s.topics} generating={s.generating} toggleTopic={s.toggleTopic}
          toggleType={s.toggleType} handleGenerate={s.handleGenerate} setTab={s.setTab} />
      )}

      {s.tab === 'pilot' && (
        <PilotTab piloting={s.piloting} pilotResult={s.pilotResult}
          pilotBoard={s.pilotBoard} setPilotBoard={s.setPilotBoard}
          pilotClass={s.pilotClass} setPilotClass={s.setPilotClass}
          pilotSubject={s.pilotSubject} setPilotSubject={s.setPilotSubject}
          pilotChapters={s.pilotChapters} setPilotChapters={s.setPilotChapters}
          handlePilot={s.handlePilot} />
      )}

      {s.tab === 'links' && (
        <LinksTab linksData={s.linksData} linksLoading={s.linksLoading}
          handleLinksAnalyze={s.handleLinksAnalyze} injectSlug={s.injectSlug}
          setInjectSlug={s.setInjectSlug} injecting={s.injecting}
          handleLinksInject={s.handleLinksInject} />
      )}

      {s.tab === 'schema' && (
        <SchemaTab schemaSlug={s.schemaSlug} setSchemaSlug={s.setSchemaSlug}
          schemaLoading={s.schemaLoading} schemaResult={s.schemaResult}
          handleSchemaInjectSingle={s.handleSchemaInjectSingle}
          handleSchemaBulk={s.handleSchemaBulk} publishedCount={s.publishedCount} />
      )}

      {s.tab === 'sitemap' && (
        <SitemapTab sitemapData={s.sitemapData} sitemapValidating={s.sitemapValidating}
          handleSitemapValidate={s.handleSitemapValidate} refreshingMeta={s.refreshingMeta}
          handleRefreshMeta={s.handleRefreshMeta} sitemap={s.sitemap}
          handleRegenerateSitemap={s.handleRegenerateSitemap} />
      )}

      {s.tab === 'pipeline' && (
        <PipelineTab subjectCoverage={s.subjectCoverage} coverageLoading={s.coverageLoading}
          loadCoverage={s.loadCoverage} subjectJobs={s.subjectJobs}
          handleRunSubject={s.handleRunSubject} handleAutoRun={s.handleAutoRun}
          activeJob={s.activeJob} setActiveJob={s.setActiveJob}
          pipelineSearch={s.pipelineSearch} setPipelineSearch={s.setPipelineSearch} />
      )}

      <AdminQuickLinks links={['content','vertex','analytics','dashboard','editor']} onNavigate={onNavigate} />
    </div>
  );
}
