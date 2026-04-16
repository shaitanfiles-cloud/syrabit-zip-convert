import axios from 'axios';
import { toast } from 'sonner';

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || '';
export const API_BASE = `${BACKEND_URL}/api`;

const _RENDER_URL = (import.meta.env.VITE_RENDER_API_URL || '').replace(/\/+$/, '');
const _WORKER_URL = (import.meta.env.VITE_WORKER_API_URL || '').replace(/\/+$/, '');
const RENDER_API = _RENDER_URL ? `${_RENDER_URL}/api` : API_BASE;
export const WORKER_API = _WORKER_URL ? `${_WORKER_URL}/api` : API_BASE;

let _authToken = null;

export const setAuthToken = (token) => {
  _authToken = token;
};

export function getAnonId() {
  let id = localStorage.getItem('syrabit_anon_id');
  if (!id) {
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    id = 'anon_' + Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join('');
    localStorage.setItem('syrabit_anon_id', id);
  }
  return id;
}

const anonHeaders = () => ({ 'x-anon-id': getAnonId() });

const authConfig = () => {
  const config = { withCredentials: true };
  if (_authToken) {
    config.headers = { Authorization: `Bearer ${_authToken}` };
  }
  return config;
};

const RETRY_CODES = new Set([408, 429, 500, 502, 503, 504]);
const MAX_RETRIES = 2;
const RETRY_DELAY_MS = 1000;

axios.interceptors.response.use(
  (response) => response,
  async (error) => {
    const config = error.config;
    const retryCount = config?._retryCount || 0;
    if (
      config &&
      retryCount < MAX_RETRIES &&
      error.response &&
      RETRY_CODES.has(error.response.status) &&
      (!config.method || config.method.toLowerCase() === 'get')
    ) {
      config._retryCount = retryCount + 1;
      {
        const delay = RETRY_DELAY_MS * config._retryCount;
        await new Promise(r => setTimeout(r, delay));
        return axios(config);
      }
    }

    if (error.response?.status === 401) {
      const reqUrl = config?.url || '';
      const isAdminContentCall = reqUrl.includes('/admin/content/') || reqUrl.includes('/admin/studio/');
      const isAdminRoute = window.location.pathname.startsWith('/admin') &&
        !window.location.pathname.startsWith('/admin/login');
      if (isAdminRoute && !isAdminContentCall) {
        toast.error('Session expired. Please log in again.');
        window.location.href = '/admin/login';
      }
    }
    return Promise.reject(error);
  }
);

export const apiClient = () =>
  axios.create({ baseURL: API_BASE, withCredentials: true });

export const getBoards = () => axios.get(`${WORKER_API}/content/boards`);
export const getClasses = (boardId) => axios.get(`${WORKER_API}/content/classes?board_id=${boardId}`);
export const getStreams = (classId) => axios.get(`${WORKER_API}/content/streams?class_id=${classId}`);
export const getAllSubjects = () => axios.get(`${WORKER_API}/content/subjects`);
export const getSubjectsByCourseType = (boardId) => axios.get(`${WORKER_API}/content/subjects-by-course-type?board_id=${boardId}`);
export const getSubject = (id) => axios.get(`${WORKER_API}/content/subjects/${id}`);
export const getChapters = (subjectId) => axios.get(`${WORKER_API}/content/chapters/${subjectId}`);
export const getChunks = (chapterId) => axios.get(`${WORKER_API}/content/chunks/${chapterId}`);
export const getChapterTopicSummary = (chapterId) => axios.get(`${WORKER_API}/content/chapters/${chapterId}/topic-summary`);
export const getChapterTopicContent = (chapterId) => axios.get(`${WORKER_API}/content/chapters/${chapterId}/topic-content`);
export const getTopicPage = (topicId, pageType) => axios.get(`${WORKER_API}/content/topic/${topicId}/page/${pageType}`);

export const getConversations = () =>
  axios.get(`${API_BASE}/conversations`, authConfig());

export const getConversation = (id) =>
  axios.get(`${API_BASE}/conversations/${id}`, authConfig());

export const deleteConversation = (id) =>
  axios.delete(`${API_BASE}/conversations/${id}`, authConfig());

export const updateConversation = (id, data) =>
  axios.patch(`${API_BASE}/conversations/${id}`, data, authConfig());

