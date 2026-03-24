import { useEffect, useState } from 'react';
import { useParams, useNavigate, Navigate } from 'react-router-dom';
import axios from 'axios';
import { Loader2 } from 'lucide-react';

const API_BASE = (import.meta.env.VITE_BACKEND_URL || '') + '/api';

export default function SeoSubjectRedirect() {
  const { board, classSlug, streamSlug, subjectSlug } = useParams();
  const navigate = useNavigate();
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await axios.get(
          `${API_BASE}/content/resolve-subject/${board}/${classSlug}/${streamSlug}/${subjectSlug}`
        );
        if (!cancelled && res.data?.id) {
          navigate(`/subject/${res.data.id}`, { replace: true });
        } else if (!cancelled) {
          setNotFound(true);
        }
      } catch {
        if (!cancelled) setNotFound(true);
      }
    })();
    return () => { cancelled = true; };
  }, [board, classSlug, streamSlug, subjectSlug, navigate]);

  if (notFound) {
    return <Navigate to="/library" replace />;
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <Loader2 className="w-8 h-8 animate-spin text-primary" />
    </div>
  );
}
