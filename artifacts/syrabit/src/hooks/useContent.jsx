/**
 * useContent.js — React Query v5 hooks for all content fetching.
 * Mirrors the spec: useSubjects, useBoards, useClasses, useStreams, useSavedSubjects
 */
import { useQuery } from '@tanstack/react-query';
import axios from 'axios';

const API_BASE = `${import.meta.env.VITE_BACKEND_URL || ''}/api`;

// ── Raw fetchers ────────────────────────────────────────────────────────────
const fetchBoards = () =>
  axios.get(`${API_BASE}/content/boards`).then((r) => r.data);

const fetchClasses = () =>
  axios.get(`${API_BASE}/content/classes`).then((r) => r.data);

const fetchStreams = () =>
  axios.get(`${API_BASE}/content/streams`).then((r) => r.data);

const fetchSubjects = () =>
  axios.get(`${API_BASE}/content/subjects`).then((r) => r.data);

const fetchLibraryBundle = () =>
  axios.get(`${API_BASE}/content/library-bundle`).then((r) => r.data);

const fetchSubject = (id) =>
  axios.get(`${API_BASE}/content/subjects/${id}`).then((r) => r.data);

const fetchChapters = (subjectId) =>
  axios.get(`${API_BASE}/content/chapters/${subjectId}`).then((r) => r.data);

const fetchChunks = (chapterId) =>
  axios.get(`${API_BASE}/content/chunks/${chapterId}`).then((r) => r.data);

const fetchSavedSubjects = () =>
  axios
    .get(`${API_BASE}/user/profile`, { withCredentials: true })
    .then((r) => r.data.saved_subjects || []);

// ── Hooks ────────────────────────────────────────────────────────────────────

/** All boards (30min stale) */
export const useBoards = () =>
  useQuery({
    queryKey: ['boards'],
    queryFn: fetchBoards,
    staleTime: 30 * 60 * 1000,
  });

/** All classes (30min stale) */
export const useClasses = () =>
  useQuery({
    queryKey: ['classes', undefined],
    queryFn: fetchClasses,
    staleTime: 30 * 60 * 1000,
  });

/** All streams (30min stale) */
export const useStreams = () =>
  useQuery({
    queryKey: ['streams', undefined],
    queryFn: fetchStreams,
    staleTime: 30 * 60 * 1000,
  });

/** All published subjects (10min stale) */
export const useSubjects = () =>
  useQuery({
    queryKey: ['subjects', undefined],
    queryFn: fetchSubjects,
    staleTime: 10 * 60 * 1000,
  });

/** Single subject detail (10min stale) */
export const useSubject = (id) =>
  useQuery({
    queryKey: ['subject', id],
    queryFn: () => fetchSubject(id),
    staleTime: 10 * 60 * 1000,
    enabled: !!id,
  });

/** Chapters for a subject (10min stale) */
export const useChapters = (subjectId) =>
  useQuery({
    queryKey: ['chapters', subjectId],
    queryFn: () => fetchChapters(subjectId),
    staleTime: 10 * 60 * 1000,
    enabled: !!subjectId,
  });

/** Chunks for a chapter (10min stale) */
export const useChunks = (chapterId) =>
  useQuery({
    queryKey: ['chunks', chapterId],
    queryFn: () => fetchChunks(chapterId),
    staleTime: 10 * 60 * 1000,
    enabled: !!chapterId,
  });

/** Saved subject IDs for authenticated user (1min stale) */
export const useSavedSubjects = (user) =>
  useQuery({
    queryKey: ['saved-subjects'],
    queryFn: fetchSavedSubjects,
    staleTime: 1 * 60 * 1000,
    enabled: !!user,
  });

export const useLibraryBundle = () =>
  useQuery({
    queryKey: ['library-bundle'],
    queryFn: fetchLibraryBundle,
    staleTime: 30 * 60 * 1000,
    gcTime: 60 * 60 * 1000,
  });
