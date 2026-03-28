import { useState, useEffect } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import { Loader2 } from 'lucide-react';
import AdminSyllabusManager from './AdminSyllabusManager';

const API = `${import.meta.env.VITE_BACKEND_URL || ''}/api`;

export default function AdminSyllabus({ adminToken }) {
  const [boards, setBoards] = useState([]);
  const [classes, setClasses] = useState([]);
  const [streams, setStreams] = useState([]);
  const [subjects, setSubjects] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const [b, c, s, sub] = await Promise.all([
          axios.get(`${API}/content/boards`),
          axios.get(`${API}/content/classes`),
          axios.get(`${API}/content/streams`),
          axios.get(`${API}/content/subjects`),
        ]);
        setBoards(b.data || []);
        setClasses(c.data || []);
        setStreams(s.data || []);
        setSubjects(sub.data || []);
      } catch {
        toast.error('Failed to load content hierarchy');
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-white/40 py-8">
        <Loader2 size={16} className="animate-spin" />
        Loading syllabus data...
      </div>
    );
  }

  return (
    <AdminSyllabusManager
      adminToken={adminToken}
      boards={boards}
      classes={classes}
      streams={streams}
      subjects={subjects}
    />
  );
}