export const getAnonConversations = () =>
  axios.get(`${API_BASE}/conversations/anon`, { headers: anonHeaders() });

export const getAnonConversation = (id) =>
  axios.get(`${API_BASE}/conversations/anon/${id}`, { headers: anonHeaders() });

export const deleteAnonConversation = (id) =>
  axios.delete(`${API_BASE}/conversations/anon/${id}`, { headers: anonHeaders() });

export const saveOnboarding = (data) =>
  axios.post(`${API_BASE}/user/onboarding`, data, authConfig());

export const adminLogin = (email, password) =>
  axios.post(`${API_BASE}/admin/login`, { email, password }, { withCredentials: true });

const adminHeaders = (token) => {
  const isRealJwt = token && typeof token === 'string' && token.split('.').length === 3;
  return isRealJwt ? { Authorization: `Bearer ${token}` } : {};
};

export const adminVerify = (token) =>
  axios.get(`${API_BASE}/admin/verify`, {
    ...(token ? { headers: adminHeaders(token) } : {}),
    withCredentials: true,
  });

export const adminLogout = () =>
  axios.post(`${API_BASE}/admin/logout`, {}, { withCredentials: true });

export const adminGetDashboard = (token) =>
  axios.get(`${API_BASE}/admin/dashboard`, { headers: adminHeaders(token), withCredentials: true });

export const adminGetUsers = (token, params = {}) =>
  axios.get(`${API_BASE}/admin/users`, { headers: adminHeaders(token), withCredentials: true, params });

export const adminUpdateUserStatus = (token, userId, status) =>
  axios.patch(`${API_BASE}/admin/users/${userId}/status`, { status }, { headers: adminHeaders(token), withCredentials: true });

export const adminUpdateUserPlan = (token, userId, plan) =>
  axios.patch(`${API_BASE}/admin/users/${userId}/plan`, { plan }, { headers: adminHeaders(token), withCredentials: true });

export const adminGetConversations = (token) =>
  axios.get(`${API_BASE}/admin/conversations`, { headers: adminHeaders(token), withCredentials: true });

export const adminGetAnalytics = (token, days = 30) =>
  axios.get(`${API_BASE}/admin/analytics`, { headers: adminHeaders(token), withCredentials: true, params: { days } });

export const adminGetDailyAnalytics = (token, days = 30) =>
  axios.get(`${API_BASE}/admin/analytics/daily`, { headers: adminHeaders(token), withCredentials: true, params: { days } });

export const adminGetRevenue = (token, days = 30) =>
  axios.get(`${API_BASE}/admin/analytics/revenue`, { headers: adminHeaders(token), withCredentials: true, params: { days } });

export const adminGetPredictor = (token) =>
  axios.get(`${API_BASE}/admin/analytics/predictor`, { headers: adminHeaders(token), withCredentials: true });

export const adminGetGA4Status = (token) =>
  axios.get(`${API_BASE}/admin/ga4/status`, { headers: adminHeaders(token), withCredentials: true });

export const adminGetGA4AuthUrl = (token, redirectUri) =>
  axios.get(`${API_BASE}/admin/ga4/auth-url`, { headers: adminHeaders(token), withCredentials: true, params: { redirect_uri: redirectUri } });


export const adminTestGA4 = (token) =>
  axios.get(`${API_BASE}/admin/ga4/test`, { headers: adminHeaders(token), withCredentials: true });

export const adminGetLiveVisitors = (token) =>
  axios.get(`${API_BASE}/admin/analytics/live`, { headers: adminHeaders(token), withCredentials: true });

export const adminSyncHistorical = (token, days = 90) =>
  axios.post(`${API_BASE}/admin/analytics/sync-historical`, { days }, { headers: adminHeaders(token), withCredentials: true });

export const adminGetContentCardViews = (token, days = 0) =>
  axios.get(`${API_BASE}/admin/analytics/content-card-views`, { headers: adminHeaders(token), withCredentials: true, params: { days } });

export const adminGetSettings = (token) =>
  axios.get(`${API_BASE}/admin/settings`, { headers: adminHeaders(token), withCredentials: true });

export const adminUpdateSettings = (token, data) =>
  axios.patch(`${API_BASE}/admin/settings`, data, { headers: adminHeaders(token), withCredentials: true });

export const adminGetRoadmap = (token) =>
  axios.get(`${API_BASE}/admin/roadmap`, { headers: adminHeaders(token), withCredentials: true });

