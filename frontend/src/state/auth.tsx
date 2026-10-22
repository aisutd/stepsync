import AsyncStorage from '@react-native-async-storage/async-storage';
import type { Session } from '@supabase/supabase-js';
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';

import { supabase, supabaseConfigured } from '@/lib/supabase';

const REMEMBER_KEY = 'stepsync.rememberMe';

/** Saved before signing in; read on the next launch. */
export async function setRememberMe(remember: boolean) {
  try {
    await AsyncStorage.setItem(REMEMBER_KEY, remember ? '1' : '0');
  } catch {
    // Not critical: the default is to stay signed in.
  }
}

type Auth = {
  session: Session | null;
  /** True while the saved session is being read on launch. */
  loading: boolean;
};

const AuthContext = createContext<Auth>({ session: null, loading: false });

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(supabaseConfigured);

  useEffect(() => {
    if (!supabaseConfigured) return;

    (async () => {
      try {
        const { data } = await supabase.auth.getSession();
        const remember = await AsyncStorage.getItem(REMEMBER_KEY).catch(() => null);
        // "Remember me" was unchecked last time: start this launch signed out.
        if (data.session && remember === '0') {
          await supabase.auth.signOut();
          setSession(null);
        } else {
          setSession(data.session);
        }
      } finally {
        setLoading(false);
      }
    })();

    // Fires on sign in, sign out, and token refresh.
    const { data } = supabase.auth.onAuthStateChange((_event, next) => setSession(next));
    return () => data.subscription.unsubscribe();
  }, []);

  return <AuthContext.Provider value={{ session, loading }}>{children}</AuthContext.Provider>;
}

export function useAuth(): Auth {
  return useContext(AuthContext);
}
