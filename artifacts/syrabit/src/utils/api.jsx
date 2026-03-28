import axios from 'axios';

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || '';
export const API_BASE = `${BACKEND_URL}/api`;

const authConfig = () => ({ withCredentials: true });

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

export const adminGetUsers = (token) =>
  axios.get(`${API_BASE}/admin/users`, { headers: adminHeaders(token), withCredentials: true });

export const adminUpdateUserStatus = (token, userId, status) =>
  axios.patch(`${API_BASE}/admin/users/${userId}/status`, { status }, { headers: adminHeaders(token), withCredentials: true });

export const adminUpdateUserPlan = (token, userId, plan) =>
  axios.patch(`${API_BASE}/admin/users/${userId}/plan`, { plan }, { headers: adminHeaders(token), withCredentials: true });

export const adminGetConversations = (token) =>
  axios.get(`${API_BASE}/admin/conversations`, { headers: adminHeaders(token), withCredentials: true });

export const adminGetAnalytics = (token) =>
  axios.get(`${API_BASE}/admin/analytics`, { headers: adminHeaders(token), withCredentials: true });

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

// ── Payments (excluded from current build) ───────────────────────────────────

export const createPaymentOrder = (plan) =>
  axios.post(`${API_BASE}/payments/create-order`, { plan }, authConfig());

export const verifyPayment = (data) =>
  axios.post(`${API_BASE}/payments/verify`, data, authConfig());