export const adminCreateRoadmapItem = (token, data) =>
  axios.post(`${API_BASE}/admin/roadmap`, data, { headers: adminHeaders(token), withCredentials: true });

export const adminDeleteRoadmapItem = (token, id) =>
  axios.delete(`${API_BASE}/admin/roadmap/${id}`, { headers: adminHeaders(token), withCredentials: true });


export const adminGetPlanConfig = (token) =>
  axios.get(`${API_BASE}/admin/plan-config`, { headers: adminHeaders(token), withCredentials: true });

export const adminUpdatePlanConfig = (token, data) =>
  axios.put(`${API_BASE}/admin/plan-config`, data, { headers: adminHeaders(token), withCredentials: true });

export const adminGetApiConfig = (token) =>
  axios.get(`${API_BASE}/admin/api-config`, { headers: adminHeaders(token), withCredentials: true });

export const adminUpdateApiConfig = (token, data) =>
  axios.put(`${API_BASE}/admin/api-config`, data, { headers: adminHeaders(token), withCredentials: true });

export const adminUpdateRoadmapItem = (token, id, data) =>
  axios.patch(`${API_BASE}/admin/roadmap/${id}`, data, { headers: adminHeaders(token), withCredentials: true });

export const adminGetActivityLog = (token) =>
  axios.get(`${API_BASE}/admin/activity-log`, { headers: adminHeaders(token), withCredentials: true });

export const getSeoPage = (board, classSlug, subjectSlug, topicSlug, pageType) => {
  let url = `${WORKER_API}/seo/page/${board}/${classSlug}/${subjectSlug}/${topicSlug}`;
  if (pageType && pageType !== 'notes') url += `/${pageType}`;
  return axios.get(url);
};

export const getSeoPageBundle = (board, classSlug, subjectSlug, topicSlug, pageType) =>
  axios.get(`${WORKER_API}/seo/page-bundle/${board}/${classSlug}/${subjectSlug}/${topicSlug}`, {
    params: pageType && pageType !== 'notes' ? { pt: pageType } : undefined,
  });

export const getSeoPageTypes = (board, classSlug, subjectSlug, topicSlug) =>
  axios.get(`${WORKER_API}/seo/page-types/${board}/${classSlug}/${subjectSlug}/${topicSlug}`);

export const getSeoRelated = (topicSlug) =>
  axios.get(`${WORKER_API}/seo/related/${topicSlug}`);

export const getChapterBySlug = (board, classSlug, subjectSlug, chapterSlug) =>
  axios.get(`${WORKER_API}/content/chapter-by-slug/${board}/${classSlug}/${subjectSlug}/${chapterSlug}`);

// ── Admin SEO management ──────────────────────────────────────────────────────

export const adminSeoStats = (token) =>
  axios.get(`${API_BASE}/seo/stats`, { headers: adminHeaders(token), withCredentials: true });

export const adminSeoListTopics = (token, params = {}) =>
  axios.get(`${API_BASE}/seo/topics`, { headers: adminHeaders(token), withCredentials: true, params });

export const adminSeoCreateTopic = (token, data) =>
  axios.post(`${API_BASE}/seo/topics`, data, { headers: adminHeaders(token), withCredentials: true });


export const adminSeoDeleteTopic = (token, topicId) =>
  axios.delete(`${API_BASE}/seo/topics/${topicId}`, { headers: adminHeaders(token), withCredentials: true });

export const adminSeoExtractTopics = (token, subjectId, force = false) => {
  const params = {};
  if (subjectId) params.subject_id = subjectId;
  if (force) params.force = true;
  return axios.post(`${API_BASE}/seo/extract-topics`, {}, { headers: adminHeaders(token), withCredentials: true, params });
};

export const adminSeoGenerate = (token, data) =>
  axios.post(`${API_BASE}/seo/generate`, data, { headers: adminHeaders(token), withCredentials: true });

export const adminSeoListPages = (token, params = {}) =>
  axios.get(`${API_BASE}/seo/pages`, { headers: adminHeaders(token), withCredentials: true, params });

export const adminSeoUpdatePageStatus = (token, pageId, status) =>
  axios.patch(`${API_BASE}/seo/pages/${pageId}/status`, null, {
    headers: adminHeaders(token),
    withCredentials: true,
    params: { status },
  });

