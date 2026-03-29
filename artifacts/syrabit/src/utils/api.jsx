import axios from 'axios';
import { toast } from 'sonner';

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || '';
export const API_BASE = `${BACKEND_URL}/api`;

const authConfig = () => ({ withCredentials: true });

// Global 401 interceptor — redirect admin to login on session expiry
axios.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      const isAdminRoute = window.location.pathname.startsWith('/admin') &&
        !window.location.pathname.startsWith('/admin/login');
      if (isAdminRoute) {
        toast.error('Session expired. Please log in again.');
        window.location.href = '/admin/login';
      }
    }
    return Promise.reject(error);
  }
);

export const apiClient = () =>
  axios.create({ baseURL: API_BASE, withCredentials: true });

export const getBoards = () => axios.get(`${API_BASE}/content/boards`);
export const getClasses = (boardId) => axios.get(`${API_BASE}/content/classes?board_id=${boardId}`);
export const getStreams = (classId) => axios.get(`${API_BASE}/content/streams?class_id=${classId}`);
export const getAllSubjects = () => axios.get(`${API_BASE}/content/subjects`);
export const getSubject = (id) => axios.get(`${API_BASE}/content/subjects/${id}`);
export const getChapters = (subjectId) => axios.get(`${API_BASE}/content/chapters/${subjectId}`);
export const getChunks = (chapterId) => axios.get(`${API_BASE}/content/chunks/${chapterId}`);

export const getConversations = () =>
  axios.get(`${API_BASE}/conversations`, authConfig());

export const getConversation = (id) =>
  axios.get(`${API_BASE}/conversations/${id}`, authConfig());

export const deleteConversation = (id) =>
  axios.delete(`${API_BASE}/conversations/${id}`, authConfig());

export const updateConversation = (id, data) =>
  axios.patch(`${API_BASE}/conversations/${id}`, data, authConfig());

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

export const adminGetAnalytics = (token) =>
  axios.get(`${API_BASE}/admin/analytics`, { headers: adminHeaders(token), withCredentials: true });

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

export const adminConnectGA4 = (token, code, redirectUri) =>
  axios.post(`${API_BASE}/admin/ga4/connect`, { code, redirect_uri: redirectUri }, { headers: adminHeaders(token), withCredentials: true });

export const adminTestGA4 = (token) =>
  axios.get(`${API_BASE}/admin/ga4/test`, { headers: adminHeaders(token), withCredentials: true });

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

export const adminDeleteSubject = (token, id) =>
  axios.delete(`${API_BASE}/admin/content/subjects/${id}`, { headers: adminHeaders(token), withCredentials: true });

export const adminDeleteChapter = (token, id) =>
  axios.delete(`${API_BASE}/admin/content/chapters/${id}`, { headers: adminHeaders(token), withCredentials: true });

export const adminReseed = (token) =>
  axios.post(`${API_BASE}/admin/seed`, {}, { headers: adminHeaders(token), withCredentials: true });

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
  let url = `${API_BASE}/seo/page/${board}/${classSlug}/${subjectSlug}/${topicSlug}`;
  if (pageType && pageType !== 'notes') url += `/${pageType}`;
  return axios.get(url);
};

export const getSeoPageTypes = (board, classSlug, subjectSlug, topicSlug) =>
  axios.get(`${API_BASE}/seo/page-types/${board}/${classSlug}/${subjectSlug}/${topicSlug}`);

export const getSeoRelated = (topicSlug) =>
  axios.get(`${API_BASE}/seo/related/${topicSlug}`);

export const getChapterBySlug = (board, classSlug, subjectSlug, chapterSlug) =>
  axios.get(`${API_BASE}/content/chapter-by-slug/${board}/${classSlug}/${subjectSlug}/${chapterSlug}`);

// ── Admin SEO management ──────────────────────────────────────────────────────

export const adminSeoStats = (token) =>
  axios.get(`${API_BASE}/seo/stats`, { headers: adminHeaders(token), withCredentials: true });

export const adminSeoListTopics = (token, params = {}) =>
  axios.get(`${API_BASE}/seo/topics`, { headers: adminHeaders(token), withCredentials: true, params });

export const adminSeoCreateTopic = (token, data) =>
  axios.post(`${API_BASE}/seo/topics`, data, { headers: adminHeaders(token), withCredentials: true });

export const adminSeoUpdateTopic = (token, topicId, data) =>
  axios.patch(`${API_BASE}/seo/topics/${topicId}`, data, { headers: adminHeaders(token), withCredentials: true });

export const adminSeoDeleteTopic = (token, topicId) =>
  axios.delete(`${API_BASE}/seo/topics/${topicId}`, { headers: adminHeaders(token), withCredentials: true });

export const adminSeoExtractTopics = (token, subjectId) =>
  axios.post(`${API_BASE}/seo/extract-topics`, subjectId ? { subject_id: subjectId } : {}, { headers: adminHeaders(token), withCredentials: true });

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

// ── QA Engine ─────────────────────────────────────────────────────────────────
export const getTopicQa = (board, classSlug, subjectSlug, topicSlug) =>
  axios.get(`${API_BASE}/seo/qa/${board}/${classSlug}/${subjectSlug}/${topicSlug}`);

export const adminListChatMessages = (token, params = {}) =>
  axios.get(`${API_BASE}/admin/chat-messages`, { headers: adminHeaders(token), withCredentials: true, params });

