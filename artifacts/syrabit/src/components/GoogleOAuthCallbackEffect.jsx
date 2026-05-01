/**
 * GoogleOAuthCallbackEffect — Task #169
 *
 * Handles post-Google-OAuth navigation for the entire app.
 *
 * After supabase.auth.signInWithOAuth() redirects back, Supabase fires
 * onAuthStateChange (in AuthContext) which exchanges the token and sets
 * `user`. This component watches `user` and reads the intent key that
 * GoogleSignInButton stored in sessionStorage before the redirect.
 *
 * Because this component is rendered inside BrowserRouter (via AppRoutes),
 * it can use useNavigate — something AuthContext cannot do since it lives
 * outside the Router.  This makes Google sign-in work correctly regardless
 * of which page the user was on when they clicked the Google button.
 *
 * Email/password sign-ins never write the intent key, so they are
 * unaffected — the effect returns early when the key is absent.
 */
import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { useAuth } from '@/context/AuthContext';
import { GOOGLE_OAUTH_INTENT_KEY } from '@/components/GoogleSignInButton';

export default function GoogleOAuthCallbackEffect() {
  const { user } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (!user) return;

    let intent;
    try {
      intent = sessionStorage.getItem(GOOGLE_OAUTH_INTENT_KEY);
    } catch {
      return;
    }
    if (!intent) return;

    try {
      sessionStorage.removeItem(GOOGLE_OAUTH_INTENT_KEY);
    } catch {}

    const role = user.role || '';

    if (intent === 'signup_with') {
      toast.success('Account created! Welcome to Syrabit.ai!');
      navigate('/onboarding', { replace: true });
    } else {
      toast.success('Welcome back!');
      if (role === 'staff' || role === 'admin') {
        navigate('/staff', { replace: true });
      } else if (!user.onboarding_done) {
        navigate('/onboarding', { replace: true });
      } else {
        navigate('/library', { replace: true });
      }
    }
  }, [user, navigate]);

  return null;
}