export const adminSeoRegenerateSitemap = (token) =>
  axios.post(`${API_BASE}/admin/content/regenerate-sitemap`, {}, { headers: adminHeaders(token), withCredentials: true });

export const adminSeoPilot = (token, params = {}) =>
  axios.post(`${API_BASE}/seo/pilot`, null, {
    headers: adminHeaders(token),
    withCredentials: true,
    params,
  });

export const adminSeoAutoRun = (token, pageTypes = null) =>
  axios.post(`${API_BASE}/seo/auto-run`, pageTypes ? { page_types: pageTypes } : {}, { headers: adminHeaders(token), withCredentials: true });

export const adminSeoJobStatus = (token, jobId) =>
  axios.get(`${API_BASE}/seo/jobs/${jobId}`, { headers: adminHeaders(token), withCredentials: true });

export const adminSeoInsights = (token) =>
  axios.get(`${API_BASE}/seo/insights`, { headers: adminHeaders(token), withCredentials: true });

export const adminSeoExpand = (token, boardSlug, pageTypes = null) =>
  axios.post(`${API_BASE}/seo/expand/${boardSlug}`, pageTypes ? { page_types: pageTypes } : {}, { headers: adminHeaders(token), withCredentials: true });

export const adminSeoBulkPublish = (token, pageType = null, subjectId = null) =>
  axios.post(`${API_BASE}/seo/bulk-publish`, null, {
    headers: adminHeaders(token),
    withCredentials: true,
    params: { ...(pageType ? { page_type: pageType } : {}), ...(subjectId ? { subject_id: subjectId } : {}) },
  });

export const adminSeoSubjectCoverage = (token) =>
  axios.get(`${API_BASE}/seo/subject-coverage`, { headers: adminHeaders(token), withCredentials: true });

export const adminSeoRunSubject = (token, subjectId, force = false, pageTypes = null) =>
  axios.post(`${API_BASE}/seo/run-subject`, pageTypes ? { page_types: pageTypes } : {}, {
    headers: adminHeaders(token),
    withCredentials: true,
    params: { subject_id: subjectId, ...(force ? { force: true } : {}) },
  });

export const adminSeoRefreshMeta = (token) =>
  axios.post(`${API_BASE}/seo/refresh-meta`, {}, { headers: adminHeaders(token), withCredentials: true });

export const adminSeoReviewQueue = (token, status = 'draft', limit = 200) =>
  axios.get(`${API_BASE}/seo/review-queue`, { headers: adminHeaders(token), withCredentials: true, params: { status, limit } });

export const adminSeoBulkReviewAction = (token, action, pageIds = [], minScore = null) => {
  const params = new URLSearchParams();
  params.append('action', action);
  pageIds.forEach(id => params.append('page_ids', id));
  if (minScore != null) params.append('min_score', String(minScore));
  return axios.post(`${API_BASE}/seo/review-queue/bulk-action`, null, {
    headers: adminHeaders(token), withCredentials: true, params,
  });
};

export const adminSeoFlagLowQuality = (token) =>
  axios.post(`${API_BASE}/seo/flag-low-quality`, {}, { headers: adminHeaders(token), withCredentials: true });



// ── Payments ─────────────────────────────────────────────────────────────────

export const createPaymentOrder = (plan) =>
  axios.post(`${API_BASE}/payments/create-order`, { plan }, authConfig());

export const verifyPayment = (data) =>
  axios.post(`${API_BASE}/payments/verify`, data, authConfig());

export const recoverPayment = () =>
  axios.post(`${API_BASE}/payments/recover`, {}, authConfig());

export const createCreditTopUp = (credits) =>
  axios.post(`${API_BASE}/payments/credit-topup`, { credits, provider: 'razorpay' }, authConfig());

export const verifyCreditTopUp = (data) =>
  axios.post(`${API_BASE}/payments/credit-topup/verify`, data, authConfig());

export const getPaymentHistory = () =>
  axios.get(`${API_BASE}/user/payments`, authConfig());

export const requestRefund = (paymentId, reason = '') =>
  axios.post(`${API_BASE}/payments/refund-request`, { payment_id: paymentId, reason }, authConfig());

// ── Vertex AI / Gemini Services ──────────────────────────────────────────────
export const vertexHealth = (token) =>
  axios.get(`${API_BASE}/admin/vertex/health`, { headers: adminHeaders(token), withCredentials: true });