export const adminListQaPairs = (token, params = {}) =>
  axios.get(`${API_BASE}/admin/qa`, { headers: adminHeaders(token), withCredentials: true, params });

export const adminCreateQaPair = (token, data) =>
  axios.post(`${API_BASE}/admin/qa`, data, { headers: adminHeaders(token), withCredentials: true });

export const adminUpdateQaStatus = (token, qaId, status) =>
  axios.patch(`${API_BASE}/admin/qa/${qaId}/status`, { status }, { headers: adminHeaders(token), withCredentials: true });

export const adminDeleteQaPair = (token, qaId) =>
  axios.delete(`${API_BASE}/admin/qa/${qaId}`, { headers: adminHeaders(token), withCredentials: true });

export const adminPromoteChatToQa = (token, msgId) =>
  axios.post(`${API_BASE}/admin/qa/from-chat/${msgId}`, {}, { headers: adminHeaders(token), withCredentials: true });

// ── Payments ─────────────────────────────────────────────────────────────────

export const createPaymentOrder = (plan) =>
  axios.post(`${API_BASE}/payments/create-order`, { plan }, authConfig());

export const verifyPayment = (data) =>
  axios.post(`${API_BASE}/payments/verify`, data, authConfig());

export const createCreditTopUp = (credits) =>
  axios.post(`${API_BASE}/payments/credit-topup`, { credits, provider: 'razorpay' }, authConfig());

export const verifyCreditTopUp = (data) =>
  axios.post(`${API_BASE}/payments/credit-topup/verify`, data, authConfig());

export const createStripeCheckout = (plan, successUrl, cancelUrl) =>
  axios.post(`${API_BASE}/payments/stripe/create-checkout`, { plan, success_url: successUrl, cancel_url: cancelUrl }, authConfig());

// ── Vertex AI / Gemini Services ──────────────────────────────────────────────
export const vertexHealth = (token) =>
  axios.get(`${API_BASE}/admin/vertex/health`, { headers: adminHeaders(token), withCredentials: true });

export const vertexTranslate = (token, text, target_lang = 'as', source_lang = 'en') =>
  axios.post(`${API_BASE}/admin/vertex/translate`, { text, target_lang, source_lang }, { headers: adminHeaders(token), withCredentials: true });

export const vertexSemanticSearch = (token, query, top_k = 10) =>
  axios.post(`${API_BASE}/admin/vertex/semantic-search`, { query, top_k }, { headers: adminHeaders(token), withCredentials: true });

export const vertexEnhance = (token, content, page_type, subject, topic, class_name) =>
  axios.post(`${API_BASE}/admin/vertex/enhance`, { content, page_type, subject, topic, class_name }, { headers: adminHeaders(token), withCredentials: true });

export const vertexQualityScore = (token, content, page_type, topic, subject) =>
  axios.post(`${API_BASE}/admin/vertex/quality-score`, { content, page_type, topic, subject }, { headers: adminHeaders(token), withCredentials: true });

export const vertexSuggestTopics = (token, subject, class_name, board = 'AHSEC') =>
  axios.post(`${API_BASE}/admin/vertex/suggest-topics`, { subject, class_name, board }, { headers: adminHeaders(token), withCredentials: true });

export const vertexSeoMeta = (token, data) =>
  axios.post(`${API_BASE}/admin/vertex/seo-meta`, data, { headers: adminHeaders(token), withCredentials: true });

export const vertexContentGaps = (token) =>
  axios.get(`${API_BASE}/admin/vertex/content-gaps`, { headers: adminHeaders(token), withCredentials: true });

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

export const syllabusImportPdf = (token, formData) =>
  axios.post(`${API_BASE}/admin/syllabus/import-pdf`, formData, { headers: { ...adminHeaders(token), 'Content-Type': 'multipart/form-data' }, withCredentials: true });

export const syllabusExtractPdf = (token, formData) => {
  formData.append('dry_run', 'true');
  return axios.post(`${API_BASE}/admin/syllabus/import-pdf`, formData, { headers: { ...adminHeaders(token), 'Content-Type': 'multipart/form-data' }, withCredentials: true });
};

export const syllabusConfirmImport = (token, payload) =>
  axios.post(`${API_BASE}/admin/syllabus/confirm-import`, payload, { headers: adminHeaders(token), withCredentials: true });

export const cmsAiSuggest = (token, text, action, subject = '', topic = '') =>
  axios.post(`${API_BASE}/admin/cms/ai-suggest`, { text, action, subject, topic }, { headers: adminHeaders(token), withCredentials: true });

export const adminUpdateUserCredits = (token, userId, data) =>
  axios.patch(`${API_BASE}/admin/users/${userId}/credits`, data, { headers: adminHeaders(token), withCredentials: true });

export const adminSearchUsers = (token, params = {}) =>
  axios.get(`${API_BASE}/admin/users`, { headers: adminHeaders(token), withCredentials: true, params });

export const adminGetPlanTiers = (token) =>
  axios.get(`${API_BASE}/admin/plan-config`, { headers: adminHeaders(token), withCredentials: true });

export const adminUpdatePlanTier = (token, plan, data) =>
  axios.patch(`${API_BASE}/admin/plan-config/${plan}`, data, { headers: adminHeaders(token), withCredentials: true });