export const vertexTranslate = (token, text, target_lang = 'as', source_lang = 'en') =>
  axios.post(`${API_BASE}/admin/vertex/translate`, { text, target_lang, source_lang }, { headers: adminHeaders(token), withCredentials: true });

export const vertexSemanticSearch = (token, query, top_k = 10) =>
  axios.post(`${API_BASE}/admin/vertex/semantic-search`, { query, top_k }, { headers: adminHeaders(token), withCredentials: true });

export const vertexQualityScore = (token, content, page_type, topic, subject) =>
  axios.post(`${API_BASE}/admin/vertex/quality-score`, { content, page_type, topic, subject }, { headers: adminHeaders(token), withCredentials: true });

export const vertexSuggestTopics = (token, subject, class_name, board = 'AHSEC') =>
  axios.post(`${API_BASE}/admin/vertex/suggest-topics`, { subject, class_name, board }, { headers: adminHeaders(token), withCredentials: true });

export const vertexSeoMeta = (token, data) =>
  axios.post(`${API_BASE}/admin/vertex/seo-meta`, data, { headers: adminHeaders(token), withCredentials: true });

export const vertexContentGaps = (token) =>
  axios.get(`${API_BASE}/admin/vertex/content-gaps`, { headers: adminHeaders(token), withCredentials: true });

export const vertexOcr = (token, formData) =>
  axios.post(`${API_BASE}/admin/vertex/ocr`, formData, {
    headers: { ...adminHeaders(token), 'Content-Type': 'multipart/form-data' },
    withCredentials: true,
  });

export const vertexNlpConcepts = (token, text, subject, class_name) =>
  axios.post(`${API_BASE}/admin/vertex/nlp-concepts`, { text, subject, class_name },
    { headers: adminHeaders(token), withCredentials: true });

export const vertexFlashcards = (token, text, subject, class_name, count = 10) =>
  axios.post(`${API_BASE}/admin/vertex/flashcards`, { text, subject, class_name, count },
    { headers: adminHeaders(token), withCredentials: true });

export const vertexMcqGenerator = (token, text, subject, class_name, count = 10, difficulty = 'mixed') =>
  axios.post(`${API_BASE}/admin/vertex/mcq-generator`, { text, subject, class_name, count, difficulty },
    { headers: adminHeaders(token), withCredentials: true });

// ── Upgrade Wave API Helpers ──────────────────────────────────────────────────
export const seoInternalLinksAnalyze = (token) =>
  axios.get(`${API_BASE}/admin/seo/internal-links/analyze`, { headers: adminHeaders(token), withCredentials: true });

export const seoInternalLinksInject = (token, slug) =>
  axios.post(`${API_BASE}/admin/seo/internal-links/inject/${slug}`, {}, { headers: adminHeaders(token), withCredentials: true });

export const seoInjectSchema = (token, slug) =>
  axios.post(`${API_BASE}/admin/seo/inject-schema/${slug}`, {}, { headers: adminHeaders(token), withCredentials: true });

export const seoInjectSchemaBulk = (token) =>
  axios.post(`${API_BASE}/admin/seo/inject-schema-bulk`, {}, { headers: adminHeaders(token), withCredentials: true });

export const seoPipelineStatus = (token) =>
  axios.get(`${API_BASE}/admin/seo/pipeline-status`, { headers: adminHeaders(token), withCredentials: true });

export const seoSitemapValidate = (token) =>
  axios.get(`${API_BASE}/admin/seo/sitemap-validate`, { headers: adminHeaders(token), withCredentials: true });

export const extractFaqs = (token, limit = 100) =>
  axios.get(`${API_BASE}/admin/conversations/extract-faqs?limit=${limit}`, { headers: adminHeaders(token), withCredentials: true });

export const conversationsSentiment = (token) =>
  axios.get(`${API_BASE}/admin/conversations/sentiment`, { headers: adminHeaders(token), withCredentials: true });

export const syncConversations = (token) =>
  axios.post(`${API_BASE}/admin/sync-conversations`, {}, { headers: adminHeaders(token), withCredentials: true });

export const pageConversions = (token, days = 30) =>
  axios.get(`${API_BASE}/admin/analytics/page-conversions?days=${days}`, { headers: adminHeaders(token), withCredentials: true });

export const churnRisk = (token) =>
  axios.get(`${API_BASE}/admin/users/churn-risk`, { headers: adminHeaders(token), withCredentials: true });

export const llmCosts = (token, days = 7) =>
  axios.get(`${API_BASE}/admin/health/llm-costs?days=${days}`, { headers: adminHeaders(token), withCredentials: true });

export const getNotificationTriggers = (token) =>
  axios.get(`${API_BASE}/admin/notifications/triggers`, { headers: adminHeaders(token), withCredentials: true });

export const createNotificationTrigger = (token, data) =>
  axios.post(`${API_BASE}/admin/notifications/triggers`, data, { headers: adminHeaders(token), withCredentials: true });

export const updateNotificationTrigger = (token, id, data) =>
  axios.patch(`${API_BASE}/admin/notifications/triggers/${id}`, data, { headers: adminHeaders(token), withCredentials: true });

export const deleteNotificationTrigger = (token, id) =>
  axios.delete(`${API_BASE}/admin/notifications/triggers/${id}`, { headers: adminHeaders(token), withCredentials: true });


export const cmsAiSuggest = (token, text, action, subject = '', topic = '') =>
  axios.post(`${API_BASE}/admin/cms/ai-suggest`, { text, action, subject, topic }, { headers: adminHeaders(token), withCredentials: true });

export const adminUpdateUserCredits = (token, userId, data) =>
  axios.patch(`${API_BASE}/admin/users/${userId}/credits`, data, { headers: adminHeaders(token), withCredentials: true });

// ── Personalized CMS ────────────────────────────────────────────────────────
export const cmsPersonalize = (body) =>
  apiClient().post('/cms/personalize', body);

export const cmsListPlans = (userId) =>
  apiClient().get(`/cms/${userId}`);

export const adminPipelineAutoGenerate = (token, subjectId, skipExisting = false) =>
  axios.post(`${API_BASE}/admin/pipeline/auto-generate`, { subject_id: subjectId, skip_existing: skipExisting }, { headers: adminHeaders(token), withCredentials: true });

export const adminPipelineStatus = (token, jobId) =>
  axios.get(`${API_BASE}/admin/pipeline/status/${jobId}`, { headers: adminHeaders(token), withCredentials: true });


export const adminIntelligenceOverview = (token) =>
  axios.get(`${API_BASE}/admin/intelligence/overview`, { headers: adminHeaders(token), withCredentials: true });

export const adminContentAutoHeal = (token) =>
  axios.post(`${API_BASE}/admin/content/auto-heal`, {}, { headers: adminHeaders(token), withCredentials: true });

export const adminContentVersionHistory = (token, chapterId) =>
  axios.get(`${API_BASE}/admin/content/version-history/${chapterId}`, { headers: adminHeaders(token), withCredentials: true });

export const postChatFeedback = (data) =>
  axios.post(`${API_BASE}/chat-feedback`, data, { headers: anonHeaders(), withCredentials: true });

export const adminGetChatFeedback = (token, limit = 100, offset = 0) =>
  axios.get(`${API_BASE}/chat-feedback?limit=${limit}&offset=${offset}`, { headers: adminHeaders(token), withCredentials: true });

export const adminGetFeedbackStats = (token) =>
  axios.get(`${API_BASE}/chat-feedback/stats`, { headers: adminHeaders(token), withCredentials: true });

export const adminPurgeAllCache = (token) =>
  axios.post(`${API_BASE}/admin/cache/purge-all`, {}, { headers: adminHeaders(token), withCredentials: true });

export const adminGetSpoofedBots = (token, days = 7) =>
  axios.get(`${API_BASE}/admin/security/spoofed-bots`, { headers: adminHeaders(token), withCredentials: true, params: { days } });

export const adminGetBlockedIps = (token) =>
  axios.get(`${API_BASE}/admin/security/blocked-ips`, { headers: adminHeaders(token), withCredentials: true });

export const adminBlockIp = (token, ip_hash, reason = 'repeat_spoof_offender') =>
  axios.post(`${API_BASE}/admin/security/block-ip`, { ip_hash, reason }, { headers: adminHeaders(token), withCredentials: true });

export const adminUnblockIp = (token, ip_hash) =>
  axios.post(`${API_BASE}/admin/security/unblock-ip`, { ip_hash }, { headers: adminHeaders(token), withCredentials: true });
